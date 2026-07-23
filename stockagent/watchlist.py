"""
관심종목(watchlist) 로더.

프로젝트 루트의 watchlist.txt를 읽어 Candidate 목록으로 변환합니다.
형식(한 줄에 하나):  <시장> <종목코드> [메모...]
  예)  KR 005930 삼성전자
       US AAPL 애플
'#' 주석과 빈 줄은 무시합니다.

파일은 국장(KR)·미장(US) 두 섹션으로 구분해 관리하며, 자동 발굴로 추가되는 종목도
해당 시장 섹션에 정리되어 들어갑니다(add()가 시장별로 재작성).
"""
from __future__ import annotations

from pathlib import Path

from .config import settings
from .models import Candidate

WATCHLIST_PATH = settings.root / "watchlist.txt"

_HEADER = """# ============================================================
#  관심종목(watchlist) 목록  ·  국장(KR) / 미장(US) 구분
# ------------------------------------------------------------
#  · 한 줄에 한 종목씩.  형식:   시장 종목코드 메모(선택)
#  · 시장 = KR(한국) 또는 US(미국)  ·  한국=6자리 숫자, 미국=티커
#  · '#' 주석·빈 줄은 무시됩니다.  각 시장 섹션 안에 추가하세요.
#  · 자동 발굴 종목은 해당 시장 섹션에 자동 정리됩니다.
#  편집 후 실행:  python run.py --watchlist   (→ output/watchlist/)
# ============================================================"""

_SECTION = {"KR": "한국 (KR)", "US": "미국 (US)"}


def load(path: Path = WATCHLIST_PATH, log=print) -> list[Candidate]:
    if not path.exists():
        log(f"  ⚠ 관심종목 파일이 없습니다: {path}")
        return []

    candidates: list[Candidate] = []
    seen: set[tuple[str, str]] = set()
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        market = parts[0].upper()
        if market not in ("KR", "US") or len(parts) < 2:
            log(f"  ⚠ {lineno}번째 줄 형식 오류(무시): {line!r}  →  예: KR 005930 삼성전자")
            continue
        ticker = parts[1].zfill(6) if market == "KR" else parts[1].upper()
        note = " ".join(parts[2:]) if len(parts) > 2 else ticker
        key = (market, ticker)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(Candidate(ticker=ticker, name=note, market=market,
                                    score=0, reasons=["관심종목"]))
    return candidates


def _write_grouped(entries: list[Candidate], path: Path = WATCHLIST_PATH) -> None:
    """관심종목을 국장/미장 섹션으로 구분해 파일 전체를 재작성."""
    lines = [_HEADER, ""]
    for market in ("KR", "US"):
        group = [c for c in entries if c.market == market]
        lines.append(f"# ===================== {_SECTION[market]} =====================")
        for c in group:
            note = "" if (not c.name or c.name == c.ticker) else f" {c.name}"
            lines.append(f"{market} {c.ticker}{note}")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def regroup(path: Path = WATCHLIST_PATH, log=print) -> int:
    """기존 watchlist.txt를 국장/미장 섹션으로 재정렬(기존 종목·메모 유지). 반환: 종목 수."""
    entries = load(path, log=lambda *a: None)
    _write_grouped(entries, path)
    kr = sum(1 for c in entries if c.market == "KR")
    us = sum(1 for c in entries if c.market == "US")
    log(f"  [관심종목] 시장별 재정렬 완료: 한국 {kr}종목 · 미국 {us}종목")
    return len(entries)


def add(candidates: list[Candidate], path: Path = WATCHLIST_PATH, log=print) -> int:
    """발굴된 종목을 해당 시장 섹션에 누적 추가(기존 유지·중복 제외). 반환: 새로 추가된 수."""
    if not candidates:
        return 0
    entries = load(path, log=lambda *a: None)
    keys = {(c.market, c.ticker) for c in entries}
    fresh = []
    for c in candidates:
        key = (c.market, c.ticker)
        if key in keys:
            continue
        keys.add(key)
        fresh.append(c)
        entries.append(c)
    if not fresh:
        log("  [관심종목] 새로 추가할 종목 없음(이미 목록에 있음).")
        return 0
    _write_grouped(entries, path)
    log(f"  [관심종목] {len(fresh)}개 종목을 watchlist.txt 에 자동 추가(시장별 정리): "
        + ", ".join(f"{c.name}({c.ticker})" for c in fresh))
    return len(fresh)
