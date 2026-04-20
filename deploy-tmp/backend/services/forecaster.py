"""
Billing forecast with anomaly detection.

Uses linear regression (with optional seasonal adjustment for 12+ months)
to forecast the next 3 months of expected billing.  Pure Python — no
heavy ML libraries required.
"""

from __future__ import annotations

import math
from datetime import datetime


def _parse_month(m: str) -> datetime:
    """Parse 'YYYY-MM' or 'YYYY-MM-DD' into a datetime."""
    return datetime.strptime(m[:7], "%Y-%m")


def _add_months(dt: datetime, n: int) -> str:
    """Return 'YYYY-MM' string for dt + n months."""
    month = dt.month - 1 + n
    year = dt.year + month // 12
    month = month % 12 + 1
    return f"{year:04d}-{month:02d}"


def _linear_regression(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Simple OLS: returns (slope, intercept)."""
    n = len(xs)
    if n < 2:
        return 0.0, ys[0] if ys else 0.0
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    ss_xy = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    ss_xx = sum((x - x_mean) ** 2 for x in xs)
    if ss_xx == 0:
        return 0.0, y_mean
    slope = ss_xy / ss_xx
    intercept = y_mean - slope * x_mean
    return slope, intercept


def _seasonal_factors(ys: list[float], period: int = 12) -> list[float]:
    """Compute multiplicative seasonal factors over the given period."""
    n = len(ys)
    if n < period:
        return [1.0] * period
    # detrend: compute moving average for each position
    factors = [0.0] * period
    counts = [0] * period
    # Simple average for each month position
    for i, y in enumerate(ys):
        pos = i % period
        factors[pos] += y
        counts[pos] += 1
    overall_mean = sum(ys) / n
    if overall_mean == 0:
        return [1.0] * period
    for i in range(period):
        if counts[i] > 0:
            factors[i] = (factors[i] / counts[i]) / overall_mean
        else:
            factors[i] = 1.0
    return factors


def forecast_billing(timeline: list[dict]) -> dict:
    """
    Forecast next 3 months of expected billing from monthly timeline data.

    Parameters
    ----------
    timeline : list of dict
        Each dict has keys: month (str), total_paid (float), total_claims (int).
        Must be sorted chronologically.

    Returns
    -------
    dict with:
        forecasted_months: [{month, predicted_paid, lower_bound, upper_bound}]
        last_actual: float
        spike_detected: bool
        spike_magnitude: float  (ratio of last actual vs upper bound, 0 if no spike)
    """
    if not timeline or len(timeline) < 3:
        return {
            "forecasted_months": [],
            "last_actual": 0.0,
            "spike_detected": False,
            "spike_magnitude": 0.0,
        }

    # Extract paid values and time indices
    paid = [float(row.get("total_paid", 0) or 0) for row in timeline]
    n = len(paid)
    xs = list(range(n))

    # Linear regression on deseasonalised data
    use_seasonal = n >= 12
    if use_seasonal:
        factors = _seasonal_factors(paid, 12)
        # Deseasonalise
        deseasonalised = []
        for i, y in enumerate(paid):
            f = factors[i % 12]
            deseasonalised.append(y / f if f != 0 else y)
        slope, intercept = _linear_regression([float(x) for x in xs], deseasonalised)
    else:
        factors = [1.0] * 12
        slope, intercept = _linear_regression([float(x) for x in xs], paid)

    # Compute residuals
    residuals = []
    for i in range(n):
        predicted = slope * i + intercept
        if use_seasonal:
            predicted *= factors[i % 12]
        residuals.append(paid[i] - predicted)

    std_residual = 0.0
    if len(residuals) >= 2:
        mean_res = sum(residuals) / len(residuals)
        var = sum((r - mean_res) ** 2 for r in residuals) / (len(residuals) - 1)
        std_residual = math.sqrt(var)

    # Forecast next 3 months
    last_month_dt = _parse_month(timeline[-1]["month"])
    forecasted = []
    for step in range(1, 4):
        future_idx = n - 1 + step
        pred = slope * future_idx + intercept
        if use_seasonal:
            # Figure out which calendar month this is
            future_month_str = _add_months(last_month_dt, step)
            future_month_num = int(future_month_str.split("-")[1])
            # seasonal factor index: align with first month of data
            first_month_num = _parse_month(timeline[0]["month"]).month
            factor_idx = (future_month_num - first_month_num) % 12
            pred *= factors[factor_idx]

        pred = max(pred, 0.0)
        lower = max(pred - 2 * std_residual, 0.0)
        upper = pred + 2 * std_residual

        forecasted.append({
            "month": _add_months(last_month_dt, step),
            "predicted_paid": round(pred, 2),
            "lower_bound": round(lower, 2),
            "upper_bound": round(upper, 2),
        })

    # Check if last actual month exceeds predicted upper bound by >50%
    # Compare last actual against what the model would have predicted for it
    last_pred = slope * (n - 1) + intercept
    if use_seasonal:
        last_month_num = last_month_dt.month
        first_month_num = _parse_month(timeline[0]["month"]).month
        factor_idx = (last_month_num - first_month_num) % 12
        last_pred *= factors[factor_idx]
    last_pred = max(last_pred, 0.0)
    last_upper = last_pred + 2 * std_residual

    last_actual = paid[-1]
    spike_detected = False
    spike_magnitude = 0.0
    if last_upper > 0:
        ratio = last_actual / last_upper
        if ratio > 1.5:
            spike_detected = True
            spike_magnitude = round(ratio, 2)

    return {
        "forecasted_months": forecasted,
        "last_actual": round(last_actual, 2),
        "spike_detected": spike_detected,
        "spike_magnitude": spike_magnitude,
    }
