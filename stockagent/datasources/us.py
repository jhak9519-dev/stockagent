"""
미국 시장 데이터 소스 (yfinance 기반, 무료).

시세·밸류에이션 지표·재무제표·업종 정보를 yfinance 한 곳에서 수집합니다.
"""
from __future__ import annotations

import io
from typing import Optional

import pandas as pd

from ..models import Candidate, StockData
from .common import enrich_price_metrics

# yfinance 투자의견 코드 -> 한국어
_REC_MAP = {
    "strong_buy": "적극 매수", "buy": "매수", "hold": "중립",
    "underperform": "비중축소", "sell": "매도", "strong_sell": "적극 매도",
}

# yfinance 재무제표 라벨 -> 표준 키
_FIN_LABELS = {
    "revenue": ["Total Revenue", "TotalRevenue"],
    "operating_income": ["Operating Income", "OperatingIncome"],
    "net_income": ["Net Income", "NetIncome", "Net Income Common Stockholders"],
    "assets": ["Total Assets", "TotalAssets"],
    "liabilities": ["Total Liabilities Net Minority Interest", "Total Liab"],
    "equity": ["Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity"],
    # 현금흐름표 (tk.cashflow 에서 추출)
    "op_cash_flow": ["Operating Cash Flow", "Total Cash From Operating Activities",
                     "Cash Flow From Continuing Operating Activities"],
    "free_cash_flow": ["Free Cash Flow"],
}


def _nasdaq100_codes() -> list[str]:
    """위키피디아에서 나스닥100 구성종목 티커를 파싱 (실패 시 빈 리스트 — 배치를 막지 않음)."""
    try:
        import requests

        # 구성종목 표는 본문이 아니라 별도 문서에 있음 (2026-07 확인)
        html = requests.get(
            "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies",
            timeout=15, headers={"User-Agent": "Mozilla/5.0"},
        ).text
        tables = pd.read_html(io.StringIO(html))
        for t in tables:
            cols = {str(c).lower(): c for c in t.columns}
            key = next((cols[c] for c in cols if "ticker" in c or "symbol" in c), None)
            if key is None:
                continue
            codes = [str(x).strip() for x in t[key].dropna() if str(x).strip()]
            if len(codes) >= 80:  # 나스닥100 표가 맞는지 크기로 검증
                return codes
        return []
    except Exception:
        return []


def list_universe() -> pd.DataFrame:
    """미국 유니버스 = S&P500 ∪ 나스닥100 (컬럼: Code, Name, Market).

    S&P500 만으로는 나스닥 상장 대형 성장주(MELI 등) 일부가 빠져,
    나스닥100 을 합집합으로 추가한다 (2026-07-20, 사용자 요청 A안).
    """
    import FinanceDataReader as fdr

    df = fdr.StockListing("S&P500")
    rename = {}
    for c in df.columns:
        cl = c.lower()
        if cl in ("symbol", "code"):
            rename[c] = "Code"
        elif cl in ("name",):
            rename[c] = "Name"
        elif cl in ("sector",):
            rename[c] = "Sector"
    df = df.rename(columns=rename)

    # 나스닥100 중 S&P500에 없는 종목 추가 (이름은 티커로 두고, 수집 시 공식명으로 교체됨)
    extra = [c for c in _nasdaq100_codes() if c not in set(df["Code"].astype(str))]
    if extra:
        df = pd.concat([df, pd.DataFrame({"Code": extra, "Name": extra})], ignore_index=True)

    df["Market"] = "US"
    return df


def _extract_financials(fin_df: pd.DataFrame, years: int = 3) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    if fin_df is None or fin_df.empty:
        return out
    cols = list(fin_df.columns)[:years]  # 최신 연도부터
    for key, labels in _FIN_LABELS.items():
        for label in labels:
            if label in fin_df.index:
                for col in cols:
                    val = fin_df.loc[label, col]
                    if pd.notna(val):
                        year = str(col.year) if hasattr(col, "year") else str(col)
                        out.setdefault(key, {})[year] = float(val)
                break
    return out


def fetch(candidate: Candidate) -> StockData:
    import yfinance as yf

    data = StockData(ticker=candidate.ticker, name=candidate.name, market="US", currency="USD")
    tk = yf.Ticker(candidate.ticker)

    # 1) 시세
    try:
        hist = tk.history(period="2y")
        if hist is not None and not hist.empty:
            data.price_history = hist
            enrich_price_metrics(data, hist["Close"], hist.get("Volume"))
            # 기술적 지표(일목·볼린저·이평·RSI·MACD) 계산
            from . import technical
            technical.compute(data, hist)
    except Exception as e:
        data.warnings.append(f"시세 수집 실패: {e}")

    # 2) 기본 정보/밸류에이션 지표
    try:
        info = tk.info or {}
        data.market_cap = info.get("marketCap")
        data.per = info.get("trailingPE")
        data.pbr = info.get("priceToBook")
        data.eps = info.get("trailingEps")
        data.bps = info.get("bookValue")
        # 배당수익률: 연배당금/주가로 직접 계산(가장 정확). yfinance의 dividendYield는
        # 버전에 따라 소수/백분율이 뒤섞여 오므로 신뢰하지 않는다.
        rate = info.get("dividendRate") or info.get("trailingAnnualDividendRate")
        px = data.price or info.get("currentPrice")
        if rate and px:
            data.dividend_yield = round(rate / px * 100, 2)
        else:
            dy = info.get("dividendYield")
            if dy:
                # rate 정보가 없을 때만 사용. yfinance 버전에 따라 소수(0.0034)/백분율(0.34)이
                # 섞여 오므로, 0.2 미만이면 소수로 보고 백분율로 환산한다.
                data.dividend_yield = round(dy * 100 if dy < 0.2 else dy, 2)
        data.sector = info.get("sector")
        data.industry = info.get("industry")
        data.name = info.get("longName") or info.get("shortName") or data.name
        if not data.price:
            data.price = info.get("currentPrice")
        # 시장 컨센서스(애널리스트)
        data.consensus_target = info.get("targetMeanPrice")
        data.consensus_high = info.get("targetHighPrice")
        data.consensus_low = info.get("targetLowPrice")
        rec = info.get("recommendationKey")
        data.consensus_rating = _REC_MAP.get(rec) if rec and rec != "none" else None
        data.analyst_count = info.get("numberOfAnalystOpinions")
        # 수급 참고 지표 (미국은 투자자 유형별 매매 데이터가 없어 보유·공매도로 갈음)
        try:
            fl = {}
            if info.get("heldPercentInstitutions") is not None:
                fl["institution_hold"] = round(info["heldPercentInstitutions"] * 100, 1)
            if info.get("heldPercentInsiders") is not None:
                fl["insider_hold"] = round(info["heldPercentInsiders"] * 100, 1)
            if info.get("shortPercentOfFloat") is not None:
                fl["short_pct_float"] = round(info["shortPercentOfFloat"] * 100, 1)
            if info.get("shortRatio") is not None:
                fl["short_ratio"] = round(float(info["shortRatio"]), 1)
            # 일별 주가·등락률·거래량 (최근 7거래일) — 미국은 투자자별 매매 데이터가 없어 이걸로 대체
            try:
                h = data.price_history
                if h is not None and not getattr(h, "empty", True) and len(h) >= 2:
                    closes = h["Close"].dropna()
                    vols = h["Volume"] if "Volume" in h.columns else None
                    daily = []
                    for i in range(len(closes) - 1, max(0, len(closes) - 8), -1):
                        chg = (closes.iloc[i] / closes.iloc[i - 1] - 1) * 100 if i > 0 else None
                        v = float(vols.iloc[i]) if vols is not None else None
                        daily.append({
                            "date": closes.index[i].strftime("%m/%d"),
                            "close": round(float(closes.iloc[i]), 2),
                            "change": round(chg, 2) if chg is not None else None,
                            "volume": v,
                        })
                    if daily:
                        fl["daily"] = daily
            except Exception:
                pass
            data.trading_flows = fl or None
        except Exception:
            pass
        # 다음 실적 발표(예정)일 — 이벤트 리스크 표기용 (실패해도 무시)
        #  ⚠ earningsTimestamp는 '가장 최근(이미 지난)' 실적일일 수 있으므로, 미래 예정일만 채택.
        try:
            from datetime import datetime as _dt
            now = _dt.now().timestamp()
            cands = [info.get(k) for k in
                     ("earningsTimestamp", "earningsTimestampStart", "earningsTimestampEnd")]
            future = [t for t in cands if t and t > now]
            if future:
                data.earnings_date = _dt.fromtimestamp(min(future)).strftime("%Y-%m-%d")
        except Exception:
            pass
    except Exception as e:
        data.warnings.append(f"기업정보 수집 실패: {e}")

    # 3) 재무제표 (손익 + 재무상태 + 현금흐름)
    try:
        data.financials = _extract_financials(tk.financials)
        bs = _extract_financials(tk.balance_sheet)
        for k, v in bs.items():
            data.financials.setdefault(k, {}).update(v)
        try:
            cf = _extract_financials(tk.cashflow)
            for k, v in cf.items():
                data.financials.setdefault(k, {}).update(v)
        except Exception:
            pass  # 현금흐름은 보조 지표 — 실패해도 무시
        if not data.financials:
            data.warnings.append("yfinance 재무 데이터를 가져오지 못했습니다.")
    except Exception as e:
        data.warnings.append(f"재무 수집 실패: {e}")

    # 4) 뉴스 + 증권사 리포트 (구글 뉴스 RSS) — 두 목록의 중복 기사는 뉴스 쪽에서 제거
    from . import news
    q = data.name or candidate.ticker
    data.broker_reports = news.fetch_broker_reports(q, market="US")
    seen = {n["title"] for n in data.broker_reports}
    data.news = [n for n in news.fetch_news(q, market="US", limit=8) if n["title"] not in seen]

    return data
