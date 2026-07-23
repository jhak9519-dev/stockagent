"""
③ 재무 분석가 에이전트 (Claude).

재무제표를 해석하여 성장성·수익성·안정성 관점의 분석 섹션을 생성합니다.
"""
from __future__ import annotations

from ..llm import llm
from ..models import AnalysisSection, StockData
from . import rule_based
from .context import data_brief

SYSTEM = (
    "당신은 증권사 리서치센터의 재무 분석 전문 애널리스트입니다. "
    "제공된 데이터 범위 안에서만 사실에 근거해 분석하고, 데이터가 없으면 없다고 명시합니다. "
    "과장 없이 전문적이고 균형 잡힌 한국어 문체로 서술합니다."
)


def analyze(data: StockData) -> AnalysisSection:
    prompt = f"""다음 종목의 재무 상태를 분석해 주세요.

{data_brief(data)}

[분량 — 반드시 지킬 것] 2페이지 리포트로 압축 중입니다. 각 필드의 '목표 글자 수'를 지키되
문장은 자연스럽게 끝맺으세요. 수치 나열·반복 금지, 핵심 해석 위주.
[강조 표기] summary와 body에서 핵심 수치·결론 구절은 **이렇게** 별표 두 개로 감싸 강조하세요(문단당 1~3곳).

아래 형식의 JSON으로만 답하세요:
{{
  "summary": "재무 상태 총평 (약 130자, 2~3문장)",
  "bullets": ["핵심 포인트 3개 (각 40자 이내: 성장성/수익성/안정성)"],
  "body": "매출·이익 추세, 마진, 재무 안정성을 근거 수치와 함께 서술 (약 400자, 2문단)"
}}"""
    result = llm.ask_json(prompt, system=SYSTEM, max_tokens=1800)
    if not result:
        # API 키가 없으면 규칙 기반 요약으로 대체
        return rule_based.fundamental_section(data)
    return AnalysisSection(
        title="재무 분석",
        summary=result.get("summary", ""),
        body=result.get("body", ""),
        bullets=result.get("bullets", []) or [],
    )
