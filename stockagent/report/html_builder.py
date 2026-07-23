"""Report 객체 -> HTML 문자열 (Jinja2 템플릿 렌더)."""
from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from ..agents.context import buy_zone, human_marcap, human_price, overheat_flag
from ..models import Report

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def _emphasize(text) -> Markup:
    """AI가 **별표 두 개**로 마킹한 핵심 구절을 <b>강조</b>로 변환.

    나머지 텍스트는 전부 HTML 이스케이프해 안전하게 렌더한다(가독성 개선, 2026-07-16).
    """
    s = str(escape(text or ""))
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s, flags=re.S)
    return Markup(s)


_env.filters["emph"] = _emphasize


def _num(v, unit="", nd=0):
    if v is None:
        return "N/A"
    if isinstance(v, float):
        return f"{v:,.{nd}f}{unit}"
    return f"{v:,}{unit}"


_OPINION_CLASS = {"매수": "buy", "중립": "hold", "매도": "sell"}


def _screen_grade(score) -> str:
    """자동발굴 점수의 구간별 등급 라벨 (점수 절대값의 의미 부여 — 리뷰 #8)."""
    if score is None:
        return ""
    if score >= 70:
        return "유망"
    if score >= 50:
        return "관찰"
    return "참고"


def render_html(report: Report) -> str:
    d = report.data
    v = report.valuation
    tpl = _env.get_template("report.html.j2")

    market_label = "KOSPI/KOSDAQ (한국)" if d.market == "KR" else "S&P500 (미국)"
    upside = "N/A"
    if v and v.upside_pct is not None:
        sign = "+" if v.upside_pct >= 0 else ""
        upside = f"{sign}{v.upside_pct}%"

    # 매수 희망 구간 — 지지선 기반(buy_low/high)이 있으면 우선, 없으면 구식 ±2% 폴백
    buy_display = "N/A"
    if v and v.buy_low and v.buy_high:
        buy_display = f"{human_price(v.buy_low, d.market)} ~ {human_price(v.buy_high, d.market)}"
    elif v and v.buy_price:
        zone = buy_zone(v.buy_price, d.market)
        if zone:
            lo, hi = zone
            buy_display = f"{human_price(lo, d.market)} ~ {human_price(hi, d.market)}"

    # 매수 구간 산출 근거(각주) — trade_zone의 실제 basis를 동적으로 (하락추세 폴백 시 오표기 방지 #2)
    from ..agents.context import trade_zone
    _, _, _, buy_basis = trade_zone(d)

    # 컨센서스 표시(범위 포함)
    consensus_target = None
    if d.consensus_target:
        consensus_target = human_price(d.consensus_target, d.market)
        if d.consensus_high and d.consensus_low:
            consensus_target += (f" (최저 {human_price(d.consensus_low, d.market)}"
                                 f" ~ 최고 {human_price(d.consensus_high, d.market)})")

    # 시세 기준일 (가격 데이터의 마지막 거래일 — 발행일과 다를 수 있음)
    price_date = None
    try:
        if d.price_history is not None and len(d.price_history):
            price_date = str(d.price_history.index[-1])[:10]
    except Exception:
        pass

    # 목표주가 산출식 표기 (PER/PBR 방식 + 배수가 있을 때)
    valuation_formula = None
    if v and v.target_price and v.valuation_method in ("PER", "PBR") and v.applied_multiple:
        base = d.eps if v.valuation_method == "PER" else d.bps
        if base and base > 0:
            base_label = "EPS" if v.valuation_method == "PER" else "BPS"
            valuation_formula = (f"{base_label} {human_price(base, d.market)}"
                                 f" × 타깃 {v.valuation_method} {v.applied_multiple:g}배"
                                 f" = 목표주가 {human_price(v.target_price, d.market)}")

    # 목표주가 색상: 상승여력 음수면 하락 색으로 (항상 빨간색이던 문제 수정)
    target_class = "sell" if (v and v.upside_pct is not None and v.upside_pct < 0) else "buy"

    # 발행 당시 매수가(구간 중심) 대비 현재가 수익률 (수익 빨강/손실 파랑)
    hold_return = None
    hold_class = "buy"
    if v and d.price:
        buy_mid = None
        if getattr(v, "buy_low", None) and getattr(v, "buy_high", None):
            buy_mid = (v.buy_low + v.buy_high) / 2
        elif getattr(v, "buy_price", None):
            buy_mid = v.buy_price
        if buy_mid:
            ret = (d.price / buy_mid - 1) * 100
            hold_return = f"{ret:+.1f}%"
            hold_class = "buy" if ret >= 0 else "sell"

    # 시나리오 표 + 확률가중 기대값 (벤치마킹, 2026-07-20)
    scenario_rows, expected_line = [], None
    sc = getattr(v, "scenarios", None) if v else None
    if sc:
        names = {"bull": "🚀 강세", "base": "기본", "bear": "📉 약세"}
        ev = 0.0
        for key in ("bull", "base", "bear"):
            s = sc.get(key)
            if not s:
                continue
            scenario_rows.append((names[key], human_price(s["price"], d.market),
                                  f"{s['prob']:.0f}%", s.get("basis", "")))
            ev += s["price"] * s["prob"] / 100
        if ev and d.price:
            expected_line = (f"확률가중 기대값 ≈ {human_price(ev, d.market)}"
                             f" (현재가 대비 {(ev / d.price - 1) * 100:+.1f}%)")

    # 리스크/리워드 비율 (매수구간 중심 진입 기준)
    rr_text = None
    if v and v.target_price and v.buy_low and v.buy_high and v.stop_loss:
        center = (v.buy_low + v.buy_high) / 2
        reward, risk = v.target_price - center, center - v.stop_loss
        if reward > 0 and risk > 0:
            rr_text = f"리스크/리워드 ≈ {reward / risk:.1f} : 1 (매수구간 중심 진입 시 손실 대비 기대이익)"

    # 지지·저항 레벨 (기술적 지표값 기반)
    levels = (d.technicals or {}).get("levels") or {}

    def _lv(items):
        # 여러 지지·저항 레벨을 각 줄로 분리해 표에서 깔끔히 보이게 (한 칸에 나열 금지)
        parts = [f"{n} {human_price(p, d.market)}" for n, p in items]
        return Markup("<br>".join(escape(x) for x in parts)) if parts else None

    level_sup, level_res = _lv(levels.get("support", [])), _lv(levels.get("resistance", []))

    # 현금흐름(영업활동현금흐름·FCF) 최신 연도 값 — 재무 지표 표에 행으로 표시
    def _latest_cf(key):
        vals = (d.financials or {}).get(key) or {}
        if not vals:
            return None
        year = max(vals.keys())
        return human_marcap(vals[year], d.market)
    op_cash_flow = _latest_cf("op_cash_flow")
    free_cash_flow = _latest_cf("free_cash_flow")

    # 기술적 지표 표 (지표명, 판독)
    tech_table = (d.technicals or {}).get("table") or []

    # 수급 동향 표
    flows_rows, flows_note, flows_daily, flows_daily_us = [], "", [], []
    f = d.trading_flows or {}
    if d.market == "KR" and f:
        def _flow(x):
            return f"{x:+,.1f}억" if x is not None else "N/A"
        if f.get("individual") is not None:
            # 외국인: 순매수 금액과 보유율을 각 줄로 분리(한 칸에 붙여쓰지 않음)
            foreign_val = _flow(f.get("foreign"))
            if f.get("foreign_hold_ratio"):
                foreign_val = Markup("%s<br><span style='color:#888;'>보유율 %s</span>") % (
                    foreign_val, f["foreign_hold_ratio"])
            flows_rows = [
                (f"개인 순매수 ({f.get('period', '')})", _flow(f.get("individual"))),
                ("외국인 순매수", foreign_val),
                ("기관 순매수", _flow(f.get("institution"))),
            ]
        p = f.get("pension") or {}
        if p.get("direction"):
            amt = f"{p['amount_100m']:,.0f}억원 " if p.get("amount_100m") else ""
            flows_rows.append(("연기금", f"{amt}{p['direction']} 상위 포착 (기준일 {p.get('date', '-')})"))
        elif p.get("date"):
            flows_rows.append(("연기금", f"매매 상위 목록에 없음 (기준일 {p['date']})"))
        flows_note = ("· 순매수 금액은 주식수×당일 종가 추정치(출처: 네이버증권). "
                      "연기금은 일별 매매 상위 목록 기준(출처: judal.co.kr) — 목록에 없으면 대규모 매매 없음으로 해석.")
        # 일자별 최근 7거래일 표 — 포맷+부호색을 여기서 처리
        # 순매수(+)·주가상승(+)=빨강(buy), 순매도(-)·하락(-)=파랑(sell) : (표시문자열, 색클래스) 튜플
        def _sc(x):
            if x is None:
                return ("-", "")
            cls = "buy" if x > 0 else "sell" if x < 0 else ""
            return (f"{x:+,.1f}", cls)

        def _chg(x):
            if x is None:
                return ("-", "")
            cls = "buy" if x > 0 else "sell" if x < 0 else ""
            return (f"{x:+.2f}%", cls)
        for row in (f.get("daily") or []):
            flows_daily.append((
                row["date"],
                human_price(row.get("close"), d.market),
                _chg(row.get("change")),
                _sc(row["individual"]), _sc(row["foreign"]), _sc(row["institution"]),
            ))
    elif f:
        if f.get("institution_hold") is not None:
            flows_rows.append(("기관 보유 비중", f"{f['institution_hold']}%"))
        if f.get("insider_hold") is not None:
            flows_rows.append(("내부자 보유 비중", f"{f['insider_hold']}%"))
        if f.get("short_pct_float") is not None:
            flows_rows.append(("공매도 비중(유통주식)", f"{f['short_pct_float']}%"))
        if f.get("short_ratio") is not None:
            flows_rows.append(("공매도 커버 소요일", f"{f['short_ratio']}일"))
        flows_note = ("· 미국은 투자자 유형별 매매 데이터가 공개되지 않아 보유·공매도 지표와 "
                      "일별 주가·거래량으로 수급을 갈음합니다. 출처: yfinance")
        # 일별 주가·등락률·거래량 표 (상승 빨강/하락 파랑)
        def _chg_us(x):
            if x is None:
                return ("-", "")
            cls = "buy" if x > 0 else "sell" if x < 0 else ""
            return (f"{x:+.2f}%", cls)

        def _vol(x):
            if x is None:
                return "-"
            return f"{x / 1e6:,.1f}M" if x >= 1e6 else f"{x / 1e3:,.0f}K"
        for row in (f.get("daily") or []):
            flows_daily_us.append((row["date"], human_price(row.get("close"), d.market),
                                   _chg_us(row.get("change")), _vol(row.get("volume"))))

    return tpl.render(
        name=d.name,
        ticker=d.ticker,
        sector=d.sector or "-",
        market_label=market_label,
        generated_at=str(report.generated_at),
        price_date=price_date,
        earnings_date=d.earnings_date,
        overheat=overheat_flag(d),
        screen_score=report.screen_score,
        screen_grade=_screen_grade(report.screen_score),
        screen_reasons=report.screen_reasons[:3],
        pick_count=report.pick_count,
        pick_streak=report.pick_streak,
        pick_first=report.pick_first,
        prev_change=report.prev_change,
        valuation_formula=valuation_formula,
        target_class=target_class,
        hold_return=hold_return,
        hold_class=hold_class,
        buy_basis=buy_basis,
        entry_stance=(v.entry_stance if v else ""),
        op_cash_flow=op_cash_flow,
        free_cash_flow=free_cash_flow,
        tech_table=tech_table,
        flows_rows=flows_rows,
        flows_note=flows_note,
        flows_daily_us=flows_daily_us,
        scenario_rows=scenario_rows,
        expected_line=expected_line,
        rr_text=rr_text,
        level_sup=level_sup,
        level_res=level_res,
        flows_daily=flows_daily,
        currency=d.currency,
        price=human_price(d.price, d.market),
        market_cap=human_marcap(d.market_cap, d.market),
        opinion=(v.opinion if v else "중립"),
        opinion_class=_OPINION_CLASS.get(v.opinion if v else "중립", "hold"),
        target_price=human_price(v.target_price, d.market) if (v and v.target_price) else "N/A",
        buy_price=buy_display,
        stop_loss=human_price(v.stop_loss, d.market) if (v and v.stop_loss) else "N/A",
        upside=upside,
        thesis=report.thesis or "(투자 요약 생성 안 됨)",
        chart_price=report.chart_paths.get("price"),
        chart_financial=report.chart_paths.get("financial"),
        market=report.market,
        fundamental=report.fundamental,
        valuation=v,
        per=_num(d.per, nd=2),
        pbr=_num(d.pbr, nd=2),
        eps=human_price(d.eps, d.market),
        bps=human_price(d.bps, d.market),
        dividend_yield=_num(d.dividend_yield, "%", nd=2) if d.dividend_yield is not None else "무배당(-)",
        high_52w=human_price(d.high_52w, d.market),
        low_52w=human_price(d.low_52w, d.market),
        consensus_target=consensus_target,
        consensus_rating=d.consensus_rating,
        analyst_count=int(d.analyst_count) if d.analyst_count else None,
        broker_reports=d.broker_reports[:5],
        news=d.news[:5],
        warnings="; ".join(d.warnings) if d.warnings else "",
    )
