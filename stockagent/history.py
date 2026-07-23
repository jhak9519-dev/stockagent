"""
자동 발굴(스크리닝) 선정 이력 관리.

매 배치에서 '최유망'으로 뽑힌 종목의 선정 날짜를 cache/pick_history.json 에 누적한다.
리포트에 '누적 N회 선정 · M일 연속'을 표시해, 같은 종목이 반복 선정되는지 한눈에 보이게 한다.

저장 형식: { "KR_000660": ["2026-07-15", "2026-07-17", "2026-07-20"], ... }
"""
from __future__ import annotations

import json
from datetime import date, datetime

from .config import settings

_PATH = settings.cache_dir / "pick_history.json"
# 이 간격(달력일) 이내면 '연속' 선정으로 간주 — 주말·공휴일 건너뜀을 허용
_STREAK_GAP = 4


def _load() -> dict[str, list[str]]:
    if not _PATH.exists():
        return {}
    try:
        return json.loads(_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _key(market: str, ticker: str) -> str:
    return f"{market}_{ticker}"


def record(candidates, when: date | None = None) -> None:
    """선정된 종목들의 날짜를 이력에 추가(같은 날 중복은 무시)."""
    if not candidates:
        return
    day = str(when or date.today())
    data = _load()
    for c in candidates:
        k = _key(c.market, c.ticker)
        dates = data.setdefault(k, [])
        if day not in dates:
            dates.append(day)
            dates.sort()
    try:
        _PATH.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    except Exception:
        pass  # 이력 저장 실패가 배치를 막지 않음


_REPORT_PATH = settings.cache_dir / "report_history.json"


def _load_reports() -> dict:
    if not _REPORT_PATH.exists():
        return {}
    try:
        return json.loads(_REPORT_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def record_report(market: str, ticker: str, target, opinion: str,
                  multiple=None, when: date | None = None) -> None:
    """리포트 발행 결과(목표가·의견·배수)를 날짜별로 저장 (전일 대비 변경 비교용)."""
    day = str(when or date.today())
    data = _load_reports()
    data.setdefault(_key(market, ticker), {})[day] = {
        "target": target, "opinion": opinion, "multiple": multiple,
    }
    try:
        _REPORT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    except Exception:
        pass


def prev_report(market: str, ticker: str, before: date | None = None) -> "dict | None":
    """지정일(기본 오늘) '이전'의 가장 최근 리포트 결과. 없으면 None."""
    recs = _load_reports().get(_key(market, ticker), {})
    cut = str(before or date.today())
    past = sorted(d for d in recs if d < cut)
    return dict(recs[past[-1]], date=past[-1]) if past else None


def stats(market: str, ticker: str) -> dict:
    """해당 종목의 {count: 누적 선정 횟수, streak: 최근 연속 선정, first: 최초 선정일}."""
    dates = _load().get(_key(market, ticker), [])
    if not dates:
        return {"count": 0, "streak": 0, "first": None}
    try:
        ds = sorted(datetime.strptime(x, "%Y-%m-%d").date() for x in dates)
    except Exception:
        return {"count": len(dates), "streak": 0, "first": dates[0]}
    streak = 1
    for i in range(len(ds) - 1, 0, -1):
        if (ds[i] - ds[i - 1]).days <= _STREAK_GAP:
            streak += 1
        else:
            break
    return {"count": len(ds), "streak": streak, "first": str(ds[0])}
