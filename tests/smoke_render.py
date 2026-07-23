"""
오프라인 스모크 테스트 — 네트워크/API 키 없이 렌더링 파이프라인만 검증.

가짜(mock) 데이터로 차트 → HTML → PDF 생성까지 통과하는지 확인합니다.
실행:  python tests/smoke_render.py
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

os.environ["STOCKAGENT_NO_PUBLISH"] = "1"  # 스모크는 실서비스 웹에 발행하지 않음

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stockagent.models import AnalysisSection, Report, StockData, Valuation
from stockagent.orchestrator import render_report
from stockagent.report import charts


def _mock_data() -> StockData:
    # 가짜 주가 시계열 (완만한 상승 + 노이즈, 랜덤 시드 고정)
    rng = np.random.default_rng(42)
    days = pd.date_range("2024-01-01", periods=400, freq="B")
    walk = np.cumsum(rng.normal(0.05, 1.0, len(days))) + 100
    close = pd.Series(walk, index=days).clip(lower=1)
    hist = pd.DataFrame({
        "Open": close, "High": close * 1.01, "Low": close * 0.99,
        "Close": close, "Volume": rng.integers(1_000_000, 5_000_000, len(days)),
    }, index=days)

    data = StockData(ticker="000000", name="테스트전자", market="KR", currency="KRW")
    data.price_history = hist
    data.price = float(close.iloc[-1])
    data.change_1m, data.change_3m, data.change_1y = 3.2, 8.5, 21.0
    data.ma20, data.ma60 = float(close.iloc[-20:].mean()), float(close.iloc[-60:].mean())
    data.high_52w, data.low_52w = float(close.max()), float(close.min())
    data.market_cap = 350_000_000_000_000
    data.per, data.pbr, data.eps = 12.5, 1.3, 8500.0
    data.dividend_yield = 2.1
    data.sector = "반도체"
    data.consensus_target, data.consensus_high, data.consensus_low = 120000.0, 150000.0, 90000.0
    data.consensus_rating, data.analyst_count = "매수", 12
    data.broker_reports = [
        {"title": "테스트전자 목표주가 15만원으로 상향 - OO증권", "publisher": "OO증권", "date": "2026-07-14"},
        {"title": "테스트전자, HBM 수혜 지속 전망 - XX투자증권", "publisher": "XX투자증권", "date": "2026-07-13"},
    ]
    data.news = [
        {"title": "테스트전자, 2분기 사상 최대 실적", "publisher": "연합뉴스", "date": "2026-07-15"},
    ]
    data.financials = {
        "revenue": {"2022": 3.0e14, "2023": 2.6e14, "2024": 3.1e14},
        "operating_income": {"2022": 4.3e13, "2023": 6.5e12, "2024": 3.5e13},
        "net_income": {"2022": 5.5e13, "2023": 1.5e13, "2024": 3.4e13},
        "equity": {"2022": 3.5e14, "2023": 3.6e14, "2024": 4.0e14},
    }
    return data


def main() -> None:
    print("스모크 테스트 시작 (오프라인)...")
    data = _mock_data()

    print("  · 차트 생성...")
    chart_paths = charts.build_charts(data)
    assert "price" in chart_paths, "주가 차트 생성 실패"
    assert "financial" in chart_paths, "재무 차트 생성 실패"
    print(f"    차트 OK ({len(chart_paths)}개)")

    report = Report(
        data=data,
        fundamental=AnalysisSection(
            title="재무 분석", summary="매출과 이익이 회복 국면에 진입했습니다.",
            body="2023년 부진했던 영업이익이 2024년 뚜렷하게 반등했습니다.\n\n자본 대비 수익성도 개선되는 추세입니다.",
            bullets=["매출 회복", "영업이익 반등", "안정적 자본"]),
        market=AnalysisSection(
            title="시황·주가 분석", summary="상승 추세가 유지되고 있습니다.",
            body="주가는 60일선 위에서 완만한 상승세를 보이고 있습니다.",
            bullets=["60일선 상회", "3개월 +8.5%"]),
        valuation=Valuation(
            opinion="매수", target_price=float(data.price) * 1.2,
            upside_pct=20.0, buy_price=float(data.price) * 0.99, stop_loss=float(data.price) * 0.91,
            rationale="실적 반등과 밸류에이션 매력을 고려할 때 상승 여력이 있습니다.",
            risks=["업황 둔화", "환율 변동", "경쟁 심화"]),
        thesis="테스트전자는 실적 저점을 통과하며 이익 개선이 가시화되고 있습니다. 현재 밸류에이션은 과거 평균 대비 낮은 수준으로, 중기 관점의 매수 접근이 유효합니다.",
        generated_at=date.today(),
        chart_paths=chart_paths,
    )

    print("  · HTML/PDF 렌더...")
    path = render_report(report)
    assert path.exists(), "보고서 파일이 생성되지 않았습니다."
    print(f"\n✅ 스모크 테스트 통과 → {path}")


if __name__ == "__main__":
    main()
