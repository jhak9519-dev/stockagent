"""
뉴스 수집 (구글 뉴스 RSS 기반, 무료·키 불필요, 한국/미국 공용).

종목명으로 최근 뉴스 제목을 가져와 시황·투자요약 분석에 활용합니다.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests

# 이보다 오래된 기사는 제외 (구글 RSS가 간혹 옛 기사를 섞어 보냄)
_MAX_AGE_DAYS = 30


def _short_date(rfc822: str) -> str:
    """'Mon, 14 Jul 2026 09:00:00 GMT' → '2026-07-14'."""
    try:
        return parsedate_to_datetime(rfc822).strftime("%Y-%m-%d")
    except Exception:
        return ""


def fetch_broker_reports(name: str, market: str = "KR", limit: int = 5) -> list[dict[str, str]]:
    """증권사 리포트·목표주가 관련 뉴스 검색.

    '종목명 목표주가'(KR) / 'name price target analyst'(US) 로 검색하면
    증권사 리포트 발간 뉴스(목표주가 상향/하향 등)가 주로 잡힌다.
    """
    q = f"{name} 목표주가" if market == "KR" else f"{name} price target analyst"
    return fetch_news(q, market=market, limit=limit)


def fetch_news(query: str, market: str = "KR", limit: int = 5) -> list[dict[str, str]]:
    """종목명으로 구글 뉴스 검색 → [{title, publisher, date}, ...] 반환."""
    if not query:
        return []
    hl, gl, ceid = ("ko", "KR", "KR:ko") if market == "KR" else ("en", "US", "US:en")
    url = f"https://news.google.com/rss/search?q={quote(query)}&hl={hl}&gl={gl}&ceid={ceid}"
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(r.content)
    except Exception:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=_MAX_AGE_DAYS)
    out: list[dict[str, str]] = []
    seen_titles: set[str] = set()
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        source = (it.findtext("source") or "").strip()
        # 제목 끝의 " - 언론사" 꼬리 제거
        if source and title.endswith(f" - {source}"):
            title = title[: -(len(source) + 3)].strip()
        # 깨진 플레이스홀더 제목(예: META_TITLE_QUOTE) 제거
        if not title or (" " not in title and title.replace("_", "").isupper()):
            continue
        # 같은 제목 중복 제거
        if title in seen_titles:
            continue
        # 30일 초과 옛 기사 제외 (날짜 파싱 실패 시에는 유지)
        pub = it.findtext("pubDate") or ""
        try:
            dt = parsedate_to_datetime(pub)
            if dt and dt < cutoff:
                continue
        except Exception:
            pass
        seen_titles.add(title)
        out.append({"title": title, "publisher": source, "date": _short_date(pub)})
        if len(out) >= limit:
            break
    return out
