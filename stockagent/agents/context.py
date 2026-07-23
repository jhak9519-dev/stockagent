"""수집한 StockData 를 Claude/Gemini 프롬프트용 텍스트로 정리하는 헬퍼."""
from __future__ import annotations

from typing import Optional

from ..models import StockData

# 매수 희망 구간 폭 (현재 기준 ±2%)
BUY_ZONE_PCT = 0.02


# ---------------------------------------------------------------------------
# 사람이 읽기 쉬운 숫자 포맷
# ---------------------------------------------------------------------------
def human_price(v: Optional[float], market: str) -> str:
    """현재가/매수가 등 주가 표기.  KR: 1,234,000원 / US: $123.45"""
    if v is None:
        return "N/A"
    return f"${v:,.2f}" if market == "US" else f"{v:,.0f}원"


def human_marcap(v: Optional[float], market: str) -> str:
    """시가총액을 조/억 단위로 축약.  예: 1,543조원 / 2.86조 달러 / 8,938억 달러"""
    if v is None:
        return "N/A"
    unit_won = "달러" if market == "US" else "원"
    if v >= 1e12:
        return f"{v / 1e12:,.2f}조 {unit_won}".replace(" 원", "원")
    if v >= 1e8:
        return f"{v / 1e8:,.0f}억 {unit_won}".replace(" 원", "원")
    return human_price(v, market)


def buy_zone(buy: Optional[float], market: str, pct: float = BUY_ZONE_PCT) -> Optional[tuple[float, float]]:
    """매수 희망가 중심값 → (하단, 상단) ±pct 구간."""
    if buy is None:
        return None
    nd = 2 if market == "US" else 0
    return round(buy * (1 - pct), nd), round(buy * (1 + pct), nd)


def overheat_flag(data: StockData) -> Optional[str]:
    """단기 과열(급등 후 고점 인접) 신호면 경고 문구, 아니면 None.

    기준: 3개월 수익률 +50% 초과 & 현재가가 52주 최고가의 90% 이상.
    점수 로직은 그대로 두되, 리포트·카톡에 '주의 표시'만 붙이기 위한 판단.
    """
    try:
        if (data.change_3m and data.change_3m > 50 and data.price and data.high_52w
                and data.price / data.high_52w > 0.90):
            return (f"단기 과열 주의: 3개월 {data.change_3m:+.1f}% 급등 후 "
                    f"52주 고점의 {data.price / data.high_52w * 100:.0f}% 수준")
    except Exception:
        pass
    return None


def trade_zone(data: StockData) -> tuple[Optional[float], Optional[float], Optional[float], str]:
    """지지선(이동평균) 기반 매수 희망 구간과 손절가: (하단, 상단, 손절, 근거설명).

    이전 방식(min(현재가, 20일선) ±2%)은 조정 중엔 사실상 '현재가 매수'가 되는 문제가 있어,
    지지선 기반으로 재설계 (2026-07-16, 사용자 요청):
    - 상승 추세(현재가 > 20일선): 상단=20일선(눌림목), 하단=60일선(최대 -10% 제한).
      상단은 현재가 -0.5% 이하로 강제해 '현재가 추격 매수'를 방지.
    - 조정 중(현재가 ≤ 20일선): 현재가 -1% ~ -7% 분할 매수 구간(60일선이 구간 안에 있으면 하단으로).
    - 손절가 = 구간 하단 -5% (지지 이탈 확정 시 기계적 손절).
    """
    price, ma20, ma60 = data.price, data.ma20, data.ma60
    if not price:
        return None, None, None, ""
    nd = 2 if data.market == "US" else 0

    if ma20 and price > ma20:
        hi = min(ma20, price * 0.995)
        lo = ma60 if (ma60 and ma60 < hi) else hi * 0.94
        lo = max(lo, price * 0.90)
        basis = "20일선 눌림목 상단 · 60일선 지지 하단"
    else:
        hi = price * 0.99
        lo = ma60 if (ma60 and price * 0.93 <= ma60 < hi) else price * 0.93
        basis = "조정 구간 분할 매수(60일선 지지 확인)"

    if lo >= hi:
        lo = hi * 0.96
    # 손절폭: 종목 변동성(ATR)에 연동 (2026-07-23, AI 리뷰 #7).
    #  고변동주에 일률 -5%면 정상 노이즈에도 손절되므로, ATR14 기반으로 -5%~-12% 범위 조정.
    stop = lo * (1 - _stop_pct(data))
    return round(lo, nd), round(hi, nd), round(stop, nd), basis


def _stop_pct(data: StockData) -> float:
    """손절 폭(비율). ATR(14)/현재가 × 2를 5%~12%로 클램프. 계산 불가 시 기본 5%."""
    try:
        h = data.price_history
        if h is None or getattr(h, "empty", True) or len(h) < 15:
            return 0.05
        import pandas as pd
        hi_s, lo_s = h["High"], h["Low"]
        prev_close = h["Close"].shift(1)
        tr = pd.concat([hi_s - lo_s, (hi_s - prev_close).abs(),
                        (lo_s - prev_close).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]
        if not atr or not data.price:
            return 0.05
        return min(max(atr / data.price * 2, 0.05), 0.12)
    except Exception:
        return 0.05


def trade_strategy(data: StockData) -> str:
    """추세 강도에 따라 매매 전략 문구를 '규칙 기반'으로 생성 (AI 편향 방지, 2026-07-21).

    모든 종목에 '눌림목 분할매수'를 반복하던 문제를 없애기 위해, 종목의 추세 강도(0~10)로
    전략 성격을 나눈다. 확신이 낮은 구간(4~6)은 긍정/부정 시나리오로 나눠 안내한다.
    """
    lo, hi, stop, _ = trade_zone(data)
    if lo is None:
        return ""
    m = data.market
    zone = f"{human_price(lo, m)} ~ {human_price(hi, m)}"
    stop_txt = human_price(stop, m)
    score = (data.technicals or {}).get("trend_score")

    head = f"매수 희망 구간 {zone}, 손절가 {stop_txt}(구간 하단 −5%). "
    if score is None:
        body = ("기술적 데이터가 부족하므로 밸류에이션과 실적 흐름을 우선 기준으로 삼고, "
                "구간 진입 시에도 한 번에 매수하기보다 나눠서 접근하는 것이 안전합니다.")
    elif score >= 7:
        body = (f"추세 강도 {score}/10으로 **상승 추세가 견조**합니다. 추세추종 관점에서 "
                "조정으로 매수 구간에 진입할 때 비중을 싣되, 단기 과열(볼린저 상단·RSI 70 이상) 국면에서는 "
                "신규 진입을 미루는 전략이 유효합니다.")
    elif score >= 4:
        body = (f"추세 강도 {score}/10으로 **방향성이 뚜렷하지 않습니다**. 확정 매수보다 시나리오로 나눠 대응하세요. "
                "① 긍정 시나리오(지지선 확인·거래량 동반 반등): 매수 구간 하단부터 분할 진입. "
                "② 부정 시나리오(지지 이탈·거래량 없는 반등): 진입을 보류하고 손절선 아래에서는 관망. "
                "두 시나리오의 확률을 비슷하게 보고, 신호가 확인되는 쪽으로만 대응하는 것이 바람직합니다.")
    else:
        body = (f"추세 강도 {score}/10으로 **하락·약세 신호가 우세**합니다. 지금은 신규 매수보다 "
                "관망과 리스크 관리가 우선입니다. 바닥 확인(거래량 급증 반등, 이동평균선 회복) 전까지는 "
                "관찰만 하고, 진입하더라도 소량으로 제한하는 보수적 접근이 안전합니다.")
    return head + body


def trade_lines(data: StockData) -> tuple[Optional[float], Optional[float]]:
    """(매수 구간 중심값, 손절가) — trade_zone의 축약형(하위 호환용)."""
    lo, hi, stop, _ = trade_zone(data)
    if lo is None:
        return None, None
    nd = 2 if data.market == "US" else 0
    return round((lo + hi) / 2, nd), stop


# ---------------------------------------------------------------------------
def _fmt(v, unit="", nd=2):
    if v is None:
        return "N/A"
    if isinstance(v, float):
        return f"{v:,.{nd}f}{unit}"
    return f"{v:,}{unit}" if isinstance(v, (int,)) else f"{v}{unit}"


def _fin_table(financials: dict[str, dict[str, float]]) -> str:
    if not financials:
        return "  (재무 데이터 없음)"
    labels = {
        "revenue": "매출액", "operating_income": "영업이익", "net_income": "당기순이익",
        "assets": "자산총계", "liabilities": "부채총계", "equity": "자본총계",
        "op_cash_flow": "영업활동현금흐름", "free_cash_flow": "잉여현금흐름(FCF)",
    }
    years = sorted({y for m in financials.values() for y in m}, reverse=True)[:3]
    lines = ["  연도: " + " | ".join(years)]
    for key, label in labels.items():
        if key not in financials:
            continue
        vals = [_fmt(financials[key].get(y), nd=0) for y in years]
        lines.append(f"  {label}: " + " | ".join(vals))
    return "\n".join(lines)


def data_brief(data: StockData) -> str:
    """분석 에이전트 프롬프트에 넣을 표준 데이터 브리핑."""
    cur = data.currency
    return f"""[종목 개요]
  종목명/코드: {data.name} ({data.ticker}) / 시장: {data.market}
  업종: {data.sector or 'N/A'} / {data.industry or 'N/A'}
  현재가: {human_price(data.price, data.market)}
  시가총액: {human_marcap(data.market_cap, data.market)}

[주가 흐름]
  1개월: {_fmt(data.change_1m, '%')} / 3개월: {_fmt(data.change_3m, '%')} / 1년: {_fmt(data.change_1y, '%')}
  20일선: {_fmt(data.ma20)} / 60일선: {_fmt(data.ma60)}
  52주 최고/최저: {_fmt(data.high_52w)} / {_fmt(data.low_52w)}{_flags(data)}

[밸류에이션 지표]
  PER: {_fmt(data.per)} / PBR: {_fmt(data.pbr)} / EPS: {_fmt(data.eps)} / BPS: {_fmt(data.bps)} / 배당수익률: {_fmt(data.dividend_yield, '%')}
  ※ PER/PBR/시가총액은 최근 시세 기준, 재무제표는 연간 결산 기준이라 시점이 달라
    서로 역산하면 소폭(수 % 이내) 차이가 날 수 있습니다. 이를 오류로 서술하지 마세요.

[기술적 지표 (차트 분석)]
{_technical(data)}

[수급 동향 (투자자별 매매)]
{_flows(data)}

[시장 컨센서스 (애널리스트)]
{_consensus(data)}

[다른 증권사 리포트·목표주가 언급 (뉴스 검색 결과)]
{_brokers(data)}

[매매 전략 참고 (기술적 기준 · 리포트에 함께 표기됨)]
{_trade(data)}

[재무제표 (최근 3개년, 통화 {cur})]
{_fin_table(data.financials)}

[최근 뉴스 헤드라인]
{_news(data)}"""


def _flags(data: StockData) -> str:
    """실적 발표 예정일·과열 신호 등 특이사항 라인 (없으면 빈 문자열)."""
    lines = []
    if data.earnings_date:
        lines.append(f"  다음 실적 발표(예정)일: {data.earnings_date} — 이벤트 전후 변동성에 유의해 서술하세요")
    oh = overheat_flag(data)
    if oh:
        lines.append(f"  ⚠ {oh} — 이 과열 리스크를 분석과 전략에 반드시 반영하세요")
    return ("\n" + "\n".join(lines)) if lines else ""


def _technical(data: StockData) -> str:
    t = data.technicals or {}
    sig = t.get("signals") or []
    if not sig:
        return "  (지표 계산 불가 — 시세 데이터 부족)"
    return "\n".join(f"  - {s}" for s in sig)


def _flows(data: StockData) -> str:
    f = data.trading_flows or {}
    if not f:
        return "  (수급 데이터 없음)"
    if data.market == "KR":
        lines = []
        if f.get("individual") is not None:
            lines.append(f"  {f.get('period', '')} 순매수({f.get('unit', '')}):"
                         f" 개인 {f.get('individual'):+,.1f} / 외국인 {f.get('foreign'):+,.1f}"
                         f" / 기관 {f.get('institution'):+,.1f}")
        if f.get("foreign_hold_ratio"):
            lines.append(f"  외국인 보유율: {f['foreign_hold_ratio']}")
        p = f.get("pension") or {}
        if p.get("direction"):
            amt = f" {p['amount_100m']:,.0f}억원" if p.get("amount_100m") else ""
            lines.append(f"  연기금: {p['direction']} 상위 목록 포착{amt}"
                         f" (기준일 {p.get('date', '-')}) — 수급 해석에 반영하세요")
        elif p.get("date"):
            lines.append(f"  연기금: 매매 상위 목록에 없음(기준일 {p['date']}) — 대규모 순매매는 없었던 것으로 추정")
        daily = f.get("daily") or []
        if daily:
            def _c(r):
                return f"{r['change']:+.1f}%" if r.get("change") is not None else "-"
            lines.append("  일자별(종가·등락·순매수억원, 최근순): "
                         + " / ".join(f"{r['date']} {_c(r)} 개{r['individual']:+.0f}·외{r['foreign']:+.0f}·기{r['institution']:+.0f}"
                                      for r in daily[:5]))
        return "\n".join(lines) if lines else "  (수급 데이터 없음)"
    parts = []
    if f.get("institution_hold") is not None:
        parts.append(f"기관 보유 {f['institution_hold']}%")
    if f.get("insider_hold") is not None:
        parts.append(f"내부자 보유 {f['insider_hold']}%")
    if f.get("short_pct_float") is not None:
        parts.append(f"공매도 비중(유통주식) {f['short_pct_float']}%")
    if f.get("short_ratio") is not None:
        parts.append(f"공매도 커버 {f['short_ratio']}일")
    out = "  " + " / ".join(parts) if parts else "  (수급 지표 없음)"
    daily = f.get("daily") or []
    if daily:
        def _c(r):
            return f"{r['change']:+.1f}%" if r.get("change") is not None else "-"
        out += ("\n  일별(종가·등락, 최근순): "
                + " / ".join(f"{r['date']} ${r['close']:,.2f} {_c(r)}" for r in daily[:5]))
    return out


def _trade(data: StockData) -> str:
    lo, hi, stop, basis = trade_zone(data)
    if lo is None:
        return "  (시세 데이터 부족)"
    return (f"  매수 희망 구간 {human_price(lo, data.market)} ~ {human_price(hi, data.market)} ({basis})"
            f" / 손절가 {human_price(stop, data.market)} (구간 하단 -5%)."
            " 이 구간·손절가는 기술적 참고선입니다. **매매 타이밍 전략은 별도 규칙으로 자동 생성되므로,"
            " rationale 에서는 반복하지 말고 밸류에이션·투자의견 근거에 집중하세요.**")


def _consensus(data: StockData) -> str:
    if not (data.consensus_target or data.consensus_rating):
        return "  (해당 없음 / 무료 데이터 미제공 — 아래 증권사 리포트 뉴스를 참고해 종합하세요)"
    parts = []
    if data.consensus_target:
        rng = ""
        if data.consensus_high and data.consensus_low:
            rng = f" (최저 {human_price(data.consensus_low, data.market)} ~ 최고 {human_price(data.consensus_high, data.market)})"
        parts.append(f"평균 목표주가 {human_price(data.consensus_target, data.market)}{rng}")
    if data.consensus_rating:
        parts.append(f"투자의견 {data.consensus_rating}")
    if data.analyst_count:
        parts.append(f"분석기관 {int(data.analyst_count)}곳")
    return "  " + " / ".join(parts)


def _brokers(data: StockData) -> str:
    if not data.broker_reports:
        return "  (검색 결과 없음)"
    lines = []
    for n in data.broker_reports[:5]:
        date = f"[{n.get('date')}] " if n.get("date") else ""
        pub = f" ({n.get('publisher')})" if n.get("publisher") else ""
        lines.append(f"  - {date}{n.get('title', '')}{pub}")
    return "\n".join(lines)


def _news(data: StockData) -> str:
    if not data.news:
        return "  (없음)"
    lines = []
    for n in data.news[:5]:
        date = f"[{n.get('date')}] " if n.get("date") else ""
        pub = f" ({n.get('publisher')})" if n.get("publisher") else ""
        lines.append(f"  - {date}{n.get('title', '')}{pub}")
    return "\n".join(lines)
