"""
리포트 HTML을 GitHub Pages 로 발행 (선택 기능).

동작: web/ 폴더(프로젝트와 분리된 별도 git 저장소)에 리포트 HTML을 복사하고
manifest.json·index.html 을 갱신한 뒤 커밋·푸시합니다. 몇 분 내에
https://jhak9519-dev.github.io/stock-reports/ 에서 열람 가능해집니다.

안전 장치:
- 발행 대상은 web/ 안의 생성물(HTML)뿐 — 프로젝트 본체(.env, 코드)는 절대 발행되지 않음
- web/.git 이 없으면 조용히 건너뜀 (기능 끄려면 web 폴더만 지우면 됨)
- 발행 실패는 경고만 남기고 배치를 막지 않음
⚠ 공개 저장소이므로 리포트 내용은 URL을 아는 누구나 볼 수 있습니다(사용자 승인, 2026-07-16).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from ..config import ROOT

WEB_DIR = ROOT / "web"
BASE_URL = "https://jhak9519-dev.github.io/stock-reports"


def enabled() -> bool:
    # 테스트(스모크) 실행 중에는 실서비스 웹에 발행하지 않는다
    if os.getenv("STOCKAGENT_NO_PUBLISH"):
        return False
    return (WEB_DIR / ".git").exists()


def current_price(market: str, ticker: str) -> "float | None":
    """종목의 현재가(최근 종가) 조회. 실패 시 None."""
    try:
        if market == "KR":
            import FinanceDataReader as fdr
            from datetime import date, timedelta
            df = fdr.DataReader(ticker, str(date.today() - timedelta(days=10)))
            return float(df["Close"].dropna().iloc[-1]) if df is not None and not df.empty else None
        else:
            import yfinance as yf
            fi = yf.Ticker(ticker).fast_info
            px = fi.get("lastPrice") or fi.get("last_price")
            return float(px) if px else None
    except Exception:
        return None


# 웹(다크 테마) 전용 스타일 — 문서 '끝'에 삽입해 원본(PDF용) 스타일을 확실히 덮어쓴다.
# PDF 렌더 경로와는 무관 (발행본에만 적용). 색상: 눈이 편한 저채도 다크 팔레트.
_WEB_STYLE = """<style>
:root { color-scheme: dark; }
html { background: #0f1319; }
body {
  background: #0f1319 !important; color: #cfd6e1 !important;
  max-width: 820px !important; margin: 0 auto !important;
  padding: 40px 28px 64px !important; font-size: 14.5px !important; line-height: 1.8 !important;
}
/* 주제별 카드 — 각 블록을 넉넉한 여백의 카드로 */
.block {
  background: #141b24 !important; border: 1px solid #232d3a !important; border-radius: 14px !important;
  padding: 20px 24px !important; margin: 0 0 20px !important;
}
.block > h2.section:first-child { margin-top: 4px !important; }
.header { border-bottom-color: #3b6ea5 !important; padding-bottom: 14px !important; margin-bottom: 22px !important; }
.eyebrow { color: #7fb2e5 !important; }
.title { color: #e8edf5 !important; }
.subtitle, .meta-row { color: #8b95a7 !important; }
.meta-row b { color: #7fb2e5 !important; }
h2.section { color: #7fb2e5 !important; border-left-color: #3b6ea5 !important; }
.opinion-box { background: #171d26; border-color: #2a3240 !important; border-radius: 10px; flex-wrap: wrap; }
.opinion-cell { border-right-color: #242c38 !important; min-width: 110px; }
.opinion-cell .k { color: #8b95a7 !important; }
.buy { color: #ff8f86 !important; } .hold { color: #e6c07b !important; } .sell { color: #7fb2e5 !important; }
.hold-ret.buy { color: #ff8f86 !important; background: #2a1d1d !important; }
.hold-ret.sell { color: #7fb2e5 !important; background: #16233a !important; }
.summary { background: #16202e !important; border: 1px solid #24344e; border-radius: 8px; padding: 12px 14px !important; }
.summary b, .body-text b { color: #ff9d94 !important; }
.bullets { list-style: none !important; padding-left: 0 !important; display: flex; flex-wrap: wrap; gap: 7px; margin: 8px 0 !important; }
.bullets li { background: #1b2431 !important; border: 1px solid #2a3849; border-radius: 8px; padding: 5px 11px !important; margin: 0 !important; font-size: 13px; color: #c5d0de; }
.risks .bullets { display: block; }
.risks .bullets li { display: list-item; background: none !important; border: none; padding: 2px 0 2px 4px !important; }
.body-text { line-height: 1.85 !important; }
table.metrics td { border-color: #2a3240 !important; padding: 7px 10px !important; }
table.metrics td.k { background: #1a222e !important; color: #8b95a7 !important; }
.risks { background: #241a1a !important; border-color: #43302f !important; }
img.chart { background: #141b24; border-radius: 8px; border-color: #2a3240 !important; padding: 0; }
.disclaimer { color: #6b7480 !important; border-top-color: #2a3240 !important; }
a { color: #7fb2e5; }
@media (max-width: 520px) {
  body { font-size: 15.5px !important; padding: 16px 13px 36px !important; }
  .title { font-size: 22px !important; }
  .opinion-cell { flex: 1 1 45%; }
}
</style>"""

# 원본 HTML의 '인라인 스타일' 색상은 CSS로 못 덮으므로 다크 팔레트로 직접 치환
_INLINE_COLOR_MAP = [
    ("color:#c0504d;background:#fff6f5;border:1px solid #f0d8d5",
     "color:#ff9d94;background:#241a1a;border:1px solid #43302f"),  # 과열 배지
    ("color:#444", "color:#b9c2d0"),
    ("color:#888", "color:#8b95a7"),
    ("color:#999", "color:#7d8698"),
    ("color:#1f4e79", "color:#7fb2e5"),
]


def _mobilify(html: str) -> str:
    """PDF용 리포트 HTML을 웹·모바일 열람용(다크 테마)으로 변환.

    - viewport 메타: 없으면 폰이 980px 가상 화면으로 렌더링해 글자가 작아짐
    - 다크 스타일을 문서 끝에 삽입: 원본 <style>보다 뒤라서 항상 이김
      (PC에서 왼쪽으로 치우쳐 잘려 보이던 문제도 margin:auto 강제로 해결)
    - 인라인 색상 치환: style="" 속성은 CSS로 못 덮어 문자열 치환으로 처리
    """
    for old, new in _INLINE_COLOR_MAP:
        html = html.replace(old, new)
    head = ('<!doctype html><html lang="ko"><head><meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '</head><body>\n')
    return head + html + "\n" + _WEB_STYLE + "\n</body></html>"


def _git(args: list[str], ok_codes=(0,)) -> None:
    r = subprocess.run(["git"] + args, cwd=str(WEB_DIR), capture_output=True,
                       text=True, encoding="utf-8", timeout=120)
    if r.returncode not in ok_codes:
        raise RuntimeError(f"git {' '.join(args)} 실패: {(r.stderr or r.stdout)[:200]}")


def publish(report, html_path, log=print):
    """리포트 1건을 발행. 성공 시 웹 URL 반환(+report.web_url 설정), 실패 시 None."""
    if not enabled():
        return None
    try:
        d = report.data
        day = str(report.generated_at)
        slug = f"{d.market}_{re.sub(r'[^0-9A-Za-z._-]', '', str(d.ticker))}.html"
        rel = f"reports/{day}/{slug}"
        dest = WEB_DIR / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(_mobilify(Path(html_path).read_text(encoding="utf-8")), encoding="utf-8")

        # manifest(발행 목록) 갱신 — 같은 경로 재발행 시 교체
        mf_path = WEB_DIR / "manifest.json"
        manifest = json.loads(mf_path.read_text(encoding="utf-8-sig")) if mf_path.exists() else []
        v = report.valuation
        # 발행 당일 제시한 매수가(구간 중심값) — 이후 수익률 계산 기준
        buy = None
        if v:
            if getattr(v, "buy_low", None) and getattr(v, "buy_high", None):
                buy = round((v.buy_low + v.buy_high) / 2, 2)
            elif getattr(v, "buy_price", None):
                buy = v.buy_price
        manifest = [m for m in manifest if m.get("path") != rel]
        manifest.append({
            "date": day, "market": d.market, "ticker": str(d.ticker), "name": d.name,
            "opinion": getattr(v, "opinion", "-") if v else "-",
            "target": getattr(v, "target_price", None) if v else None,
            "upside": getattr(v, "upside_pct", None) if v else None,
            "buy": buy,
            "path": rel,
        })
        mf_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

        _build_index(manifest)

        _git(["add", "-A"])
        _git(["commit", "-m", f"리포트 발행: {day} {d.name}({d.ticker})"], ok_codes=(0, 1))
        _git(["push", "origin", "main"])

        url = f"{BASE_URL}/{rel}"
        try:
            report.web_url = url  # 카톡 버튼 링크 등에서 사용
        except Exception:
            pass
        log(f"  🌐 웹 발행 완료: {url}")
        return url
    except Exception as e:
        log(f"  ⚠ 웹 발행 실패(리포트는 정상 저장됨): {e}")
        return None


def _return_badge(m: dict, price_cache: dict) -> str:
    """발행 당일 매수가 대비 현재 수익률 뱃지 HTML (수익=빨강, 손실=파랑). 없으면 빈 문자열."""
    buy = m.get("buy")
    if not buy:
        return ""
    key = (m.get("market"), m.get("ticker"))
    if key not in price_cache:
        price_cache[key] = current_price(m.get("market"), m.get("ticker"))
    cur = price_cache[key]
    if not cur:
        return ""
    ret = (cur / buy - 1) * 100
    cls = "gain" if ret >= 0 else "loss"
    return (f'<div class="ret-box"><span class="ret-label">매수가 대비</span>'
            f'<span class="ret {cls}">{ret:+.1f}%</span></div>')


def _returns_by_period(manifest: list[dict], price_cache: dict) -> dict:
    """발행일 기준 주간(7일)·월간(30일)·전체 평균 수익률을 집계.

    현재 날짜는 manifest의 가장 최근 발행일을 기준으로 삼는다(스크립트에서 Date.now 사용 불가 대비).
    """
    from datetime import date as _date

    rets = []  # (발행일, 수익률)
    for m in manifest:
        buy = m.get("buy")
        if not buy:
            continue
        key = (m.get("market"), m.get("ticker"))
        if key not in price_cache:
            price_cache[key] = current_price(m.get("market"), m.get("ticker"))
        cur = price_cache[key]
        if not cur:
            continue
        try:
            d = _date.fromisoformat(m["date"])
        except Exception:
            continue
        rets.append((d, (cur / buy - 1) * 100))
    if not rets:
        return {}
    ref = max(d for d, _ in rets)  # 최신 발행일 기준
    out = {}
    for label, days in (("week", 7), ("month", 30), ("all", None)):
        vals = [r for d, r in rets if days is None or (ref - d).days < days]
        if vals:
            out[label] = {"avg": sum(vals) / len(vals), "n": len(vals)}
    return out


def _summary_html(summary: dict) -> str:
    """주간·월간·전체 평균 수익률 요약 박스 HTML."""
    if not summary:
        return ""
    label = {"week": "주간(7일)", "month": "월간(30일)", "all": "전체"}
    cells = []
    for k in ("week", "month", "all"):
        s = summary.get(k)
        if not s:
            continue
        cls = "gain" if s["avg"] >= 0 else "loss"
        cells.append(f'<div class="sum-cell"><div class="sum-k">{label[k]} 평균</div>'
                     f'<div class="sum-v {cls}">{s["avg"]:+.1f}%</div>'
                     f'<div class="sum-n">{s["n"]}건</div></div>')
    return f'<div class="summary-box">{"".join(cells)}</div>'


def _refresh_report_returns(manifest: list[dict], price_cache: dict) -> None:
    """각 발행 리포트 상세 HTML의 헤더 수익률 배지를 현재가 기준으로 최신화.

    리포트 상세는 정적 HTML이라 발행 시점 값에 고정되므로, 목록을 갱신할 때 함께
    'hold-ret' 배지를 현재 수익률로 치환한다(수익=buy빨강/손실=sell파랑).
    """
    for m in manifest:
        buy = m.get("buy")
        if not buy:
            continue
        cur = price_cache.get((m.get("market"), m.get("ticker")))
        if not cur:
            continue
        ret = (cur / buy - 1) * 100
        color, bg = ("#ff8f86", "#2a1d1d") if ret >= 0 else ("#7fb2e5", "#16233a")
        p = WEB_DIR / m["path"]
        if not p.exists():
            continue
        html = p.read_text(encoding="utf-8")
        # 인라인 스타일로 배지 생성 → 기존(구버전 CSS 없는) 리포트에서도 색이 적용됨
        badge = (f'<span class="hold-ret" style="font-weight:700;border-radius:20px;'
                 f'padding:2px 10px;font-size:0.72em;color:{color};background:{bg}">'
                 f'매수가 대비 {ret:+.1f}%</span>')
        if "hold-ret" in html:  # 이미 배지가 있으면 교체
            html2 = re.sub(r'<span class="hold-ret[^>]*>[^<]*</span>', badge, html)
        else:  # 없으면 제목(종목명·티커) 뒤에 삽입
            html2 = re.sub(r'(<div class="title">.*?</span>)',
                           lambda mm: mm.group(1) + " " + badge, html, count=1, flags=re.S)
        if html2 != html:
            p.write_text(html2, encoding="utf-8")


def _build_index(manifest: list[dict]) -> None:
    """manifest 로부터 날짜별 목록 index.html 생성 + 각 리포트 상세 수익률 최신화."""
    price_cache: dict = {}
    summary = _returns_by_period(manifest, price_cache)
    _refresh_report_returns(manifest, price_cache)

    def fmt_target(m):
        t, up = m.get("target"), m.get("upside")
        if t is None:
            return ""
        cur = "₩" if m.get("market") == "KR" else "$"
        t_txt = f"{t:,.0f}" if m.get("market") == "KR" else f"{t:,.2f}"
        up_txt = f" ({up:+.1f}%)" if up is not None else ""
        return f" · 목표 {cur}{t_txt}{up_txt}"

    by_date: dict[str, list[dict]] = {}
    for m in manifest:
        by_date.setdefault(m.get("date", "?"), []).append(m)

    parts = ["""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stock Agent 리서치 리포트</title>
<style>
 :root{color-scheme:dark}
 html{background:#0f1319}
 body{font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;max-width:720px;margin:0 auto;
      padding:28px 18px 44px;background:#0f1319;color:#cfd6e1;line-height:1.7}
 h1{color:#e8edf5;font-size:22px;border-bottom:3px solid #3b6ea5;padding-bottom:10px}
 h1 .sub{color:#7fb2e5;font-size:12px;letter-spacing:2px;display:block;font-weight:700}
 h2{color:#7fb2e5;font-size:15px;margin:24px 0 8px;border-left:4px solid #3b6ea5;padding-left:8px}
 ul{list-style:none;padding:0;margin:0}
 li{margin:10px 0}
 a.card{display:block;background:#171d26;border:1px solid #2a3240;border-radius:12px;
        padding:14px 16px;text-decoration:none;color:#e8edf5;transition:border-color .15s}
 a.card:hover,a.card:active{border-color:#3b6ea5;background:#1a222e}
 .pick{display:inline-block;color:#7fb2e5;font-size:11px;font-weight:700;letter-spacing:1px;
       background:#16233a;border:1px solid #22304a;border-radius:20px;padding:2px 10px;margin-bottom:7px}
 .row1{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
 .stock{font-weight:700;font-size:16px}
 .op{font-weight:700;font-size:12px;border-radius:20px;padding:2px 10px}
 .buy{color:#ff8f86;background:#2a1d1d} .sell{color:#7fb2e5;background:#16233a} .hold{color:#e6c07b;background:#2a2417}
 .ret-box{margin-left:auto;display:flex;flex-direction:column;align-items:flex-end;gap:2px}
 .ret-label{color:#8b95a7;font-size:10px}
 .ret{font-weight:700;font-size:13px;border-radius:20px;padding:2px 10px}
 .ret.gain{color:#ff8f86;background:#2a1d1d} .ret.loss{color:#7fb2e5;background:#16233a}
 .summary-box{display:flex;gap:10px;margin:16px 0 8px;flex-wrap:wrap}
 .sum-cell{flex:1;min-width:90px;background:#171d26;border:1px solid #2a3240;border-radius:12px;padding:12px 14px;text-align:center}
 .sum-k{color:#8b95a7;font-size:11px}
 .sum-v{font-size:20px;font-weight:800;margin:3px 0} .sum-v.gain{color:#ff8f86} .sum-v.loss{color:#7fb2e5}
 .sum-n{color:#6b7480;font-size:10px}
 .row2{color:#9aa5b5;font-size:13.5px;margin-top:5px}
 .cta{color:#7fb2e5;font-size:12.5px;font-weight:700;margin-top:9px;padding-top:9px;
      border-top:1px dashed #2a3240;display:flex;justify-content:space-between;align-items:center}
 .foot{color:#6b7480;font-size:11px;margin-top:30px;border-top:1px solid #2a3240;padding-top:12px}
</style></head><body>
<h1><span class="sub">STOCK AGENT</span>📊 리서치 리포트</h1>""" + _summary_html(summary)]
    cls = {"매수": "buy", "매도": "sell", "중립": "hold"}
    pick_label = {"KR": "DAILY PICK - 한국", "US": "DAILY PICK - 미국"}
    for day in sorted(by_date, reverse=True):
        parts.append(f"<h2>{day}</h2><ul>")
        for m in sorted(by_date[day], key=lambda x: x.get("market", "")):
            op = m.get("opinion", "-")
            target_line = fmt_target(m).lstrip(" ·")  # 둘째 줄에 목표가·상승여력
            ret_badge = _return_badge(m, price_cache)
            parts.append(f"""<li><a class="card" href="{m["path"]}">
  <span class="pick">{pick_label.get(m.get("market"), m.get("market", ""))}</span>
  <div class="row1"><span class="stock">{m.get("name", "")} ({m.get("ticker", "")})</span>
    <span class="op {cls.get(op, "hold")}">{op}</span>{ret_badge}</div>
  {f'<div class="row2">{target_line}</div>' if target_line else ''}
  <div class="cta"><span>카드를 누르면 전체 리포트가 열립니다</span><span>리포트 보기 ›</span></div>
</a></li>""")
        parts.append("</ul>")
    parts.append("""<div class="foot">본 리포트는 AI(멀티 에이전트)가 공개 데이터를 바탕으로 자동 생성한 참고 자료이며,
투자 권유가 아닙니다. 투자 판단의 책임은 투자자 본인에게 있습니다.</div></body></html>""")
    (WEB_DIR / "index.html").write_text("\n".join(parts), encoding="utf-8")
