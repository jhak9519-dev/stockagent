# -*- coding: utf-8 -*-
"""
과거 리포트를 '현재 디자인'으로 재생성하는 마이그레이션 도구 (AI 재분석 없음).

rerender_pdf.py 는 <style> 블록만 갈아끼웠지만, 표 개선(2026-07-27)처럼
'마크업 구조'까지 바뀐 경우엔 옛 표를 새 구조로 업그레이드해야 한다.
이 도구는 분석 내용(수치·서술)은 그대로 두고 아래만 바꾼다:

  1) <style> 블록을 현재 템플릿 최신본으로 교체 (항목명 칸 폭 자동조정 등)
  2) 저항선/지지선의 여러 레벨을 ` · ` 나열 → 각 줄(<br>)로 분리
  3) 외국인 순매수의 보유율을 아랫줄로 분리
  4) 일자별 수급표(KR 6칸 / US 4칸)를 colgroup·정렬 클래스가 있는 새 표로 재작성
  5) 시나리오 표를 핵심 조건 55% 배분(colgroup)으로 재작성

그런 다음 output HTML을 다시 쓰고 PDF를 재렌더하며, 대응하는 웹 발행본은
실제 발행 파이프라인(_mobilify)에 그대로 통과시켜 신규 리포트와 동일한 다크
테마로 재생성한다.

사용:
  .venv\\Scripts\\python.exe tools\\rerender_design.py           # output 전체 + 웹 반영
  .venv\\Scripts\\python.exe tools\\rerender_design.py --no-web  # PDF/HTML만, 웹 미반영
  .venv\\Scripts\\python.exe tools\\rerender_design.py "<특정.html>"
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

os.environ.setdefault("STOCKAGENT_NO_PUBLISH", "1")  # 자동 발행 경로 비활성(직접 mobilify만 사용)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stockagent.report.pdf import html_to_pdf          # noqa: E402
from stockagent.report.publish import _mobilify, WEB_DIR  # noqa: E402

_TPL = ROOT / "stockagent" / "report" / "templates" / "report.html.j2"
_STYLE_RE = re.compile(r"<style>.*?</style>", re.S)

# --- 표 재작성용 상수(템플릿과 동일하게 유지) ---
_CG_DAILY_KR = ('<colgroup><col style="width:17%"><col style="width:17%">'
                '<col style="width:14%"><col style="width:17.3%">'
                '<col style="width:17.3%"><col style="width:17.4%"></colgroup>')
_CG_DAILY_US = ('<colgroup><col style="width:26%"><col style="width:24%">'
                '<col style="width:22%"><col style="width:28%"></colgroup>')
_CG_SCEN = ('<colgroup><col style="width:15%"><col style="width:19%">'
            '<col style="width:11%"><col style="width:55%"></colgroup>')


def _cells(row_html: str):
    """<tr> 한 줄에서 (속성, 값) 튜플 목록 추출."""
    return re.findall(r"<td([^>]*)>(.*?)</td>", row_html, flags=re.S)


def _colorcls(attrs: str) -> str:
    """셀 속성에서 buy/sell 색 클래스만 골라 ' buy' / ' sell' / '' 반환."""
    m = re.search(r'class="(buy|sell)"', attrs)
    return f" {m.group(1)}" if m else ""


def _upgrade_levels(html: str) -> str:
    def repl(m):
        return m.group(1) + m.group(2).replace(" · ", "<br>") + m.group(3)
    return re.sub(
        r'(<td class="k">(?:저항선 \(위\)|지지선 \(아래\))</td><td>)(.*?)(</td>)',
        repl, html, flags=re.S)


def _upgrade_foreign(html: str) -> str:
    return re.sub(
        r'(<td class="k">외국인 순매수</td><td[^>]*>)(.*?)\s+\(보유율\s*(.*?)\)(</td>)',
        r'\1\2<br><span style="color:#8b95a7;">보유율 \3</span>\4',
        html, flags=re.S)


def _upgrade_daily(html: str) -> str:
    m = re.search(
        r'(?s)<table class="metrics" style="margin-top:6px;">\s*'
        r'<tr><td class="k">일자</td>.*?</table>', html)
    if not m:
        return html
    block = m.group(0)
    rows = re.findall(r"<tr>.*?</tr>", block, flags=re.S)
    if not rows:
        return html
    is_kr = "개인" in rows[0]           # 헤더로 KR/US 판별
    if is_kr:
        header = ('<tr><td class="k dt">일자</td><td class="k num">종가</td>'
                  '<td class="k num">등락률</td><td class="k num">개인</td>'
                  '<td class="k num">외국인</td><td class="k num">기관</td></tr>')
        cg = _CG_DAILY_KR
    else:
        header = ('<tr><td class="k dt">일자</td><td class="k num">종가</td>'
                  '<td class="k num">등락률</td><td class="k num">거래량</td></tr>')
        cg = _CG_DAILY_US
    out = [f'<table class="metrics fixed daily" style="margin-top:6px;">', cg, header]
    for r in rows[1:]:
        c = _cells(r)
        if is_kr and len(c) == 6:
            out.append(
                f'<tr><td class="dt">{c[0][1]}</td>'
                f'<td class="num">{c[1][1]}</td>'
                f'<td class="num{_colorcls(c[2][0])}">{c[2][1]}</td>'
                f'<td class="num{_colorcls(c[3][0])}">{c[3][1]}</td>'
                f'<td class="num{_colorcls(c[4][0])}">{c[4][1]}</td>'
                f'<td class="num{_colorcls(c[5][0])}">{c[5][1]}</td></tr>')
        elif (not is_kr) and len(c) == 4:
            out.append(
                f'<tr><td class="dt">{c[0][1]}</td>'
                f'<td class="num">{c[1][1]}</td>'
                f'<td class="num{_colorcls(c[2][0])}">{c[2][1]}</td>'
                f'<td class="num">{c[3][1]}</td></tr>')
        else:
            out.append(r)  # 예상 밖 형태는 원본 유지(안전)
    out.append("</table>")
    return html.replace(block, "\n  ".join(out))


def _upgrade_scenario(html: str) -> str:
    m = re.search(
        r'(?s)<table class="metrics">\s*'
        r'<tr><td class="k">시나리오</td>.*?</table>', html)
    if not m:
        return html
    block = m.group(0)
    rows = re.findall(r"<tr>.*?</tr>", block, flags=re.S)
    if not rows:
        return html
    header = ('<tr><td class="k dt">시나리오</td><td class="k num">12개월 목표가</td>'
              '<td class="k num">확률</td><td class="k">핵심 조건</td></tr>')
    out = ['<table class="metrics fixed scen">', _CG_SCEN, header]
    for r in rows[1:]:
        c = _cells(r)
        if len(c) == 4:
            out.append(
                f'<tr><td class="dt">{c[0][1]}</td>'
                f'<td class="num">{c[1][1]}</td>'
                f'<td class="num">{c[2][1]}</td>'
                f'<td class="cond">{c[3][1]}</td></tr>')
        else:
            out.append(r)
    out.append("</table>")
    return html.replace(block, "\n  ".join(out))


def migrate(html: str, new_style: str) -> str:
    """리포트 HTML 1건을 현재 디자인으로 변환(첫 <style> 교체 + 표 업그레이드)."""
    html = _STYLE_RE.sub(lambda _: new_style, html, count=1)
    html = _upgrade_levels(html)
    html = _upgrade_foreign(html)
    html = _upgrade_daily(html)
    html = _upgrade_scenario(html)
    return html


def _web_slug(out_html: Path) -> str:
    """output 파일명 -> 웹 발행 슬러그(<market>_<ticker>.html)."""
    parts = out_html.stem.split("_")   # [날짜, 시장, ...이름..., 티커]
    return f"{parts[1]}_{parts[-1]}.html"


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    do_web = "--no-web" not in sys.argv

    sm = _STYLE_RE.search(_TPL.read_text(encoding="utf-8"))
    if not sm:
        print("템플릿에서 <style>를 찾지 못했습니다.")
        return
    new_style = sm.group(0)

    if args:
        targets = [Path(args[0])]
    else:
        targets = sorted(p for p in (ROOT / "output").rglob("*.html")
                         if "테스트전자" not in p.name)
    if not targets:
        print("대상 HTML이 없습니다.")
        return

    web_changed = False
    for out_html in targets:
        html = out_html.read_text(encoding="utf-8")
        migrated = migrate(html, new_style)
        out_html.write_text(migrated, encoding="utf-8")
        try:
            html_to_pdf(migrated, out_html.with_suffix(".pdf"))
            pdf_ok = "PDF✓"
        except Exception as e:
            pdf_ok = f"PDF✗({e})"

        web_ok = "웹-"
        if do_web:
            slug = _web_slug(out_html)
            wp = WEB_DIR / "reports" / out_html.parent.name / slug
            if wp.exists():
                wp.write_text(_mobilify(migrated), encoding="utf-8")
                web_ok = f"웹✓({slug})"
                web_changed = True
            else:
                web_ok = f"웹없음({slug})"
        print(f"  · {out_html.parent.name}/{out_html.name}  {pdf_ok}  {web_ok}")

    print(f"\n총 {len(targets)}건 재생성 완료.")

    if do_web and web_changed:
        import subprocess
        def g(*a):
            return subprocess.run(["git", *a], cwd=str(WEB_DIR),
                                  capture_output=True, text=True, encoding="utf-8")
        g("add", "-A")
        c = g("commit", "-m", "과거 리포트 표 디자인 일괄 재적용(칸 폭·줄바꿈·colgroup)")
        if c.returncode == 0:
            p = g("push")
            print("웹 저장소 push:", "성공" if p.returncode == 0
                  else f"실패 — {(p.stderr or p.stdout)[:200]}")
        else:
            print("웹 커밋 없음(변경 없음이거나 실패):", (c.stdout or c.stderr)[:160])


if __name__ == "__main__":
    main()
