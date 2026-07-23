# -*- coding: utf-8 -*-
"""
디자인(CSS·레이아웃) 변경을 AI 재분석 없이 빠르게 반영하는 도구.

기존에 생성된 리포트 HTML의 <style> 블록만 현재 템플릿의 최신 스타일로 교체하고
PDF를 다시 렌더한다. 분석 내용(수치·서술)은 그대로 두므로 Claude 호출이 없어 즉시 끝난다.

사용:
  .venv\\Scripts\\python.exe tools\\rerender_pdf.py "output\\2026-07-21\\....html"
  (인자를 생략하면 output 폴더에서 가장 최근 HTML을 자동 선택)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stockagent.report.pdf import html_to_pdf  # noqa: E402

_TPL = ROOT / "stockagent" / "report" / "templates" / "report.html.j2"
_STYLE_RE = re.compile(r"<style>.*?</style>", re.S)


def _latest_html() -> Path | None:
    cands = list((ROOT / "output").rglob("*.html"))
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else _latest_html()
    if not target or not target.exists():
        print("대상 HTML을 찾을 수 없습니다.")
        return

    new_style = _STYLE_RE.search(_TPL.read_text(encoding="utf-8"))
    if not new_style:
        print("템플릿에서 <style> 블록을 찾지 못했습니다.")
        return

    html = target.read_text(encoding="utf-8")
    if not _STYLE_RE.search(html):
        print("대상 HTML에 <style> 블록이 없습니다(구버전).")
        return
    html = _STYLE_RE.sub(lambda _: new_style.group(0), html, count=1)
    target.write_text(html, encoding="utf-8")

    pdf = html_to_pdf(html, target.with_suffix(".pdf"))
    print(f"재렌더 완료: {pdf}")


if __name__ == "__main__":
    main()
