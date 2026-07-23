"""시세 데이터 공통 계산 유틸 (한국/미국 공용)."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def pct_change(series: pd.Series, periods: int) -> Optional[float]:
    """periods 거래일 전 대비 등락률(%). 데이터 부족 시 None."""
    if series is None or len(series) <= periods:
        return None
    now = series.iloc[-1]
    past = series.iloc[-periods - 1]
    if past == 0 or pd.isna(past) or pd.isna(now):
        return None
    return round((now / past - 1) * 100, 2)


def enrich_price_metrics(data, close: pd.Series, volume: Optional[pd.Series] = None) -> None:
    """StockData 객체에 이동평균/등락률/52주 고저 등을 채워 넣습니다.

    거래일 기준: 1개월≈21일, 3개월≈63일, 1년≈252일.
    """
    close = close.dropna()
    if close.empty:
        data.warnings.append("시세 데이터가 비어 있습니다.")
        return

    data.price = round(float(close.iloc[-1]), 2)
    data.change_1m = pct_change(close, 21)
    data.change_3m = pct_change(close, 63)
    data.change_1y = pct_change(close, 252)

    if len(close) >= 20:
        data.ma20 = round(float(close.iloc[-20:].mean()), 2)
    if len(close) >= 60:
        data.ma60 = round(float(close.iloc[-60:].mean()), 2)

    window_52w = close.iloc[-252:] if len(close) >= 252 else close
    data.high_52w = round(float(window_52w.max()), 2)
    data.low_52w = round(float(window_52w.min()), 2)

    if volume is not None and not volume.dropna().empty:
        recent_vol = volume.dropna().iloc[-20:]
        if not recent_vol.empty:
            data.volume_avg = round(float(recent_vol.mean()), 0)


def safe_ratio(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """a/b 를 안전하게 계산 (0 나눗셈/None 방지)."""
    if a is None or b is None:
        return None
    try:
        if b == 0 or np.isnan(a) or np.isnan(b):
            return None
        return round(float(a) / float(b), 2)
    except (TypeError, ValueError):
        return None
