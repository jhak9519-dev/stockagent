"""
네이버 증권 기반 한국 종목 데이터 (FinanceDataReader의 KRX 상장목록·시총 소스가
404 장애를 일으켜 대체·보강용으로 도입, 2026-07-23).

제공:
  · list_universe(): 시총 상위 종목 리스트(스크리닝 유니버스)  ← marketValue 랭킹 API
  · metrics(ticker): 개별 종목의 시총·PER·PBR·EPS·BPS·배당수익률·52주 고저·업종  ← integration API

시세(OHLCV)는 기존대로 FinanceDataReader.DataReader 를 씁니다(네이버/야후 소스라 정상 작동).
"""
from __future__ import annotations

import re
from typing import Optional

import pandas as pd
import requests

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_RANK_URL = "https://m.stock.naver.com/api/stocks/marketValue/{market}?page={page}&pageSize=100"
_INTEG_URL = "https://m.stock.naver.com/api/stock/{ticker}/integration"


def _num(s) -> Optional[float]:
    """'18.45배' / '103,521원' / '8.23%' → 숫자. 파싱 실패 시 None."""
    s = re.sub(r"[^\d.\-]", "", str(s or ""))
    try:
        return float(s) if s not in ("", "-", ".") else None
    except ValueError:
        return None


def _parse_marcap(s) -> Optional[float]:
    """'1,361조 2,615억' → 원 단위 float."""
    s = str(s or "")
    total = 0.0
    jo = re.search(r"([\d,]+)\s*조", s)
    eok = re.search(r"([\d,]+)\s*억", s)
    if jo:
        total += float(jo.group(1).replace(",", "")) * 1e12
    if eok:
        total += float(eok.group(1).replace(",", "")) * 1e8
    if not jo and not eok:  # 순수 숫자(억원 단위)면 그대로 억 처리
        n = _num(s)
        return n * 1e8 if n else None
    return total or None


def list_universe(pool_size: int = 100) -> pd.DataFrame:
    """코스피+코스닥 시총 상위 리스트. 컬럼: Code, Name, Market, Marcap(억원), Close."""
    rows = []
    for market in ("KOSPI", "KOSDAQ"):
        pages = (pool_size // 100) + 1
        for page in range(1, pages + 1):
            try:
                js = requests.get(_RANK_URL.format(market=market, page=page),
                                  timeout=10, headers=_UA).json()
            except Exception:
                break
            stocks = js.get("stocks") or []
            if not stocks:
                break
            for s in stocks:
                rows.append({
                    "Code": str(s.get("itemCode", "")).zfill(6),
                    "Name": s.get("stockName", ""),
                    "Market": market,
                    "Marcap": _num(s.get("marketValue")),  # 억원 단위
                    "Close": _num(s.get("closePrice")),
                })
    df = pd.DataFrame(rows)
    if "Marcap" in df.columns and len(df):
        df = df.sort_values("Marcap", ascending=False).reset_index(drop=True)
    return df


def metrics(ticker: str) -> Optional[dict]:
    """개별 종목의 밸류에이션 지표·업종·종목명. 실패 시 None."""
    try:
        js = requests.get(_INTEG_URL.format(ticker=ticker.zfill(6)),
                          timeout=10, headers=_UA).json()
    except Exception:
        return None
    info = {it.get("code"): it.get("value") for it in js.get("totalInfos", [])}
    sector = None
    ici = js.get("industryCompareInfo") or {}
    if isinstance(ici, dict):
        sector = ici.get("industryName") or ici.get("industryCodeName")
    return {
        "name": js.get("stockName"),
        "sector": sector,
        "market_cap": _parse_marcap(info.get("marketValue")),
        "per": _num(info.get("per")),
        "pbr": _num(info.get("pbr")),
        "eps": _num(info.get("eps")),
        "bps": _num(info.get("bps")),
        "dividend_yield": _num(info.get("dividendYieldRatio")),
        "high_52w": _num(info.get("highPriceOf52Weeks")),
        "low_52w": _num(info.get("lowPriceOf52Weeks")),
        "foreign_rate": info.get("foreignRate"),
    }
