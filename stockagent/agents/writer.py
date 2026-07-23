"""
⑥ 보고서 작성가 에이전트 (Claude).

재무·시황·밸류에이션 결과를 하나의 '투자 요약(Executive Summary)'으로 종합합니다.
증권사 리포트 첫 페이지의 핵심 논지에 해당합니다.
"""
from __future__ import annotations

from ..llm import llm
from ..models import AnalysisSection, StockData, Valuation
from . import rule_based
from .context import data_brief

SYSTEM = (
    "당신은 증권사 리서치센터의 수석 애널리스트로, 개별 분석을 종합해 "
    "명확한 투자 논지(Thesis)를 제시하는 보고서를 작성합니다. "
    "전문적이되 이해하기 쉬운 한국어로, 근거에 기반해 서술합니다."
)


def write_thesis(
    data: StockData,
    fundamental: AnalysisSection,
    market: AnalysisSection,
    valuation: Valuation,
) -> str:
    prompt = f"""아래 자료를 종합하여, 이 종목에 대한 '투자 논지(Executive Summary)'를 작성해 주세요.

{data_brief(data)}

[재무 분석] {fundamental.summary}
[시황 분석] {market.summary}
[투자의견] {valuation.opinion} / 목표주가 {valuation.target_price} {data.currency} (상승여력 {valuation.upside_pct}%)
[투자 근거] {valuation.rationale}

[분량·서술 지침 — 반드시 지킬 것]
- **약 350자, 정확히 2문단, 총 5~6문장 이내로 간결하게** 작성하세요(문장은 자연스럽게 끝맺을 것). 장황한 배경·반복 금지.
- 1문단: 핵심 투자 논지(업황·실적·밸류에이션을 엮어 왜 지금 주목하는지) + 목표주가·투자의견.
- 2문단: 컨센서스/증권사 시각과의 비교, 매수 구간·손절가를 활용한 진입·리스크 관리 요점.
- 핵심 수치·결론 구절(투자의견, 목표주가, 결정적 근거)은 **이렇게** 별표 두 개로 감싸 강조하세요.
  문단당 1~3곳만 — 남발 금지.
- **이 종목에서만 성립하는 고유 논점 1개를 반드시 포함**하세요(다른 종목에 복붙 불가한 사업구조·회계
  특이사항·세그먼트 구성 등). "AI 사이클 수혜→급등→눌림목 매수" 같은 일반 서사만 반복하지 마세요.
- 근거 없는 단정은 피하고 데이터 범위 내에서만 서술하세요.

투자 요약 본문만 출력하세요(제목/머리말 없이)."""
    if llm.available:
        text = llm.ask(prompt, system=SYSTEM, max_tokens=2000, temperature=0.5)
        if text:  # AI 호출 성공(실패 시 "" 반환)
            return text
    # AI 미사용 또는 호출 실패 시 규칙 기반 요약으로 대체(공백 방지)
    return rule_based.thesis(data, fundamental, market, valuation)
