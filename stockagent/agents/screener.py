"""
① 스크리너 에이전트.

수백~수천 종목 중에서 '깊게 분석할 가치가 있는 후보'를 정량 지표로 압축합니다.
LLM을 쓰지 않고 규칙/점수로만 동작하여 빠르고 저렴합니다.

기본 전략(설명):
  - 대상: 시가총액 상위 pool_size 종목 (유동성/데이터 안정성 확보)
  - 지표: 3개월·1개월 수익률(모멘텀), 60일선 위 여부(추세), 52주 고점 대비 위치
  - 점수: 상승 추세이면서 과열(고점 근접)되지 않은 종목에 가점
  - 우선주/스팩/ETF 등은 이름 규칙으로 제외
두 시장 모두 FinanceDataReader 로 시세를 받아 동일한 방식으로 채점합니다.
"""
from __future__ import annotations

import re
from typing import Optional

import pandas as pd

from ..models import Candidate

# 제외할 이름 패턴 (KR 우선주/스팩/리츠/ETF 등). ETF는 브랜드명으로도 필터.
_EXCLUDE_RE = re.compile(
    r"(?:우[BC]?$|스팩|제\d+호|리츠|ETF|ETN|인버스|레버리지|선물|"
    r"KODEX|TIGER|KBSTAR|ARIRANG|KINDEX|HANARO|KOSEF|SOL |ACE |PLUS |RISE |WON )")


def _clean_universe(df: pd.DataFrame, market: str, pool_size: int) -> pd.DataFrame:
    df = df.copy()
    if "Name" in df.columns:
        df = df[~df["Name"].astype(str).str.contains(_EXCLUDE_RE)]
    # 시가총액 상위로 pool 구성 (있을 때만)
    if "Marcap" in df.columns:
        df = df.sort_values("Marcap", ascending=False)
    return df.head(pool_size)


def _momentum_score(close: pd.Series) -> tuple[float, list[str], dict]:
    """시세 시리즈로부터 점수/근거/지표를 계산."""
    close = close.dropna()
    if len(close) < 70:
        return -1e9, ["시세 데이터 부족"], {}

    # 거래정지 의심: 마지막 거래일이 7일(달력) 이상 과거면 후보에서 제외
    try:
        last = pd.Timestamp(close.index[-1])
        now = pd.Timestamp.now(tz=last.tz) if last.tz is not None else pd.Timestamp.now()
        if (now - last).days > 7:
            return -1e9, ["최근 시세 없음(거래정지 의심)"], {}
    except Exception:
        pass

    # 등락률 기준을 리포트(common.pct_change: periods+1 전 종가 대비)와 동일하게 통일
    ret_1m = close.iloc[-1] / close.iloc[-22] - 1
    ret_3m = close.iloc[-1] / close.iloc[-64] - 1
    ma60 = close.iloc[-60:].mean()
    above_ma60 = close.iloc[-1] > ma60
    high_252 = close.iloc[-252:].max() if len(close) >= 252 else close.max()
    from_high = close.iloc[-1] / high_252 - 1  # 0에 가까울수록 고점 근접(음수)

    reasons = []
    score = 0.0
    # 모멘텀 기여에 상한을 둬 '급등주 몰빵'을 방지 (2026-07-23, AI 리뷰 #8).
    #  이전엔 3개월 +100%면 +60점이라 급등주만 뽑혔음 → 기여를 ±25/±15로 클램프.
    score += max(min(ret_3m * 100 * 0.6, 25), -25)
    score += max(min(ret_1m * 100 * 0.3, 15), -15)
    if above_ma60:
        score += 10
        reasons.append("60일 이동평균선 위(상승 추세)")
    # 고점 대비 위치: 과열(고점 근접) 감점 강화, 완만한 조정 구간 가점
    if -0.25 <= from_high <= -0.05:
        score += 10
        reasons.append("52주 고점 대비 완만한 조정 구간")
    elif from_high > -0.02:
        score -= 15
        reasons.append("52주 고점 근접(과열 주의)")
    elif from_high > -0.05:
        score -= 7
        reasons.append("52주 고점 인접")
    # 20일선 과이격(단기 급등) 감점 — 급등 직후 추격 억제
    ma20 = close.iloc[-20:].mean()
    disparity = close.iloc[-1] / ma20 - 1 if ma20 else 0
    if disparity > 0.15:
        score -= 10
        reasons.append(f"20일선 +{disparity*100:.0f}% 과이격(단기 급등)")
    # 1개월 모멘텀이 3개월보다 크게 꺾이면(고점 후 둔화) 감점
    if ret_3m > 0.3 and ret_1m < ret_3m / 3:
        score -= 8
        reasons.append("상승 탄력 둔화(고점 후 조정 조짐)")

    if ret_3m > 0:
        reasons.append(f"최근 3개월 수익률 +{ret_3m*100:.1f}%")
    else:
        reasons.append(f"최근 3개월 수익률 {ret_3m*100:.1f}%")

    metrics = {
        "ret_1m": round(ret_1m * 100, 1),
        "ret_3m": round(ret_3m * 100, 1),
        "above_ma60": above_ma60,
        "from_high": round(from_high * 100, 1),
    }
    return round(score, 2), reasons, metrics


def _score_us_batch(pool: pd.DataFrame) -> tuple[list[Candidate], int]:
    """S&P500 전체를 yfinance 일괄 다운로드로 채점. (후보 리스트, 실패 수) 반환.

    개별 조회(fdr.DataReader × N)는 500종목에 수십 분이 걸리지만,
    yf.download 는 멀티스레드 일괄 요청이라 1~2분 안에 전체를 받아온다.
    """
    import yfinance as yf

    rows = []
    for _, row in pool.iterrows():
        code = str(row.get("Code", "")).strip()
        if code:
            rows.append((code, str(row.get("Name", code)) or code))
    ymap = {c: c.replace(".", "-") for c, _ in rows}  # BRK.B → BRK-B (야후 표기)

    df = yf.download(list(ymap.values()), period="18mo", interval="1d",
                     auto_adjust=True, progress=False, threads=True)
    closes = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]]

    scored: list[Candidate] = []
    failed = 0
    for code, name in rows:
        col = ymap[code]
        if col not in closes.columns:
            failed += 1
            continue
        score, reasons, _ = _momentum_score(closes[col])
        if score <= -1e8:
            failed += 1
            continue
        scored.append(Candidate(ticker=code, name=name, market="US", score=score, reasons=reasons))
    return scored, failed


def screen(
    market: str,
    top_n: int = 3,
    pool_size: int = 40,
    explicit_tickers: Optional[list[str]] = None,
    log=print,
) -> list[Candidate]:
    """후보 종목 리스트를 반환.

    explicit_tickers 가 주어지면 스크리닝 없이 그 종목들을 후보로 사용(빠른 테스트용).
    """
    import FinanceDataReader as fdr

    from ..datasources import kr, us

    src = kr if market == "KR" else us

    # --- 빠른 경로: 명시 종목 ---
    if explicit_tickers:
        universe = src.list_universe()
        name_map = {}
        if {"Code", "Name"}.issubset(universe.columns):
            name_map = dict(zip(universe["Code"].astype(str).str.zfill(6 if market == "KR" else 0),
                                universe["Name"]))
        cands = []
        for t in explicit_tickers:
            key = t.zfill(6) if market == "KR" else t
            cands.append(Candidate(ticker=t, name=name_map.get(key, t), market=market,
                                   score=0, reasons=["사용자 지정 종목"]))
        return cands

    # --- 자동 스크리닝 ---
    log(f"  [스크리너] {market} 상장목록 로드 중...")
    universe = src.list_universe()

    scored: list[Candidate] = []
    failed = 0
    if market == "US":
        # 미국: S&P500 목록에 시가총액 컬럼이 없어 '시총 상위 N' 컷이 불가능
        #  → 전체를 yfinance 일괄 다운로드로 채점 (개별 조회보다 빠르고 유니버스 왜곡 없음)
        pool = _clean_universe(universe, market, len(universe))
        log(f"  [스크리너] 미국 유니버스 {len(pool)}종목(S&P500+나스닥100) 일괄 채점 중... (일괄 시세 다운로드, 1~2분)")
        scored, failed = _score_us_batch(pool)
    else:
        pool = _clean_universe(universe, market, pool_size)
        log(f"  [스크리너] 후보풀 {len(pool)}종목에 대해 모멘텀/추세 채점 중... (시세 조회로 다소 시간이 걸립니다)")
        for _, row in pool.iterrows():
            code = str(row.get("Code", "")).strip()
            if market == "KR":
                code = code.zfill(6)
            name = str(row.get("Name", code))
            if not code:
                continue
            try:
                hist = fdr.DataReader(code, "2023-01-01")
                if hist is None or hist.empty:
                    failed += 1
                    continue
                close = hist["Close"] if "Close" in hist.columns else hist.iloc[:, -1]
                score, reasons, _ = _momentum_score(close)
                if score <= -1e8:  # 데이터 부족/거래정지 의심 → 제외
                    failed += 1
                    continue
                scored.append(Candidate(ticker=code, name=name, market=market, score=score, reasons=reasons))
            except Exception:
                failed += 1
                continue

    if failed:
        log(f"    · 시세 부족/조회 실패로 {failed}종목 제외")
    scored.sort(key=lambda c: c.score, reverse=True)
    top = scored[:top_n]
    for c in top:
        log(f"    ✓ 후보 선정: {c.name}({c.ticker})  점수 {c.score}")
    return top
