"""
⑤ 밸류에이션 에이전트 (Claude + 계산).

재무·시황 분석 결과와 지표를 종합해 투자의견/목표주가/상승여력을 도출합니다.
목표주가는 Claude가 근거와 함께 제시하되, 상승여력은 현재가 기준으로 재계산합니다.
"""
from __future__ import annotations

from ..llm import llm
from ..models import AnalysisSection, StockData, Valuation
from . import rule_based
from .context import data_brief, trade_strategy, trade_zone

SYSTEM = (
    "당신은 증권사 리서치센터의 밸류에이션 담당 애널리스트입니다. "
    "PER/PBR 등 상대가치와 실적 추세를 근거로 투자의견과 목표주가를 산정합니다. "
    "반드시 데이터 범위 내에서 논리적으로 판단하고, 불확실성을 함께 밝힙니다."
)

_VALID_OPINIONS = {"매수", "중립", "매도"}


def evaluate(data: StockData, fundamental: AnalysisSection, market: AnalysisSection) -> Valuation:
    prompt = f"""다음 종목의 투자의견과 목표주가를 산정해 주세요.

{data_brief(data)}

[재무 분석 요약]
{fundamental.summary}

[시황 분석 요약]
{market.summary}

[목표주가 산정 규칙 — 반드시 지키세요]
- 목표주가는 '적용 지표 × 타깃 배수' 방식으로 산정하며, **12개월 목표주가**입니다.
  · PER 방식: 목표주가 = EPS × 타깃 PER   · PBR 방식: 목표주가 = BPS × 타깃 PBR
  · **지주사·자산주는 NAV/SOTP(순자산가치), 경기민감주는 정상화(사이클 평균) 이익 기준,
    적자·고성장주는 PSR/EV·선행이익** 등 종목 성격에 맞는 방식을 valuation_method에 쓰세요.
- **⚠ 타깃 배수 앵커(가장 중요)**: 타깃 배수는 당일 주가·시황에 흔들리지 말고 아래 앵커 범위에 고정하세요.
  ① 현재 PER(위 데이터의 PER) ② 시장 컨센서스 목표가가 함의하는 배수 ③ 업종 평균/과거 밴드.
  **타깃 배수는 이 앵커들의 ±30% 이내**에서만 정하고, 벗어나면 그 사유를 rationale에 반드시 명시하세요.
  '상승여력이 나오도록 배수를 키우는' 역산은 금지합니다(현재가가 올랐다고 목표가를 따라 올리지 마세요).
- **트레일링 PER이 이미 100배↑인 고밸류주는 트레일링 배수 확장 금지** → 선행 EPS 추정(컨센서스 성장률 차용)
  또는 PBR/EV 등 대체 지표로 전환하세요. 경기민감주에 트레일링 초고배수는 방어할 수 없습니다.
- valuation_method(방식), applied_multiple('단일' 타깃 배수), rationale의 산출식·target_price가 수치적으로 일치해야 합니다.
- rationale 은 밸류에이션 근거에 집중(약 450자, 매매 전략은 strategy 필드). **첫 문단에 산출식과 '12개월 목표'임을 명시**
  (예: "EPS 3.01달러 × 타깃 PER 12배 = 12개월 목표주가 36.12달러, 타깃 배수는 업종 평균 11배·컨센서스 함의 13배 범위 내").
- 시장 컨센서스가 있으면 참고하되 맹종하지 말고, 차이 나면 이유를 밝히세요.
- rationale에서 핵심 수치·결론 구절은 **이렇게** 별표 두 개로 강조하세요(문단당 1~3곳).

[매매 전략 — strategy 필드]
위 [매매 전략 참고]의 매수 구간·손절가와 아래 추세 강도를 근거로, 이 종목에 맞는 매매 전략을
2~3문장으로 새로 서술하세요(약 200자). 아래는 '판단 가이드'일 뿐 문구를 그대로 베끼지 말고,
이 종목의 수급·밸류에이션·뉴스까지 반영해 매번 다르게 작성하세요:
  · 추세 강도 7↑(견조한 상승): 추세추종 관점, 조정 시 매수·과열 시 대기.
  · 추세 강도 4~6(방향 불명): 확정 매수보다 긍정/부정 시나리오로 나눠 조건부 대응.
  · 추세 강도 3↓(약세): 신규 매수보다 관망·리스크 관리 우선.
'눌림목 분할매수' 같은 획일적 표현을 모든 종목에 반복하지 마세요.

[시나리오 분석 — 3개 필수]
- 강세(bull)/기본(base)/약세(bear) **3가지를 반드시** 제시하세요(누락 금지). 12개월 목표가 + 발생 확률(합계 100).
- 각 시나리오 basis에는 **방향을 가를 트리거**(예: 실적 발표 HBM 가이던스, 금리 등)를 포함하세요.
- base 시나리오의 가격은 target_price 와 일치해야 합니다.

아래 형식의 JSON으로만 답하세요. 숫자는 통화 {data.currency} 기준(단위 없이):
{{
  "opinion": "매수 | 중립 | 매도 중 하나",
  "valuation_method": "PER | PBR | 기타",
  "applied_multiple": 타깃_배수_숫자_또는_null,
  "target_price": 목표주가_숫자_또는_null,
  "scenarios": {{
    "bull": {{"price": 숫자, "prob": 확률_숫자, "basis": "핵심 조건 한 줄"}},
    "base": {{"price": 숫자, "prob": 확률_숫자, "basis": "핵심 조건 한 줄"}},
    "bear": {{"price": 숫자, "prob": 확률_숫자, "basis": "핵심 조건 한 줄"}}
  }},
  "strategy": "이 종목 상황에 맞춘 매매 전략 (약 200자, 위 가이드대로 매번 새로 작성)",
  "rationale": "투자의견과 목표주가 산정 근거를 밸류에이션 중심으로 서술 (약 450자)",
  "risks": ["주요 리스크 요인 3개 내외"]
}}"""
    result = llm.ask_json(prompt, system=SYSTEM, max_tokens=2500)
    if not result:
        # AI 미사용 시 규칙 기반 방향성 판단으로 대체
        return rule_based.valuation(data)

    opinion = str(result.get("opinion", "중립")).strip()
    if opinion not in _VALID_OPINIONS:
        opinion = "중립"

    target, recalced = _consistent_target(data, result)

    # 상승여력은 현재가 기준으로 직접 재계산 (LLM 산술 오류 방지)
    upside = round((target / data.price - 1) * 100, 1) if (target and data.price) else None

    # 진입 태도: 투자의견과 매수구간 위치의 정합성 (의견-전략 모순 방지 #4)
    entry_stance = _entry_stance(opinion, data)

    risks = result.get("risks", []) or []
    if isinstance(risks, str):
        risks = [risks]

    # 코드 재계산값을 채택했는데 LLM 서술값과 다르면, 본문-헤더 수치 불일치 오해를 막는 각주 추가
    rationale = result.get("rationale", "")
    if recalced:
        rationale = rationale.rstrip() + "\n\n(목표주가는 서술된 '지표 × 적용 배수' 산출식으로 재계산해 확정한 값입니다.)"

    lo, hi, stop, _ = trade_zone(data)
    nd = 2 if data.market == "US" else 0
    return Valuation(
        opinion=opinion,
        target_price=round(target, 2) if target else None,
        upside_pct=upside,
        buy_price=(round((lo + hi) / 2, nd) if lo and hi else None),
        buy_low=lo,
        buy_high=hi,
        stop_loss=stop,
        rationale=rationale,
        risks=risks,
        valuation_method=(str(result.get("valuation_method") or "").strip().upper() or None),
        applied_multiple=_num(result.get("applied_multiple")),
        scenarios=_parse_scenarios(result, data, target),
        # AI가 종목별로 새로 서술한 전략 우선, 비었으면 규칙기반으로 폴백
        strategy=(str(result.get("strategy") or "").strip() or trade_strategy(data)),
        entry_stance=entry_stance,
    )


def _entry_stance(opinion: str, data: StockData) -> str:
    """투자의견과 매수 구간 위치로 '진입 태도'를 규칙 산출 (의견-전략 모순 방지).

    매수구간 상단(hi)이 현재가 대비 어디인지로 즉시성/대기 여부를 판정한다.
    """
    lo, hi, _, _ = trade_zone(data)
    if not (hi and data.price):
        return ""
    # 중립·매도는 매수 권유가 아니므로 '관심 진입 레벨'로 통일 (의견-전략 모순 방지)
    if opinion != "매수":
        return "관심 진입 레벨"
    ratio = hi / data.price
    if ratio >= 0.98:          # 매수구간 상단이 현재가 바로 아래(≈지금 사도 되는 위치)
        return "즉시 매수권"
    elif ratio >= 0.93:        # 현재가보다 2~7% 아래 → 눌림목 대기
        return "조정 시 매수(즉시 매수 아님)"
    return "깊은 조정 대기"     # 7% 초과 아래 → 지금은 관망


def _parse_scenarios(result: dict, data: StockData, target) -> "dict | None":
    """LLM의 강세/베이스/약세 시나리오를 검증·정규화.

    - price 는 현재가의 0.1~10배 범위만 인정 (터무니없는 값 차단)
    - prob 합계는 100 으로 정규화, base 가격은 확정 목표가로 교체(일관성)
    - 유효 시나리오가 2개 미만이면 None (표를 그리지 않음)
    """
    raw = result.get("scenarios")
    if not isinstance(raw, dict):
        return None
    out: dict = {}
    for key in ("bull", "base", "bear"):
        s = raw.get(key)
        if not isinstance(s, dict):
            continue
        price, prob = _num(s.get("price")), _num(s.get("prob"))
        if price is None or prob is None or prob < 0:
            continue
        if data.price and not (0.1 * data.price <= price <= 10 * data.price):
            continue
        out[key] = {"price": round(price, 2), "prob": prob,
                    "basis": str(s.get("basis") or "").strip()[:80]}
    if len(out) < 2:
        return None
    if "base" in out and target:  # 헤더 목표가와 일치시킴
        out["base"]["price"] = round(float(target), 2)
    total = sum(s["prob"] for s in out.values())
    if total > 0:
        for s in out.values():
            s["prob"] = round(s["prob"] / total * 100)
    return out


def _num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _consistent_target(data: StockData, result: dict) -> tuple["float | None", bool]:
    """목표주가를 '지표 × 배수'로 코드에서 재계산해 배수-목표가 불일치를 제거.

    PER/PBR 방식이고 지표(EPS/BPS)가 양수이며 결과가 현재가의 0.3~4배 범위면 채택.
    그 외에는 LLM이 제시한 target_price를 사용한다.
    반환: (목표주가, LLM 서술값과 1% 이상 다른 재계산값을 채택했는지 여부)
    """
    method = str(result.get("valuation_method", "")).upper()
    mult = _num(result.get("applied_multiple"))
    llm_target = _num(result.get("target_price"))

    computed = None
    if mult and mult > 0:
        if method == "PER" and data.eps and data.eps > 0:
            computed = data.eps * mult
        elif method == "PBR" and data.bps and data.bps > 0:
            computed = data.bps * mult

    if computed and data.price and 0.3 * data.price <= computed <= 4 * data.price:
        # 컨센서스 앵커: 목표가가 시장 컨센서스에서 ±35% 넘게 벗어나면 그 경계로 클램프
        #  (배수가 당일 주가에 역산돼 목표가가 매일 흔들리는 것을 억제 — 리뷰 #1/#5)
        ct = _num(data.consensus_target)
        if ct and ct > 0:
            computed = min(max(computed, ct * 0.65), ct * 1.35)
        differs = llm_target is None or abs(computed - llm_target) / max(abs(llm_target), 1e-9) > 0.01
        return round(computed, 4), differs
    # 재계산 불가 시에도 컨센서스가 있으면 LLM 목표가를 컨센서스 ±35%로 클램프
    ct = _num(data.consensus_target)
    if llm_target and ct and ct > 0:
        clamped = min(max(llm_target, ct * 0.65), ct * 1.35)
        return clamped, abs(clamped - llm_target) / max(abs(llm_target), 1e-9) > 0.01
    return llm_target, False
