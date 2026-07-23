"""
한국 시장 데이터 소스.

- 시세/상장목록: FinanceDataReader (무료)
- 재무제표: DART Open API (무료, 키 필요)

DART는 종목코드(6자리)가 아니라 '고유번호(corp_code, 8자리)'로 재무를 조회하므로,
최초 1회 전체 매핑표(zip)를 내려받아 cache 폴더에 저장해 재사용합니다.
"""
from __future__ import annotations

import io
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from ..config import settings
from ..models import Candidate, StockData
from .common import enrich_price_metrics, safe_ratio

DART_BASE = "https://opendart.fss.or.kr/api"
_CORP_MAP_CACHE = settings.cache_dir / "dart_corp_map.parquet"

# DART 재무제표에서 뽑을 핵심 계정.
# (재무제표구분 sj_div, [계정명 후보]) — 같은 이름이 자본변동표(SCE) 등에도 나오므로
# 재무상태표(BS)/손익계산서(IS·CIS)로 한정해 오염을 방지한다.
_BS = ("BS",)              # 재무상태표
_IS = ("IS", "CIS")        # 손익계산서 / 포괄손익계산서
_CF = ("CF",)              # 현금흐름표
_ACCOUNT_SPEC = {
    "revenue": (_IS, ["매출액", "수익(매출액)", "영업수익", "매출"]),
    "operating_income": (_IS, ["영업이익", "영업이익(손실)"]),
    "net_income": (_IS, ["당기순이익", "당기순이익(손실)"]),
    "assets": (_BS, ["자산총계"]),
    "liabilities": (_BS, ["부채총계"]),
    "equity": (_BS, ["자본총계"]),
    "op_cash_flow": (_CF, ["영업활동현금흐름", "영업활동순현금흐름", "영업활동으로인한현금흐름",
                           "영업활동으로인한순현금흐름", "영업활동 현금흐름"]),
}


# ---------------------------------------------------------------------------
# 상장 종목 유니버스
# ---------------------------------------------------------------------------
def list_universe() -> pd.DataFrame:
    """KOSPI+KOSDAQ 시총 상위 목록. 컬럼: Code, Name, Market, Marcap, Close.

    ⚠ FinanceDataReader의 KRX 상장목록 소스가 404 장애를 일으켜(2026-07-23),
    네이버 증권 시총 랭킹 API로 대체함(datasources/naver_kr.py).
    """
    from . import naver_kr
    return naver_kr.list_universe(pool_size=100)


# 상장목록 캐시 (프로세스 1회만 조회) — 시가총액/상장주식수 조회에 재사용
_LISTING_CACHE: Optional[pd.DataFrame] = None


def _listing_lookup(ticker: str) -> tuple[Optional[float], Optional[float], Optional[str]]:
    """종목코드로 (시가총액, 상장주식수, 종목명) 조회. 없으면 (None, None, None)."""
    global _LISTING_CACHE
    try:
        if _LISTING_CACHE is None:
            _LISTING_CACHE = list_universe()
        df = _LISTING_CACHE
        if "Code" not in df.columns:
            return None, None, None
        hit = df[df["Code"].astype(str).str.zfill(6) == ticker.zfill(6)]
        if hit.empty:
            return None, None, None
        row = hit.iloc[0]
        marcap = float(row["Marcap"]) if "Marcap" in df.columns and pd.notna(row.get("Marcap")) else None
        shares = float(row["Stocks"]) if "Stocks" in df.columns and pd.notna(row.get("Stocks")) else None
        name = str(row["Name"]) if "Name" in df.columns and pd.notna(row.get("Name")) else None
        return marcap, shares, name
    except Exception:
        return None, None, None


# ---------------------------------------------------------------------------
# DART corp_code 매핑
# ---------------------------------------------------------------------------
def _load_corp_map() -> pd.DataFrame:
    """종목코드 -> DART 고유번호 매핑표. 캐시 우선."""
    if _CORP_MAP_CACHE.exists():
        return pd.read_parquet(_CORP_MAP_CACHE)

    if not settings.has_dart:
        return pd.DataFrame(columns=["corp_code", "corp_name", "stock_code"])

    url = f"{DART_BASE}/corpCode.xml"
    resp = requests.get(url, params={"crtfc_key": settings.dart_api_key}, timeout=30)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        xml_bytes = zf.read(zf.namelist()[0])
    df = pd.read_xml(io.BytesIO(xml_bytes), dtype=str)
    df = df[df["stock_code"].notna() & (df["stock_code"].str.strip() != "")]
    df["stock_code"] = df["stock_code"].str.zfill(6)
    df = df[["corp_code", "corp_name", "stock_code"]].reset_index(drop=True)
    try:
        df.to_parquet(_CORP_MAP_CACHE)
    except Exception:
        pass  # parquet 엔진 미설치 등 — 캐시 실패해도 동작엔 지장 없음
    return df


def _corp_code(ticker: str) -> Optional[str]:
    df = _load_corp_map()
    if df.empty:
        return None
    hit = df[df["stock_code"] == ticker.zfill(6)]
    return None if hit.empty else hit.iloc[0]["corp_code"]


# 표준산업분류(KSIC) 2자리 대분류 → 간략 업종명 (상장사 위주 커버)
_KSIC2 = {
    "01": "농업", "03": "어업", "05": "석탄광업", "06": "금속광업", "07": "비금속광물광업",
    "10": "식료품", "11": "음료", "12": "담배", "13": "섬유", "14": "의복",
    "15": "가죽·신발", "16": "목재", "17": "펄프·종이", "18": "인쇄", "19": "석유정제",
    "20": "화학", "21": "의약품", "22": "고무·플라스틱", "23": "비금속광물제품", "24": "1차 금속",
    "25": "금속가공", "26": "반도체·전자부품", "27": "의료·정밀·광학기기", "28": "전기장비", "29": "기계·장비",
    "30": "자동차·부품", "31": "기타 운송장비", "32": "가구", "33": "기타 제조", "35": "전기·가스",
    "36": "수도", "37": "하수·폐기물", "41": "종합 건설", "42": "전문공사", "45": "자동차 판매",
    "46": "도매", "47": "소매", "49": "육상 운송", "50": "수상 운송", "51": "항공 운송",
    "52": "창고·운송서비스", "55": "숙박", "56": "음식점", "58": "출판", "59": "영상·음악",
    "61": "통신", "62": "소프트웨어", "63": "정보서비스", "64": "금융", "65": "보험",
    "66": "금융·보험서비스", "68": "부동산", "70": "연구개발", "71": "전문 서비스", "72": "과학·기술 서비스",
    "73": "기타 전문·과학·기술", "86": "보건·의료", "90": "창작·예술",
}


def _company_sector(corp: Optional[str]) -> Optional[str]:
    """DART 회사개황(company.json)의 업종코드로 간략 업종명을 반환."""
    if not settings.has_dart or not corp:
        return None
    try:
        js = requests.get(
            f"{DART_BASE}/company.json",
            params={"crtfc_key": settings.dart_api_key, "corp_code": corp},
            timeout=15,
        ).json()
    except Exception:
        return None
    if js.get("status") != "000":
        return None
    code = (js.get("induty_code") or "").strip()
    return _KSIC2.get(code[:2]) if len(code) >= 2 else None


_KRX_DESC_CACHE: Optional[pd.DataFrame] = None


def _krx_sector(ticker: str) -> Optional[str]:
    """KRX-DESC 상장목록의 Sector 컬럼으로 업종 보완 (DART KSIC 매핑 실패 시 fallback)."""
    global _KRX_DESC_CACHE
    try:
        if _KRX_DESC_CACHE is None:
            import FinanceDataReader as fdr
            _KRX_DESC_CACHE = fdr.StockListing("KRX-DESC")
        df = _KRX_DESC_CACHE
        code_col = next((c for c in ("Code", "Symbol") if c in df.columns), None)
        if not code_col or "Sector" not in df.columns:
            return None
        hit = df[df[code_col].astype(str).str.zfill(6) == ticker.zfill(6)]
        if hit.empty:
            return None
        sec = hit.iloc[0]["Sector"]
        return str(sec).strip() if pd.notna(sec) and str(sec).strip() else None
    except Exception:
        return None


def _match_account(name: str, sj_div: str) -> Optional[str]:
    """계정명 + 재무제표구분(sj_div)이 모두 맞을 때만 표준 키를 반환."""
    name = (name or "").replace(" ", "")
    for key, (divs, aliases) in _ACCOUNT_SPEC.items():
        if sj_div in divs and any(a.replace(" ", "") == name for a in aliases):
            return key
    return None


def _fetch_financials(ticker: str, years: int = 3) -> dict[str, dict[str, float]]:
    """최근 years개 연도 사업보고서에서 핵심 계정을 추출.
    반환: { "revenue": {"2023": 값, ...}, ... }
    """
    out: dict[str, dict[str, float]] = {}
    if not settings.has_dart:
        return out
    corp = _corp_code(ticker)
    if not corp:
        return out

    this_year = datetime.now().year
    for year in range(this_year - 1, this_year - 1 - years, -1):
        params = {
            "crtfc_key": settings.dart_api_key,
            "corp_code": corp,
            "bsns_year": str(year),
            "reprt_code": "11011",  # 사업보고서(연간)
            "fs_div": "CFS",        # 연결재무제표 우선
        }
        try:
            r = requests.get(f"{DART_BASE}/fnlttSinglAcntAll.json", params=params, timeout=20)
            js = r.json()
        except Exception:
            continue
        if js.get("status") != "000":
            # 연결이 없으면 별도(OFS)로 재시도
            params["fs_div"] = "OFS"
            try:
                js = requests.get(f"{DART_BASE}/fnlttSinglAcntAll.json", params=params, timeout=20).json()
            except Exception:
                continue
            if js.get("status") != "000":
                continue
        for row in js.get("list", []):
            key = _match_account(row.get("account_nm", ""), row.get("sj_div", ""))
            if not key:
                continue
            # 해당 연도에 이미 값을 잡았으면 건너뜀(첫 매칭=재무상태표/손익계산서 값 유지)
            if str(year) in out.get(key, {}):
                continue
            amt = _to_number(row.get("thstrm_amount"))
            if amt is None:
                continue
            out.setdefault(key, {})[str(year)] = amt
    return out


def _to_number(s) -> Optional[float]:
    if s is None:
        return None
    s = str(s).replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 종목 1개 전체 수집
# ---------------------------------------------------------------------------
def fetch(candidate: Candidate) -> StockData:
    import FinanceDataReader as fdr

    data = StockData(ticker=candidate.ticker, name=candidate.name, market="KR", currency="KRW")

    # 1) 시세 (최근 약 1.5년)
    try:
        start = (datetime.now().year - 2, )  # 넉넉히
        hist = fdr.DataReader(candidate.ticker, f"{start[0]}-01-01")
        if hist is not None and not hist.empty:
            data.price_history = hist
            close_col = "Close" if "Close" in hist.columns else hist.columns[-1]
            vol = hist["Volume"] if "Volume" in hist.columns else None
            enrich_price_metrics(data, hist[close_col], vol)
            # 기술적 지표(일목·볼린저·이평·RSI·MACD) 계산
            from . import technical
            technical.compute(data, hist)
    except Exception as e:
        data.warnings.append(f"시세 수집 실패: {e}")

    # 2) 밸류에이션 지표·시총·종목명 (네이버 증권 — fdr 404 대체, 값이 정확)
    from . import naver_kr
    nm = naver_kr.metrics(candidate.ticker)
    if nm:
        data.market_cap = nm.get("market_cap")
        data.per, data.pbr = nm.get("per"), nm.get("pbr")
        data.eps, data.bps = nm.get("eps"), nm.get("bps")
        data.dividend_yield = nm.get("dividend_yield")
        if nm.get("name"):
            data.name = nm["name"]  # 공식 종목명으로 교체(관심종목 메모가 제목이 되지 않도록)
    else:
        data.warnings.append("네이버 밸류에이션 지표를 가져오지 못했습니다.")

    # 3) 재무제표 + 업종 (DART, 실패 시 KRX-DESC로 보완) — DART는 fdr과 별개라 정상
    corp = _corp_code(candidate.ticker)
    data.sector = _company_sector(corp) or (nm.get("sector") if nm else None) or _krx_sector(candidate.ticker)
    try:
        data.financials = _fetch_financials(candidate.ticker)
        if not data.financials:
            data.warnings.append("DART 재무 데이터를 가져오지 못했습니다(키 없음/미상장/조회실패).")
    except Exception as e:
        data.warnings.append(f"재무 수집 실패: {e}")

    # 5) 투자자별 매매동향 (네이버 API) + 연기금 상위 매매 포착 (judal.co.kr) — 실패해도 경고만
    from . import flows
    data.trading_flows = flows.fetch_kr_flows(candidate.ticker)
    if data.trading_flows is None:
        data.warnings.append("투자자별 매매동향을 가져오지 못했습니다.")
    pension = flows.fetch_kr_pension(candidate.ticker)
    if pension:
        if data.trading_flows is None:
            data.trading_flows = {}
        data.trading_flows["pension"] = pension

    # 6) 뉴스 + 증권사 리포트 (구글 뉴스 RSS) — 두 목록의 중복 기사는 뉴스 쪽에서 제거
    from . import news
    data.broker_reports = news.fetch_broker_reports(data.name, market="KR")
    seen = {n["title"] for n in data.broker_reports}
    data.news = [n for n in news.fetch_news(data.name, market="KR", limit=8) if n["title"] not in seen]
    return data


def _derive_valuation(data: StockData, shares: Optional[float]) -> None:
    """재무 데이터와 시가총액/상장주식수로 EPS·BPS·PER·PBR을 근사 계산.

    - PER = 시가총액 / 당기순이익,  PBR = 시가총액 / 자본총계
    - EPS = 당기순이익 / 상장주식수,  BPS = 자본총계 / 상장주식수
    상장주식수가 있어야 EPS/BPS를 산출하며, 없으면 PER/PBR만 계산합니다.
    """
    fin = data.financials
    latest_year = None
    if fin.get("net_income"):
        latest_year = max(fin["net_income"].keys())
    if not latest_year:
        return

    ni = fin.get("net_income", {}).get(latest_year)
    eq = fin.get("equity", {}).get(latest_year)

    if data.market_cap:
        # 적자(순이익≤0)면 PER은 무의미한 음수가 되므로 None 처리 (밸류에이션 오염 방지)
        data.per = safe_ratio(data.market_cap, ni) if (ni is not None and ni > 0) else None
        data.pbr = safe_ratio(data.market_cap, eq) if (eq is not None and eq > 0) else None

    if shares:
        data.eps = safe_ratio(ni, shares)
        data.bps = safe_ratio(eq, shares)
