"""
규칙 기반 요약 생성기 (Claude API 키가 없을 때의 대체 서술).

수집한 숫자만으로 재무·시황·밸류에이션 요약문을 만들어, 무료 테스트 단계에서도
보고서가 비어 보이지 않게 합니다. 나중에 ANTHROPIC_API_KEY를 설정하면 이 자리는
Claude가 생성하는 고품질 서술로 자동 교체됩니다.

주의: 여기서 만드는 문장은 '단순 규칙'에 기반한 참고용 요약이며, 심층 해석이나
목표주가 산정은 하지 않습니다(그 부분은 AI 단계의 몫입니다).
"""
from __future__ import annotations

from typing import Optional

from ..models import AnalysisSection, StockData, Valuation

_NOTE = "(규칙 기반 자동 요약 · AI 미적용 단계)"


# --- 계산 헬퍼 ---------------------------------------------------------------
def _years_desc(fin: dict) -> list[str]:
    return sorted({y for m in fin.values() for y in m}, reverse=True)


def _val(fin: dict, key: str, year: str) -> Optional[float]:
    return fin.get(key, {}).get(year)


def _pct(now: Optional[float], past: Optional[float]) -> Optional[float]:
    if now is None or past is None or past == 0:
        return None
    return round((now / past - 1) * 100, 1)


def _ratio(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return round(a / b * 100, 1)


def _fmt(v: Optional[float], unit: str = "%") -> str:
    return "N/A" if v is None else f"{v:+.1f}{unit}" if unit == "%" and v is not None else f"{v:.1f}{unit}"


def _metrics(data: StockData) -> dict:
    """재무제표로부터 성장성/수익성/안정성 지표를 계산."""
    fin = data.financials
    m: dict = {}
    years = _years_desc(fin)
    if len(years) >= 1:
        y0 = years[0]
        rev0 = _val(fin, "revenue", y0)
        m["op_margin"] = _ratio(_val(fin, "operating_income", y0), rev0)
        m["net_margin"] = _ratio(_val(fin, "net_income", y0), rev0)
        m["debt_ratio"] = _ratio(_val(fin, "liabilities", y0), _val(fin, "equity", y0))
        m["roe"] = _ratio(_val(fin, "net_income", y0), _val(fin, "equity", y0))
        m["latest_year"] = y0
    if len(years) >= 2:
        y0, y1 = years[0], years[1]
        m["rev_growth"] = _pct(_val(fin, "revenue", y0), _val(fin, "revenue", y1))
        m["op_growth"] = _pct(_val(fin, "operating_income", y0), _val(fin, "operating_income", y1))
    return m


# --- 섹션 생성 ---------------------------------------------------------------
def fundamental_section(data: StockData) -> AnalysisSection:
    m = _metrics(data)
    if not m:
        return AnalysisSection(
            title="재무 분석",
            summary=f"{_NOTE} 재무제표 데이터가 없어 요약을 생성하지 못했습니다. "
                    "한국 종목은 DART 키가 필요하며, 미국 종목은 자동 수집됩니다.",
        )

    bullets = []
    if m.get("rev_growth") is not None:
        trend = "증가" if m["rev_growth"] >= 0 else "감소"
        bullets.append(f"매출 성장률(전년比): {m['rev_growth']:+.1f}% ({trend})")
    if m.get("op_margin") is not None:
        bullets.append(f"영업이익률: {m['op_margin']:.1f}%")
    if m.get("net_margin") is not None:
        bullets.append(f"순이익률: {m['net_margin']:.1f}%")
    if m.get("roe") is not None:
        bullets.append(f"ROE(자기자본이익률): {m['roe']:.1f}%")
    if m.get("debt_ratio") is not None:
        health = "양호" if m["debt_ratio"] < 100 else "다소 높음" if m["debt_ratio"] < 200 else "높음"
        bullets.append(f"부채비율: {m['debt_ratio']:.1f}% ({health})")

    # 요약문 조립 (명사구를 가운뎃점으로 이어 자연스럽게)
    parts = []
    if m.get("rev_growth") is not None:
        parts.append(f"매출 전년比 {m['rev_growth']:+.1f}%")
    if m.get("op_margin") is not None:
        parts.append(f"영업이익률 {m['op_margin']:.1f}%")
    if m.get("net_margin") is not None:
        parts.append(f"순이익률 {m['net_margin']:.1f}%")
    if m.get("debt_ratio") is not None:
        parts.append(f"부채비율 {m['debt_ratio']:.1f}%")
    summary = (f"{_NOTE} " + " · ".join(parts) + " 수준을 기록했습니다."
               if parts else f"{_NOTE} 재무 지표를 계산했습니다.")

    # 숫자 나열에 그치지 않도록, 규칙으로 판단 가능한 해석 한 줄을 덧붙인다
    interp = ""
    rg, og = m.get("rev_growth"), m.get("op_growth")
    if rg is not None and og is not None:
        if og > rg > 0:
            interp = " 이익이 매출보다 빠르게 늘어 수익성 레버리지가 나타나는 국면입니다."
        elif rg > 0 > og:
            interp = " 외형은 성장했지만 이익이 뒷걸음쳐 비용 부담이 커진 모습입니다."
        elif rg < 0 and og < 0:
            interp = " 매출과 이익이 함께 줄어 업황 둔화의 영향이 뚜렷합니다."
        elif rg < 0 < og:
            interp = " 매출은 줄었지만 이익이 늘어 체질 개선(비용 효율화)이 진행 중인 것으로 보입니다."

    body = (
        f"성장성 측면에서 매출 성장률은 {m.get('rev_growth', 'N/A')}%, "
        f"영업이익 성장률은 {m.get('op_growth', 'N/A')}%로 집계됩니다.{interp}\n\n"
        f"수익성 측면에서 영업이익률 {m.get('op_margin', 'N/A')}%, 순이익률 {m.get('net_margin', 'N/A')}%, "
        f"ROE {m.get('roe', 'N/A')}%를 기록했습니다.\n\n"
        f"안정성 측면에서 부채비율은 {m.get('debt_ratio', 'N/A')}% 수준입니다. "
        "구체적인 업종 비교와 심층 해석은 AI 분석 단계에서 보강됩니다."
    )
    return AnalysisSection(title="재무 분석", summary=summary, body=body, bullets=bullets)


def market_section(data: StockData) -> AnalysisSection:
    bullets = []
    if data.change_1m is not None:
        bullets.append(f"1개월 수익률: {data.change_1m:+.1f}%")
    if data.change_3m is not None:
        bullets.append(f"3개월 수익률: {data.change_3m:+.1f}%")
    if data.change_1y is not None:
        bullets.append(f"1년 수익률: {data.change_1y:+.1f}%")

    # 추세 판단 (현재가 vs 60일선)
    trend_txt = "판단 불가"
    if data.price is not None and data.ma60 is not None:
        trend_txt = "60일 이동평균선 위(상승 추세)" if data.price > data.ma60 else "60일 이동평균선 아래(하락/조정)"
        bullets.append(trend_txt)

    # 52주 위치
    pos_txt = ""
    if data.price and data.high_52w and data.low_52w and data.high_52w > data.low_52w:
        pos = (data.price - data.low_52w) / (data.high_52w - data.low_52w) * 100
        pos_txt = f" 현재가는 52주 밴드의 하단에서 {pos:.0f}% 지점에 위치합니다."
        bullets.append(f"52주 밴드 내 위치: {pos:.0f}%")

    ret3 = f"{data.change_3m:+.1f}%" if data.change_3m is not None else "N/A"
    summary = f"{_NOTE} 최근 3개월 주가는 {ret3} 변동했으며, {trend_txt}입니다.{pos_txt}"
    body = (
        f"주가 흐름을 보면 1개월 {_fmt(data.change_1m)}, 3개월 {_fmt(data.change_3m)}, "
        f"1년 {_fmt(data.change_1y)}의 수익률을 기록했습니다.\n\n"
        f"이동평균 기준으로는 {trend_txt}의 국면입니다.{pos_txt} "
        "거시 환경과 업종·수급에 대한 해석은 AI 분석 단계에서 보강됩니다."
    )
    # 차트 지표 요약(계산된 신호 나열 — 종합 해석은 AI 단계 몫)
    tech = ""
    t = data.technicals or {}
    if t.get("signals"):
        tech = (f"{_NOTE} 차트 지표 신호: " + " / ".join(t["signals"]) +
                ". 신호 간 종합 판단과 시나리오 해석은 AI 분석 단계에서 보강됩니다.")
    return AnalysisSection(title="시황·주가 분석", summary=summary, body=body,
                           bullets=bullets, technical_outlook=tech)


def valuation(data: StockData) -> Valuation:
    """단순 점수화로 방향성만 제시(목표주가는 산정하지 않음)."""
    m = _metrics(data)
    score = 0
    notes = []

    if data.per is not None:
        if data.per < 15:
            score += 1; notes.append(f"PER {data.per:.1f}배로 낮은 편")
        elif data.per > 30:
            score -= 1; notes.append(f"PER {data.per:.1f}배로 높은 편")
        else:
            notes.append(f"PER {data.per:.1f}배")
    if data.pbr is not None:
        if data.pbr < 1.5:
            score += 1; notes.append(f"PBR {data.pbr:.2f}배로 낮은 편")
        elif data.pbr > 4:
            score -= 1; notes.append(f"PBR {data.pbr:.2f}배로 높은 편")
    if m.get("net_margin") is not None and m["net_margin"] > 10:
        score += 1; notes.append("두 자릿수 순이익률")
    if m.get("rev_growth") is not None and m["rev_growth"] > 10:
        score += 1; notes.append("매출 두 자릿수 성장")
    if data.change_3m is not None:
        if data.change_3m > 0:
            score += 1
        elif data.change_3m < -10:
            score -= 1

    opinion = "매수" if score >= 2 else "매도" if score <= -2 else "중립"

    risks = []
    if data.per is not None and data.per > 30:
        risks.append("밸류에이션 부담(고 PER)")
    if m.get("rev_growth") is not None and m["rev_growth"] < 0:
        risks.append("매출 역성장")
    if m.get("debt_ratio") is not None and m["debt_ratio"] > 200:
        risks.append("높은 부채비율")
    if not data.financials:
        risks.append("재무 데이터 결측")
    if not risks:
        risks = ["시장 변동성", "업황 둔화 가능성"]

    rationale = (
        f"{_NOTE} 밸류에이션 지표는 " + (", ".join(notes) if notes else "제한적입니다") + ". "
        f"이를 단순 점수화하면 방향성은 '{opinion}'으로 나타납니다. "
        "정밀한 목표주가와 투자의견 근거는 AI 분석 단계에서 산정됩니다(현재는 목표주가 미산정). "
        "매수가·손절가는 기술적 기준(20일선/−8%)으로 제시됩니다."
    )
    from .context import trade_strategy, trade_zone
    lo, hi, stop, _ = trade_zone(data)
    nd = 2 if data.market == "US" else 0
    center = round((lo + hi) / 2, nd) if lo and hi else None
    return Valuation(opinion=opinion, target_price=None, upside_pct=None,
                     buy_price=center, buy_low=lo, buy_high=hi, stop_loss=stop,
                     rationale=rationale, risks=risks[:3], strategy=trade_strategy(data))


def thesis(data: StockData, fundamental: AnalysisSection,
           market: AnalysisSection, val: Valuation) -> str:
    m = _metrics(data)
    growth = f"{m['rev_growth']:+.1f}%" if m.get("rev_growth") is not None else "N/A"
    ret3 = f"{data.change_3m:+.1f}%" if data.change_3m is not None else "N/A"
    return (
        f"{_NOTE}\n\n"
        f"{data.name}은(는) 최근 매출이 전년 대비 {growth} 변동했고, 3개월 주가 수익률은 {ret3}입니다. "
        f"밸류에이션 지표를 단순 점수화한 방향성은 '{val.opinion}'입니다. "
        "본 요약은 객관적 수치에 기반한 참고용이며, 시장 맥락과 전망을 반영한 심층 투자 논지는 "
        "Anthropic API 키를 설정하면 Claude가 생성합니다."
    )
