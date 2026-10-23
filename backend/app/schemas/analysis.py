"""Pydantic models defining the API contract for wind forecast intelligence."""
from __future__ import annotations

from typing import Any, List, Optional
from pydantic import BaseModel, Field


class IntervalObservation(BaseModel):
    start_time: str = Field(..., description="UTC ISO timestamp of the half-hour delivery interval start")
    delivery_time: str = Field(..., description="London local HH:MM display time")
    settlement_period: Optional[int] = Field(None, description="Settlement period (1-48)")
    forecast_publish_time: Optional[str] = Field(None, description="UTC ISO timestamp of selected forecast publication")
    forecast_publish_time_display: Optional[str] = Field(None, description="Human-readable publication time")
    forecast_mw: Optional[float] = Field(None, description="Forecasted wind generation in MW")
    actual_mw: Optional[float] = Field(None, description="Actual wind generation outturn in MW")
    error_mw: Optional[float] = Field(None, description="Forecast error in MW (forecast - actual)")
    lead_time_hours: Optional[float] = Field(None, description="Forecast lead time in hours (delivery - publish)")
    status: str = Field(..., description="Matching status (e.g. Matched, Missing actual)")


class MetricsSummary(BaseModel):
    mae: Optional[float] = Field(None, description="Mean Absolute Error in MW")
    rmse: Optional[float] = Field(None, description="Root Mean Square Error in MW")
    bias: Optional[float] = Field(None, description="Mean Error / Bias in MW (positive = overforecast)")
    valid_count: int = Field(..., description="Count of paired half-hour intervals evaluated")
    mean_actual_mw: Optional[float] = Field(None, description="Mean actual generation across valid intervals in MW")
    mean_forecast_mw: Optional[float] = Field(None, description="Mean forecast generation across valid intervals in MW")
    nmae_percent: Optional[float] = Field(None, description="Normalized MAE as % of average actual generation")


class CoverageSummary(BaseModel):
    matched_intervals: int = Field(..., description="Number of intervals with both forecast and actual data")
    expected_intervals: int = Field(..., description="Expected intervals in day (48)")
    missing_actual_intervals: int = Field(..., description="Intervals missing actual outturn")
    missing_forecast_intervals: int = Field(..., description="Intervals missing eligible forecast")
    actual_intervals_available: int = Field(..., description="Total actual intervals available")
    eligible_forecast_intervals: int = Field(..., description="Total eligible forecast intervals available")


class RiskBufferSummary(BaseModel):
    p50_error_mw: Optional[float] = Field(None, description="Median forecast error in MW")
    p90_error_mw: Optional[float] = Field(None, description="90th percentile forecast error in MW")
    p95_error_mw: Optional[float] = Field(None, description="95th percentile forecast error in MW")
    p90_shortfall_mw: Optional[float] = Field(None, description="P90 generation deficit when forecast > actual in MW")
    recommended_buffer_mw: Optional[float] = Field(None, description="Recommended reserve buffer in MW")
    interpretation: str = Field(..., description="Actionable explanation for power traders/buyers")


class DiurnalSlot(BaseModel):
    period: int = Field(..., description="Settlement period (1 to 48)")
    delivery_time: str = Field(..., description="HH:MM interval start time")
    mae: Optional[float] = Field(None, description="Mean Absolute Error in MW for this period")
    bias: Optional[float] = Field(None, description="Mean forecast error / bias in MW")
    valid_count: int = Field(..., description="Observations count for this half hour")


class WindRegimeItem(BaseModel):
    regime: str = Field(..., description="Generation regime: Low (<5 GW), Medium (5-12 GW), High (>12 GW)")
    range_mw: str = Field(..., description="MW boundary definition")
    count: int = Field(..., description="Number of intervals in this regime")
    mae: Optional[float] = Field(None, description="MAE within this regime in MW")
    bias: Optional[float] = Field(None, description="Bias within this regime in MW")
    nmae_percent: Optional[float] = Field(None, description="Normalized MAE % within this regime")


class HorizonBucket(BaseModel):
    horizon_range: str = Field(..., description="Lead time window (e.g. 12-24h)")
    count: int = Field(..., description="Number of forecast vintages evaluated")
    mae: Optional[float] = Field(None, description="MAE in MW for this lead time")
    bias: Optional[float] = Field(None, description="Bias in MW for this lead time")


class ProvenanceSummary(BaseModel):
    sources: List[str] = Field(..., description="Elexon dataset streams utilized")
    retrieved_at: str = Field(..., description="Data retrieval timestamp (London time)")
    actual_records_retrieved: int = Field(..., description="Raw actual records ingested")
    forecast_records_retrieved: int = Field(..., description="Raw forecast records ingested")
    actual_wind_intervals: int = Field(..., description="Distinct wind delivery intervals found")
    eligible_forecast_intervals: int = Field(..., description="Forecast intervals before cutoff")
    matched_intervals: int = Field(..., description="Successfully paired intervals")
    actual_duplicate_rows: int = Field(..., description="Duplicate actual records handled")
    forecast_duplicate_rows: int = Field(..., description="Duplicate forecast records handled")
    forecast_rows_after_cutoff_excluded: int = Field(..., description="Forecasts filtered out due to cutoff")
    warnings: List[str] = Field(default_factory=list, description="Data quality or coverage warnings")
    cache_status: str = Field(default="live", description="Cache tier utilized: sqlite_persistent, memory, or live")
    cache_ttl_seconds: Optional[int] = Field(None, description="In-memory cache TTL")
    cache_bypassed: bool = Field(default=False, description="Whether cache was bypassed")


class DayAnalysisResponse(BaseModel):
    delivery_date: str = Field(..., description="Selected delivery date (YYYY-MM-DD)")
    timezone: str = Field("Europe/London", description="Business timezone")
    cutoff_time: str = Field(..., description="Decision cutoff time (HH:MM)")
    cutoff_datetime: str = Field(..., description="Absolute cutoff datetime in London time")
    expected_intervals: int = Field(48, description="Expected half-hour intervals")
    executive_summary: str = Field(..., description="Headline executive summary for procurement decisions")
    purchasing_guidance: str = Field(..., description="Actionable recommendation for covering forecast risk")
    observations: List[IntervalObservation] = Field(..., description="48 half-hour interval observations")
    metrics: MetricsSummary = Field(..., description="Headline accuracy metrics")
    coverage: CoverageSummary = Field(..., description="Coverage and completeness statistics")
    risk_buffer: RiskBufferSummary = Field(..., description="Quantified risk buffer and quantiles")
    diurnal_profile: List[DiurnalSlot] = Field(default_factory=list, description="48 settlement period diurnal error profile")
    wind_regimes: List[WindRegimeItem] = Field(default_factory=list, description="Accuracy stratified by wind generation level")
    horizon_analysis: List[HorizonBucket] = Field(default_factory=list, description="Error progression across forecast lead time")
    provenance: ProvenanceSummary = Field(..., description="Data audit and provenance details")


class DaySummaryItem(BaseModel):
    date: str = Field(..., description="YYYY-MM-DD")
    mae: Optional[float] = Field(None, description="Mean Absolute Error in MW")
    rmse: Optional[float] = Field(None, description="Root Mean Square Error in MW")
    bias: Optional[float] = Field(None, description="Bias in MW")
    nmae_percent: Optional[float] = Field(None, description="Normalized MAE %")
    mean_actual_mw: Optional[float] = Field(None, description="Average actual generation in MW")
    mean_forecast_mw: Optional[float] = Field(None, description="Average forecast generation in MW")
    valid_count: int = Field(..., description="Evaluated half-hour intervals")
    coverage_percent: float = Field(..., description="Percentage of 48 intervals matched")


class MonthAnalysisResponse(BaseModel):
    month: str = Field("2026-01", description="Evaluated month")
    cutoff_time: str = Field(..., description="Decision cutoff time")
    total_days: int = Field(31, description="Days in month")
    days_with_data: int = Field(..., description="Days with valid matched intervals")
    metrics: MetricsSummary = Field(..., description="Month-aggregate accuracy metrics")
    best_day: Optional[DaySummaryItem] = Field(None, description="Day with lowest MAE")
    worst_day: Optional[DaySummaryItem] = Field(None, description="Day with highest MAE")
    daily_summaries: List[DaySummaryItem] = Field(..., description="Per-day summary for all 31 days")
    diurnal_profile: List[DiurnalSlot] = Field(..., description="31-day aggregate 48-slot diurnal profile")
    wind_regimes: List[WindRegimeItem] = Field(..., description="31-day aggregate wind regime breakdown")
    risk_buffer: RiskBufferSummary = Field(..., description="Month-level risk buffer calculation")
    provenance: dict[str, Any] = Field(default_factory=dict, description="Audit metadata")
