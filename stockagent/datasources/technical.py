"""
기술적 지표 계산 (일목균형표·볼린저밴드·이동평균·RSI·MACD).

시세 OHLCV DataFrame으로부터 지표 값과 '사람이 읽는 신호 문구'를 만들어
StockData.technicals 에 담습니다. AI(시황 에이전트)가 이 신호를 근거로
차트 관점의 주가 전망을 서술하고, 리포트에는 지표 표로도 표시됩니다.

모든 계산은 pandas 만 사용(추가 의존성 없음), 실패해도 예외를 밖으로 내지 않습니다.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd


def _last(s: pd.Series) -> Optional[float]:
    s = s.dropna()
    return round(float(s.iloc[-1]), 2) if len(s) else None


def compute(data, hist: pd.DataFrame) -> None:
    """지표를 계산해 data.technicals(dict)에 저장. 데이터 부족 항목은 건너뜀."""
    try:
        close_col = "Close" if "Close" in hist.columns else hist.columns[-1]
        close = hist[close_col].dropna()
        high = hist["High"].dropna() if "High" in hist.columns else close
        low = hist["Low"].dropna() if "Low" in hist.columns else close
        if len(close) < 30:
            return
        price = float(close.iloc[-1])
        t: dict = {"table": [], "signals": []}

        # ── 이동평균 배열 ────────────────────────────────────────
        mas = {n: _last(close.rolling(n).mean()) for n in (5, 20, 60, 120) if len(close) >= n}
        if mas.get(5) and mas.get(20) and mas.get(60):
            if price > mas[5] > mas[20] > mas[60]:
                arr = "정배열(주가>5>20>60일선) — 전형적 상승 추세"
            elif price < mas[5] < mas[20] < mas[60]:
                arr = "역배열(주가<5<20<60일선) — 하락 추세"
            else:
                arr = "혼조 배열 — 추세 전환 구간 가능성"
            t["table"].append(("이동평균 배열", arr))
            t["signals"].append(f"이동평균: {arr}")
        t["ma"] = mas

        # ── 볼린저밴드 (20일, 2σ) ──────────────────────────────
        if len(close) >= 20:
            mid = close.rolling(20).mean()
            std = close.rolling(20).std()
            upper, lower = _last(mid + 2 * std), _last(mid - 2 * std)
            if upper and lower and upper > lower:
                pct_b = (price - lower) / (upper - lower)
                if pct_b >= 0.95:
                    pos = "상단 밴드 터치/돌파 — 단기 과열 신호"
                elif pct_b >= 0.8:
                    pos = "상단 밴드 근접 — 상승 탄력 강하나 과열 유의"
                elif pct_b <= 0.05:
                    pos = "하단 밴드 터치 — 과매도 신호"
                elif pct_b <= 0.2:
                    pos = "하단 밴드 근접 — 약세 속 반등 관찰 구간"
                else:
                    pos = "밴드 중간권 — 중립"
                t["bollinger"] = {"upper": upper, "lower": lower, "pct_b": round(pct_b, 2)}
                t["table"].append(("볼린저밴드(20,2σ)", f"%b {pct_b:.2f} · {pos}"))
                t["signals"].append(f"볼린저밴드: %b {pct_b:.2f}, {pos}")

        # ── 일목균형표 ──────────────────────────────────────────
        if len(close) >= 78:  # 52 + 26 선행 여유
            tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2
            kijun = (high.rolling(26).max() + low.rolling(26).min()) / 2
            span_a = ((tenkan + kijun) / 2).shift(26)
            span_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
            sa, sb = _last(span_a), _last(span_b)
            tk, kj = _last(tenkan), _last(kijun)
            if sa and sb and tk and kj:
                top, bot = max(sa, sb), min(sa, sb)
                if price > top:
                    cloud = "주가가 구름대 위 — 강세 구간"
                elif price < bot:
                    cloud = "주가가 구름대 아래 — 약세 구간"
                else:
                    cloud = "주가가 구름대 안 — 방향 탐색 구간"
                cross = "전환선>기준선(호전)" if tk > kj else "전환선<기준선(악화)" if tk < kj else "전환선=기준선"
                t["ichimoku"] = {"tenkan": tk, "kijun": kj, "span_a": sa, "span_b": sb}
                t["table"].append(("일목균형표", f"{cloud} · {cross}"))
                t["signals"].append(f"일목균형표: {cloud}, {cross}")

        # ── RSI(14, Wilder) ─────────────────────────────────────
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        rs = gain / loss.replace(0, pd.NA)
        rsi = _last(100 - 100 / (1 + rs))
        if rsi is not None:
            zone = "과열권(70↑)" if rsi >= 70 else "과매도권(30↓)" if rsi <= 30 else "중립권"
            t["rsi"] = rsi
            t["table"].append(("RSI(14)", f"{rsi:.1f} · {zone}"))
            t["signals"].append(f"RSI(14) {rsi:.1f} — {zone}")

        # ── MACD(12, 26, 9) ─────────────────────────────────────
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        m, s = _last(macd), _last(signal)
        if m is not None and s is not None:
            stat = "시그널 상회 — 상승 모멘텀" if m > s else "시그널 하회 — 하락 모멘텀"
            t["macd"] = {"macd": m, "signal": s}
            t["table"].append(("MACD(12,26,9)", stat))
            t["signals"].append(f"MACD: {stat}")

        # ── 추세 강도 점수 (신호 가중 종합, 0~10) ───────────────
        pts, total = 0.0, 0.0

        def _vote(weight: float, bullish: bool) -> None:
            nonlocal pts, total
            total += weight
            if bullish:
                pts += weight

        if mas.get(20):
            _vote(1, price > mas[20])
        if mas.get(60):
            _vote(1, price > mas[60])
        if mas.get(5) and mas.get(20) and mas.get(60):
            _vote(2, mas[5] > mas[20] > mas[60])          # 정배열
        if t.get("bollinger"):
            _vote(1, t["bollinger"]["pct_b"] >= 0.5)
        ich = t.get("ichimoku")
        if ich:
            _vote(2, price > max(ich["span_a"], ich["span_b"]))  # 구름 위
            _vote(1, ich["tenkan"] > ich["kijun"])
        if rsi is not None:
            _vote(1, 50 <= rsi < 70)                       # 건전한 상승 모멘텀 구간
        if t.get("macd"):
            _vote(1, t["macd"]["macd"] > t["macd"]["signal"])
        if total:
            score10 = round(pts / total * 10)
            t["trend_score"] = score10
            t["table"].insert(0, ("추세 강도", f"{score10}/10 (지표 신호 가중 종합)"))
            t["signals"].insert(0, f"추세 강도 종합 {score10}/10")

        # ── 지지·저항 레벨 (계산된 지표값을 현재가 기준으로 분류) ──
        cands: list[tuple[str, float]] = []
        for label, v in (("20일선", mas.get(20)), ("60일선", mas.get(60)), ("120일선", mas.get(120))):
            if v:
                cands.append((label, v))
        if t.get("bollinger"):
            cands += [("볼린저 상단", t["bollinger"]["upper"]), ("볼린저 하단", t["bollinger"]["lower"])]
        if ich:
            cands += [("일목 구름 상단", max(ich["span_a"], ich["span_b"])),
                      ("일목 구름 하단", min(ich["span_a"], ich["span_b"]))]
        if getattr(data, "high_52w", None):
            cands.append(("52주 최고", data.high_52w))
        if getattr(data, "low_52w", None):
            cands.append(("52주 최저", data.low_52w))
        t["levels"] = {
            "support": sorted([c for c in cands if c[1] < price], key=lambda x: -x[1])[:4],
            "resistance": sorted([c for c in cands if c[1] >= price], key=lambda x: x[1])[:4],
        }

        data.technicals = t
    except Exception as e:  # 지표 계산 실패는 리포트 생성을 막지 않음
        try:
            data.warnings.append(f"기술적 지표 계산 실패: {e}")
        except Exception:
            pass
