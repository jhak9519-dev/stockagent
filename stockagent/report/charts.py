"""
차트 생성 (matplotlib).

- 주가 차트: 종가 + 20일/60일 이동평균선
- 재무 차트: 최근 3개년 매출/영업이익/당기순이익 막대

이미지는 base64 data URI 문자열로 반환하여 HTML에 그대로 삽입합니다
(PDF 렌더 시 외부 파일 경로 문제를 피하기 위함).
"""
from __future__ import annotations

import base64
import io

import matplotlib

matplotlib.use("Agg")  # 화면 없이 이미지 파일만 생성
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt

from ..models import StockData

# 한글 폰트 설정 (Windows: 맑은 고딕 우선)
for _cand in ["Malgun Gothic", "AppleGothic", "NanumGothic", "Noto Sans CJK KR"]:
    if any(_cand in f.name for f in fm.fontManager.ttflist):
        matplotlib.rcParams["font.family"] = _cand
        break
matplotlib.rcParams["axes.unicode_minus"] = False  # 마이너스 기호 깨짐 방지

# 다크 테마 팔레트 (웹 다크 카드와 어울리도록). PDF에서도 어두운 차트 박스로 표시됨.
_ACCENT = "#7fb2e5"    # 밝은 파랑 (종가·밴드)
_ACCENT2 = "#ff8f86"   # 코랄 (20일선·매출)
_GREY = "#9aa5b5"      # 회색 (60일선·순이익)
_BG = "#141b24"        # 차트 배경 (웹 카드색과 동일)
_FG = "#e8edf5"        # 제목·범례 텍스트
_MUTED = "#8b95a7"     # 축 눈금
_GRID = "#2a3240"      # 그리드·테두리


def _style_dark(fig, ax, title: str) -> None:
    """차트를 다크 테마로 스타일 (배경·축·그리드·텍스트)."""
    fig.patch.set_facecolor(_BG)
    ax.set_facecolor(_BG)
    ax.set_title(title, fontsize=12, fontweight="bold", color=_FG)
    for s in ax.spines.values():
        s.set_color(_GRID)
    ax.tick_params(colors=_MUTED, labelsize=8)
    ax.grid(True, alpha=0.18, color=_GRID)
    leg = ax.get_legend()
    if leg:
        for t in leg.get_texts():
            t.set_color(_FG)


def _to_data_uri(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor=_BG)
    plt.close(fig)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def price_chart(data: StockData) -> str | None:
    hist = data.price_history
    if hist is None or getattr(hist, "empty", True):
        return None
    close_col = "Close" if "Close" in hist.columns else hist.columns[-1]
    close = hist[close_col].dropna()
    if close.empty:
        return None

    fig, ax = plt.subplots(figsize=(8, 3.2))
    # 볼린저밴드(20일, ±2σ) 음영 — 밴드 상/하단 대비 주가 위치를 시각화
    if len(close) >= 20:
        mid = close.rolling(20).mean()
        std = close.rolling(20).std()
        ax.fill_between(close.index, (mid - 2 * std).values, (mid + 2 * std).values,
                        color=_ACCENT, alpha=0.15, label="볼린저밴드(±2σ)")
    ax.plot(close.index, close.values, color=_ACCENT, linewidth=1.5, label="종가")
    if len(close) >= 20:
        ax.plot(close.index, close.rolling(20).mean(), color=_ACCENT2, linewidth=1.0, label="20일선")
    if len(close) >= 60:
        ax.plot(close.index, close.rolling(60).mean(), color=_GREY, linewidth=1.0, label="60일선")
    ax.legend(loc="upper left", fontsize=9, frameon=False)
    _style_dark(fig, ax, f"{data.name} 주가 추이")
    return _to_data_uri(fig)


def financial_chart(data: StockData) -> str | None:
    fin = data.financials
    if not fin:
        return None
    years = sorted({y for m in fin.values() for y in m})[-3:]
    if not years:
        return None

    series = {
        "매출액": [fin.get("revenue", {}).get(y) for y in years],
        "영업이익": [fin.get("operating_income", {}).get(y) for y in years],
        "당기순이익": [fin.get("net_income", {}).get(y) for y in years],
    }
    # 값이 전부 없는 항목 제거
    series = {k: v for k, v in series.items() if any(x is not None for x in v)}
    if not series:
        return None

    # 단위 자동 축약
    all_vals = [abs(x) for v in series.values() for x in v if x is not None]
    scale, unit = (1e12, "조") if max(all_vals) >= 1e12 else \
                  (1e8, "억") if max(all_vals) >= 1e8 else (1, "")

    fig, ax = plt.subplots(figsize=(8, 3.0))
    n = len(series)
    width = 0.8 / n
    colors = [_ACCENT, _ACCENT2, _GREY]
    for i, (label, vals) in enumerate(series.items()):
        xs = [j + (i - (n - 1) / 2) * width for j in range(len(years))]
        ys = [(x / scale) if x is not None else 0 for x in vals]
        ax.bar(xs, ys, width=width, label=label, color=colors[i % len(colors)])
    ax.set_xticks(range(len(years)))
    ax.set_xticklabels(years)
    ax.legend(fontsize=9, frameon=False)
    _style_dark(fig, ax, f"주요 실적 추이 (단위: {unit}{data.currency})")
    return _to_data_uri(fig)


def build_charts(data: StockData) -> dict[str, str]:
    charts = {}
    p = price_chart(data)
    if p:
        charts["price"] = p
    f = financial_chart(data)
    if f:
        charts["financial"] = f
    return charts
