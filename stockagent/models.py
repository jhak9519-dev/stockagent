"""
데이터 모델 (에이전트들이 주고받는 '서류 양식').

비개발자 설명: 각 에이전트가 다음 에이전트에게 넘기는 표준 서류 포맷입니다.
서류 칸이 정해져 있어야 서로 오해 없이 일을 이어받을 수 있습니다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional


# ---------------------------------------------------------------------------
# ① 스크리너 결과: 분석할 후보 종목
# ---------------------------------------------------------------------------
@dataclass
class Candidate:
    ticker: str            # 종목 코드 (한국: "005930", 미국: "AAPL")
    name: str              # 종목명
    market: str            # "KR" 또는 "US"
    score: float = 0.0     # 스크리닝 점수 (높을수록 우선 분석)
    reasons: list[str] = field(default_factory=list)  # 후보로 뽑힌 근거


# ---------------------------------------------------------------------------
# ② 데이터 수집 결과: 한 종목의 원천 데이터 묶음
# ---------------------------------------------------------------------------
@dataclass
class StockData:
    ticker: str
    name: str
    market: str

    # 시세 관련
    price: Optional[float] = None            # 현재가(최근 종가)
    currency: str = "KRW"
    price_history: Any = None                # pandas DataFrame (OHLCV)
    change_1m: Optional[float] = None        # 1개월 등락률(%)
    change_3m: Optional[float] = None
    change_1y: Optional[float] = None
    ma20: Optional[float] = None             # 20일 이동평균
    ma60: Optional[float] = None
    high_52w: Optional[float] = None
    low_52w: Optional[float] = None
    volume_avg: Optional[float] = None

    # 밸류에이션 지표
    market_cap: Optional[float] = None
    per: Optional[float] = None
    pbr: Optional[float] = None
    eps: Optional[float] = None
    bps: Optional[float] = None
    dividend_yield: Optional[float] = None

    # 시장 컨센서스 (애널리스트 평균)
    consensus_target: Optional[float] = None   # 평균 목표주가
    consensus_high: Optional[float] = None     # 최고 목표주가
    consensus_low: Optional[float] = None      # 최저 목표주가
    consensus_rating: Optional[str] = None     # 평균 투자의견
    analyst_count: Optional[int] = None        # 분석 기관 수
    broker_reports: list[dict[str, str]] = field(default_factory=list)  # 증권사 리포트·목표주가 관련 뉴스

    # 재무 (연간, 최신 순). 각 항목은 {연도: 값} 형태
    financials: dict[str, dict[str, float]] = field(default_factory=dict)
    sector: Optional[str] = None
    industry: Optional[str] = None
    earnings_date: Optional[str] = None      # 다음 실적 발표(예정)일 "YYYY-MM-DD" (US만 수집 가능)
    technicals: Optional[dict] = None        # 기술적 지표(일목·볼린저·이평·RSI·MACD) 값·신호
    trading_flows: Optional[dict] = None     # 투자자별 매매동향(KR: 개인/외국인/기관, US: 보유·공매도)

    # 뉴스/컨센서스 (제목 리스트 등)
    news: list[dict[str, str]] = field(default_factory=list)

    # 수집 중 발생한 경고(데이터 결측 등)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ③~⑤ 분석 결과 (각 분석 에이전트의 산출물)
# ---------------------------------------------------------------------------
@dataclass
class AnalysisSection:
    title: str                       # 섹션 제목 (예: "재무 분석")
    summary: str = ""                # 3~4문장 요약
    body: str = ""                   # 상세 서술 (여러 문단)
    bullets: list[str] = field(default_factory=list)  # 핵심 포인트
    technical_outlook: str = ""      # (시황 섹션 전용) 차트 지표 기반 주가 전망 서술


@dataclass
class Valuation:
    opinion: str = "중립"            # 투자의견: 매수/중립/매도
    target_price: Optional[float] = None
    upside_pct: Optional[float] = None   # 현재가 대비 상승여력(%)
    buy_price: Optional[float] = None    # 매수 희망가 중심(하위 호환용)
    buy_low: Optional[float] = None      # 매수 희망 구간 하단 (지지선 기반)
    buy_high: Optional[float] = None     # 매수 희망 구간 상단 (눌림목)
    stop_loss: Optional[float] = None    # 손절가(구간 하단 -5%)
    rationale: str = ""              # 근거 서술
    risks: list[str] = field(default_factory=list)
    valuation_method: Optional[str] = None    # 목표주가 산출 방식: "PER" | "PBR" | 기타
    applied_multiple: Optional[float] = None  # 적용한 타깃 배수 (리포트에 산출식 표기용)
    scenarios: Optional[dict] = None          # 강세/베이스/약세 시나리오 {bull|base|bear: {price, prob, basis}}
    strategy: str = ""                        # 매매 전략 (추세강도 기반 규칙 생성 — 편향 방지)
    entry_stance: str = ""                    # 진입 태도: "즉시 매수권"|"조정 시 매수"|"관심 진입 레벨"(의견-매수구간 정합)


# ---------------------------------------------------------------------------
# ⑥ 최종 보고서
# ---------------------------------------------------------------------------
@dataclass
class Report:
    data: StockData
    fundamental: Optional[AnalysisSection] = None
    market: Optional[AnalysisSection] = None
    valuation: Optional[Valuation] = None
    thesis: str = ""                 # 투자 요약(Executive summary)
    generated_at: date = field(default_factory=date.today)
    chart_paths: dict[str, str] = field(default_factory=dict)  # 차트 이미지 경로
    screen_score: Optional[float] = None  # 스크리너 점수(자동 발굴 시)
    screen_reasons: list[str] = field(default_factory=list)  # 스크리너 선정 근거(자동 발굴 시)
    pick_count: int = 0        # 자동 발굴 누적 선정 횟수
    pick_streak: int = 0       # 최근 연속 선정 횟수
    pick_first: Optional[str] = None  # 최초 선정일
    prev_change: str = ""      # 직전 발행 리포트 대비 목표가·의견 변경 요약
