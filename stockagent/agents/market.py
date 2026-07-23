"""
④ 시황/뉴스 분석가 에이전트 (Claude).

주가 흐름, 업종 위치, 뉴스 심리를 바탕으로 시장 관점의 분석 섹션을 생성합니다.
"""
from __future__ import annotations

from ..llm import llm
from ..models import AnalysisSection, StockData
from . import rule_based
from .context import data_brief

SYSTEM = (
    "당신은 증권사 리서치센터의 시황·산업 분석 애널리스트입니다. "
    "거시/업종 환경과 종목의 주가 흐름·수급을 연결해 균형 있게 해석합니다. "
    "확인되지 않은 정보는 단정하지 않고, 한국어로 전문적으로 서술합니다."
)


def analyze(data: StockData) -> AnalysisSection:
    prompt = f"""다음 종목의 '거시환경·업종·수급'을 포함한 시황을 심층 분석해 주세요.

{data_brief(data)}

[반드시 다룰 내용]
1) 거시환경: 금리·환율·경기 사이클 등이 이 종목/업종에 주는 영향(제공된 뉴스·업종 정보 범위 내에서 해석).
2) 업종 내 위치: 해당 업종의 업황 국면과 동사의 경쟁적 위치.
3) 수급·주가 흐름: 위 [수급 동향]의 투자자별 매매(개인/외국인/기관 또는 보유·공매도)를 근거로
   누가 사고 파는지, 주가 흐름과 어떻게 맞물리는지 해석.
4) 뉴스·증권사 시각: 제공된 최근 뉴스와 증권사 리포트·목표주가 언급을 반영.
근거 없는 단정은 피하고, 데이터 범위 내에서 서술하세요.

[차트 관점 전망 — technical_outlook 필드]
위 [기술적 지표]의 일목균형표·볼린저밴드·이동평균 배열·RSI·MACD 신호를 종합해,
차트 관점 주가 전망(핵심 지지/저항, 추세 지속/전환 가능성)을 1~2문단으로 간결히 서술하세요.
지표가 엇갈리면 어느 쪽을 더 신뢰하는지 이유를 밝히고, 방향 확신이 낮으면 단정하지 말고 조건부로 서술하세요.

[분량 — 반드시 지킬 것] 2페이지 리포트로 압축 중입니다. 각 필드의 '목표 글자 수'를 지키되,
문장은 자연스럽게 끝맺으세요(중간에 끊지 말 것). 장황한 배경·반복 금지.
[강조 표기] summary·body·technical_outlook에서 핵심 수치·결론 구절은 **이렇게** 별표 두 개로 감싸 강조하세요(문단당 1~3곳).

아래 형식의 JSON으로만 답하세요:
{{
  "summary": "거시·업종·수급을 아우른 시황 총평 (약 150자, 2~3문장)",
  "bullets": ["핵심 포인트 4개 (각 40자 이내: 거시·업종, 수급/추세, 뉴스·증권사 시각, 리스크)"],
  "body": "거시·업종 → 수급/주가 흐름 → 뉴스·증권사 시각 순으로 서술 (약 550자, 3문단 이내)",
  "technical_outlook": "차트 지표 기반 주가 전망 (약 250자, 지지/저항·추세 핵심만)"
}}"""
    result = llm.ask_json(prompt, system=SYSTEM, max_tokens=2500)
    if not result:
        # API 키가 없으면 규칙 기반 요약으로 대체
        return rule_based.market_section(data)
    return AnalysisSection(
        title="시황·주가 분석",
        summary=result.get("summary", ""),
        body=result.get("body", ""),
        bullets=result.get("bullets", []) or [],
        technical_outlook=result.get("technical_outlook", "") or "",
    )
