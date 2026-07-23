"""
HTML -> PDF 렌더 (Playwright / 헤드리스 Chromium).

Chromium의 인쇄 엔진을 사용하므로 한글 폰트와 CSS 레이아웃이 그대로 반영됩니다.
Playwright/Chromium이 준비되지 않은 경우, HTML 파일로 저장하고 안내합니다.
"""
from __future__ import annotations

from pathlib import Path


def html_to_pdf(html: str, out_path: Path) -> Path:
    """HTML 문자열을 PDF로 저장. 성공 시 PDF 경로, 실패 시 HTML 경로 반환."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return _save_html_fallback(html, out_path, reason="playwright 미설치")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_content(html, wait_until="networkidle")
            page.pdf(
                path=str(out_path),
                format="A4",
                print_background=True,
                margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
            )
            browser.close()
        return out_path
    except Exception as e:
        return _save_html_fallback(html, out_path, reason=f"Chromium 실행 실패({e})")


def _save_html_fallback(html: str, out_path: Path, reason: str) -> Path:
    html_path = out_path.with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")
    print(f"    ⚠ PDF 생성 건너뜀({reason}). 대신 HTML로 저장했습니다: {html_path.name}")
    print("      → PDF를 원하시면:  python -m playwright install chromium")
    return html_path
