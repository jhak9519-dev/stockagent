"""
투자자별 매매동향 수집.

- KR: 네이버 모바일 증권 API (무료·키 불필요) — 일별 개인/외국인/기관 순매수(주식 수)
      + 외국인 보유율. KRX(pykrx)는 2025년부터 로그인이 필요해져 무인 배치에 부적합.
      ※ 연기금 등 기관 세부 구분은 KRX 로그인 없이는 무료 소스가 없어 '기관 합계'로 제공.
- US: 투자자 유형별 매매 데이터가 공개되지 않아, yfinance의 기관/내부자 보유율과
      공매도 지표로 수급을 갈음합니다 (us.py에서 수집).
"""
from __future__ import annotations

import re
from typing import Optional

import requests

_NAVER_TREND = "https://m.stock.naver.com/api/stock/{ticker}/trend?pageSize={n}"
_JUDAL_URL = "https://www.judal.co.kr/?view=stockList&type={t}"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def _num(s) -> float:
    return float(str(s).replace(",", "").replace("+", "").replace("%", "") or 0)


def fetch_kr_pension(ticker: str) -> Optional[dict]:
    """연기금 순매수/순매도 '상위 목록'(judal.co.kr, 매일 갱신)에서 해당 종목 포착.

    이 페이지는 전 종목이 아니라 연기금 매매 상위 ~100종목 목록이므로,
    목록에 없으면 '대규모 연기금 매매 없음'으로 해석한다.
    반환: {"date": 기준일, "direction": "순매수"|"순매도"|None, "amount_100m": 억원|None}
    실패(사이트 변경·접속 불가) 시 None — 배치를 막지 않는다.
    """
    try:
        out: dict = {"date": None, "direction": None, "amount_100m": None}
        code = ticker.zfill(6)
        for t, label in (("fundBuy", "순매수"), ("fundSell", "순매도")):
            html = requests.get(_JUDAL_URL.format(t=t), timeout=15, headers=_UA).text
            if out["date"] is None:
                m = re.search(r"기준일\s*[:：]\s*([\d-]+)", html)
                out["date"] = m.group(1) if m else None
            for block in html.split("<tr")[1:]:
                c = re.search(r"code=(\d{6})", block)
                if not c or c.group(1) != code:
                    continue
                out["direction"] = label
                # 매매금액 = 첫 번째 <td> 셀 (행 머리글 <th>의 툴팁 속 숫자를 피하기 위해 td만 탐색)
                tds = re.findall(r"<td[^>]*>(.*?)</td>", block, re.S)
                if tds:
                    a = re.search(r"([\d,]+)\s*억원", re.sub(r"<[^>]+>", " ", tds[0]))
                    out["amount_100m"] = float(a.group(1).replace(",", "")) if a else None
                return out
        return out
    except Exception:
        return None


def fetch_kr_flows(ticker: str, days: int = 20) -> Optional[dict]:
    """최근 days 거래일의 투자자별 순매수 합계. 실패 시 None (배치를 막지 않음).

    반환 예:
    {"period": "최근 20거래일", "unit": "억원(추정)",
     "individual": -1234.5, "foreign": +987.6, "institution": +246.9,
     "foreign_hold_ratio": "40.06%",
     "recent5": [{"date": "07-15", "individual": -71849, ...}, ...]}  # 주식 수
    """
    try:
        url = _NAVER_TREND.format(ticker=ticker, n=days)
        rows = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"}).json()
        if not isinstance(rows, list) or not rows:
            return None

        keys = {"individual": "individualPureBuyQuant",
                "foreign": "foreignerPureBuyQuant",
                "institution": "organPureBuyQuant"}
        value = {k: 0.0 for k in keys}          # 순매수 금액 근사(주식수 × 당일 종가)
        for r in rows:
            px = _num(r.get("closePrice"))
            for k, col in keys.items():
                value[k] += _num(r.get(col)) * px

        def _amt(r, col):  # 순매수 주식수 × 당일 종가 → 억원
            return round(_num(r.get(col)) * _num(r.get("closePrice")) / 1e8, 1)

        def _chg(r):  # 전일 대비 등락률(%) = 전일비 / (종가 - 전일비)
            close = _num(r.get("closePrice"))
            diff = _num(r.get("compareToPreviousClosePrice"))
            prev = close - diff
            return round(diff / prev * 100, 2) if prev else None

        daily = [{
            "date": f"{str(r.get('bizdate'))[4:6]}/{str(r.get('bizdate'))[6:8]}",
            "close": _num(r.get("closePrice")),
            "change": _chg(r),
            "individual": _amt(r, keys["individual"]),
            "foreign": _amt(r, keys["foreign"]),
            "institution": _amt(r, keys["institution"]),
        } for r in rows[:7]]

        return {
            "period": f"최근 {len(rows)}거래일",
            "unit": "억원(주식수×종가 추정)",
            "individual": round(value["individual"] / 1e8, 1),
            "foreign": round(value["foreign"] / 1e8, 1),
            "institution": round(value["institution"] / 1e8, 1),
            "foreign_hold_ratio": rows[0].get("foreignerHoldRatio"),
            "daily": daily,
        }
    except Exception:
        return None
