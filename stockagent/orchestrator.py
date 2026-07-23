"""
오케스트레이터 — 멀티 에이전트 파이프라인 조율.

전체 흐름:
  스크리너 → (후보별) 데이터수집 → 재무분석 → 시황분석 → 밸류에이션 → 보고서작성 → 차트 → PDF

비개발자 설명: 리서치센터의 '팀장' 역할입니다. 각 담당자(에이전트)에게 순서대로
일을 시키고, 결과물을 모아 최종 보고서(PDF)로 만들어 output 폴더에 저장합니다.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from .agents import fundamental, market, screener, valuation, writer
from .config import settings
from .datasources import kr, us
from .models import Candidate, Report
from .report import charts
from .report.html_builder import render_html
from .report.pdf import html_to_pdf


def _safe_filename(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣_.-]", "_", text)


def analyze_candidate(cand: Candidate, log=print) -> Report:
    """후보 1종목에 대한 전체 분석 파이프라인 실행 → Report 반환."""
    log(f"\n▶ 분석 시작: {cand.name} ({cand.ticker}) [{cand.market}]")

    # ② 데이터 수집
    log("  [2/6] 데이터 수집 (시세·재무·뉴스)...")
    src = kr if cand.market == "KR" else us
    data = src.fetch(cand)
    for w in data.warnings:
        log(f"      · 경고: {w}")

    # ③ 재무 분석
    log("  [3/6] 재무 분석 (Claude)...")
    fund_section = fundamental.analyze(data)

    # ④ 시황 분석
    log("  [4/6] 시황·주가 분석 (Claude)...")
    mkt_section = market.analyze(data)

    # ⑤ 밸류에이션
    log("  [5/6] 밸류에이션·투자의견 (Claude)...")
    val = valuation.evaluate(data, fund_section, mkt_section)

    # ⑥ 보고서 종합
    log("  [6/6] 투자 요약 종합 (Claude)...")
    thesis = writer.write_thesis(data, fund_section, mkt_section, val)

    report = Report(
        data=data,
        fundamental=fund_section,
        market=mkt_section,
        valuation=val,
        thesis=thesis,
        generated_at=date.today(),
        chart_paths=charts.build_charts(data),
        screen_score=cand.score if cand.score else None,
        screen_reasons=(list(cand.reasons) if cand.score else []),
    )
    # 자동 발굴 선정 이력(누적 횟수·연속) 반영
    from . import history
    st = history.stats(cand.market, cand.ticker)
    report.pick_count = st["count"]
    report.pick_streak = st["streak"]
    report.pick_first = st["first"]

    # 전일 대비 변경 요약 (같은 종목 직전 발행분과 목표가·의견 비교) — AI 리뷰 #6
    v = report.valuation
    if v:
        prev = history.prev_report(cand.market, cand.ticker)
        if prev:
            parts = []
            pt, ct = prev.get("target"), v.target_price
            if pt and ct and abs(ct - pt) / pt > 0.005:
                cur = "₩" if cand.market == "KR" else "$"
                fmt = (lambda x: f"{x:,.0f}") if cand.market == "KR" else (lambda x: f"{x:,.2f}")
                parts.append(f"목표가 {cur}{fmt(pt)}→{cur}{fmt(ct)} ({(ct/pt-1)*100:+.1f}%)")
            if prev.get("opinion") and prev["opinion"] != v.opinion:
                parts.append(f"의견 {prev['opinion']}→{v.opinion}")
            if parts:
                report.prev_change = f"전일({prev['date']}) 대비 " + " · ".join(parts)
        history.record_report(cand.market, cand.ticker, v.target_price, v.opinion,
                              getattr(v, "applied_multiple", None))
    return report


def render_report(report: Report, subdir: str = "", log=print) -> Path:
    """Report → PDF + HTML 저장. 날짜별 폴더에 보관하고 PDF 경로 반환.

    저장 위치: output/[subdir/]<날짜>/<파일명>.pdf (+ 같은 이름의 .html 원본)
    예) output/2026-07-16/2026-07-16_US_..._AMD.pdf
        output/watchlist/2026-07-16/...    (관심종목은 watchlist 하위에 날짜 폴더)
    HTML 원본을 함께 남겨 두면 나중에 PDF 없이도 내용 검토·재렌더가 쉽습니다.
    """
    html = render_html(report)
    base = f"{report.generated_at}_{report.data.market}_{_safe_filename(report.data.name)}_{report.data.ticker}"

    # 날짜별 폴더로 분류 보관 (subdir이 있으면 그 하위에 날짜 폴더 생성)
    out_dir = settings.output_dir
    if subdir:
        out_dir = out_dir / subdir
    out_dir = out_dir / str(report.generated_at)
    out_dir.mkdir(parents=True, exist_ok=True)

    # HTML 원본도 함께 저장 (검토·재활용·재렌더용)
    html_path = out_dir / f"{base}.html"
    html_path.write_text(html, encoding="utf-8")

    path = html_to_pdf(html, out_dir / f"{base}.pdf")
    log(f"  ✅ 저장 완료: {path}")
    log(f"     (HTML 원본 동시 저장: {html_path.name})")

    # GitHub Pages 웹 발행 (web/.git 있을 때만 동작, 실패해도 배치 계속)
    from .report import publish
    publish.publish(report, html_path, log=log)

    # 이메일 발송 — PDF 첨부 (.env에 MAIL_* 설정 시에만 동작, 실패해도 배치 계속)
    from . import mailer
    if mailer.enabled():
        mailer.send_report_mail(report, path, log=log)
    return path


def run(
    market_choice: str = "KR",
    top_n: int = 3,
    pool_size: int = 40,
    explicit_tickers: list[str] | None = None,
    log=print,
) -> list[Path]:
    """전체 파이프라인 실행. 생성된 보고서 경로 목록 반환."""
    log("=" * 60)
    log(" Stock Agent — 멀티 에이전트 리서치 파이프라인")
    log("=" * 60)
    log("API 키 상태:")
    log(settings.summary())
    log("")

    # ① 스크리닝
    log("[1/6] 종목 스크리닝...")
    candidates = screener.screen(
        market=market_choice,
        top_n=top_n,
        pool_size=pool_size,
        explicit_tickers=explicit_tickers,
        log=log,
    )
    if not candidates:
        log("  ⚠ 후보 종목이 없습니다. 종료합니다.")
        return []

    # 자동 발굴(스크리닝)로 뽑힌 종목은 관심종목에 누적 추가 (기존 목록 유지·중복 제외)
    if not explicit_tickers:
        from . import history, watchlist
        watchlist.add(candidates, log=log)
        history.record(candidates)  # 선정 이력 기록(누적 횟수·연속)

    # ②~⑥ 후보별 분석 + 렌더
    outputs: list[Path] = []
    summaries: list[str] = []
    for cand in candidates:
        try:
            report = analyze_candidate(cand, log=log)
            outputs.append(render_report(report, log=log))
            summaries.append(f"· {report.data.name} {report.valuation.opinion}")
        except Exception as e:
            log(f"  ✗ {cand.name} 분석 중 오류: {e}")

    # 카톡 요약 알림 — 여러 종목이므로 한 건으로 묶어 전송 (설정된 경우에만)
    from . import notify
    from .llm import llm
    if outputs and notify.enabled():
        head = f"[StockAgent] {market_choice} 리포트 {len(outputs)}건 완료"
        lines = [head] + summaries[:5]
        if llm.fallback_used:
            lines.append("⚠ 일부 섹션 규칙기반 대체(AI 폴백)")
        if notify.send_text("\n".join(lines)):
            log("  📱 카톡 요약 알림 전송 완료")

    log("\n" + "=" * 60)
    log(f" 완료: 보고서 {len(outputs)}건 생성 → {settings.output_dir}")
    log("=" * 60)
    return outputs


def run_best(market: str | None = None, pool_size: int = 40, log=print) -> list[Path]:
    """'가장 유망한 1종목'만 리포트로 생성.

    market="KR" 또는 "US" 지정 시 해당 시장 안에서, 미지정 시 한·미 통합해서 1종목 선정.
    AI 호출을 1종목(4회)으로 최소화 → 무료티어 호출 한도 부담이 적음.
    발굴된 종목은 관심종목에도 자동 추가된다.
    """
    from . import watchlist

    markets = [market] if market in ("KR", "US") else ["KR", "US"]
    scope = {"KR": "한국", "US": "미국"}.get(market, "한국·미국 통합")

    log("=" * 60)
    log(f" Stock Agent — {scope} 최유망 1종목 발굴 리포트")
    log("=" * 60)
    log("API 키 상태:")
    log(settings.summary())
    log("")

    log(f"[1/6] {scope} 스크리닝 (시세 기반, AI 미사용)...")
    cands = []
    for mkt in markets:
        cands += screener.screen(market=mkt, top_n=3, pool_size=pool_size, log=log)
    cands = [c for c in cands if c.score > -1e8]
    if not cands:
        log("  ⚠ 후보 종목이 없습니다. 종료합니다.")
        return []

    cands.sort(key=lambda c: c.score, reverse=True)
    log("\n  [후보 순위]")
    for c in cands[:6]:
        log(f"    {c.market}  {c.name}({c.ticker})  점수 {c.score}")
    best = cands[0]
    log(f"\n  ★ 최종 선정: {best.name}({best.ticker}) [{best.market}]  점수 {best.score}")

    watchlist.add([best], log=log)
    from . import history
    history.record([best])  # 오늘 선정 이력 기록(누적 횟수·연속 계산용)
    report = analyze_candidate(best, log=log)
    out = render_report(report, log=log)

    # 카톡 요약 알림 (카카오 API 연동이 설정된 경우에만 동작)
    from . import notify
    from .llm import llm
    if notify.enabled():
        if notify.send_report_summary(report, fallback=llm.fallback_used):
            log("  📱 카톡 요약 알림 전송 완료")

    log("\n" + "=" * 60)
    log(f" 완료: {best.name} 리포트 1건 → {out}")
    log("=" * 60)
    return [out]


def run_watchlist(log=print) -> list[Path]:
    """관심종목(watchlist.txt) 전체에 대해 리포트 생성 → output/watchlist/ 에 별도 저장."""
    from . import watchlist

    log("=" * 60)
    log(" Stock Agent — 관심종목(watchlist) 리포트")
    log("=" * 60)
    log("API 키 상태:")
    log(settings.summary())
    log("")

    candidates = watchlist.load(log=log)
    if not candidates:
        log("  ⚠ 관심종목이 없습니다. watchlist.txt 에 종목을 추가하세요.")
        return []
    log(f"[관심종목] {len(candidates)}개 종목 분석을 시작합니다.")

    outputs: list[Path] = []
    for cand in candidates:
        try:
            report = analyze_candidate(cand, log=log)
            outputs.append(render_report(report, subdir="watchlist", log=log))
        except Exception as e:
            log(f"  ✗ {cand.name}({cand.ticker}) 분석 중 오류: {e}")

    log("\n" + "=" * 60)
    log(f" 완료: 관심종목 보고서 {len(outputs)}건 → {settings.output_dir / 'watchlist'}")
    log("=" * 60)
    return outputs
