"""The agronomic models are the part that must be provably correct -- they are
published formulas with defined thresholds, so they get exact-value tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import risk_models
from app.services.weather import HourPoint


def build_day(day_offset: int, temp: float, humid_hours: int, humidity_high: float = 95.0):
    """One synthetic day: `humid_hours` hours at high RH, the rest dry."""
    base = datetime(2026, 1, 10, tzinfo=timezone.utc) + timedelta(days=day_offset)
    points = []
    for hour in range(24):
        points.append(
            HourPoint(
                ts=base + timedelta(hours=hour),
                temp_c=temp,
                humidity=humidity_high if hour < humid_hours else 55.0,
                rainfall_mm=0.0,
            )
        )
    return points


class TestSmithPeriod:
    def test_two_qualifying_days_fires(self):
        points = build_day(0, 14.0, 12) + build_day(1, 14.0, 12)
        out = risk_models.smith_period(risk_models.summarise_days(points))
        assert out.triggered is True
        assert out.score == 1.0
        assert out.detail["longest_run_days"] == 2
        assert len(out.detail["periods"]) == 1

    def test_one_qualifying_day_is_a_warning_not_a_period(self):
        points = build_day(0, 14.0, 12) + build_day(1, 14.0, 4)
        out = risk_models.smith_period(risk_models.summarise_days(points))
        assert out.triggered is False
        assert out.score == 0.5
        assert out.detail["longest_run_days"] == 1

    def test_cold_days_never_qualify_however_humid(self):
        points = build_day(0, 8.0, 24) + build_day(1, 8.0, 24)
        out = risk_models.smith_period(risk_models.summarise_days(points))
        assert out.triggered is False
        assert out.detail["longest_run_days"] == 0

    def test_ten_humid_hours_is_below_the_eleven_hour_threshold(self):
        points = build_day(0, 15.0, 10) + build_day(1, 15.0, 10)
        out = risk_models.smith_period(risk_models.summarise_days(points))
        assert out.triggered is False


class TestBeaumontPeriod:
    def test_forty_six_consecutive_hours_fires(self):
        points = []
        base = datetime(2026, 1, 10, tzinfo=timezone.utc)
        for hour in range(50):
            points.append(HourPoint(ts=base + timedelta(hours=hour), temp_c=15.0, humidity=80.0, rainfall_mm=0.0))
        out = risk_models.beaumont_period(points)
        assert out.triggered is True
        assert out.detail["longest_run_hours"] == 50

    def test_a_dry_hour_breaks_the_run(self):
        points = []
        base = datetime(2026, 1, 10, tzinfo=timezone.utc)
        for hour in range(50):
            humidity = 60.0 if hour == 25 else 80.0
            points.append(HourPoint(ts=base + timedelta(hours=hour), temp_c=15.0, humidity=humidity, rainfall_mm=0.0))
        out = risk_models.beaumont_period(points)
        assert out.triggered is False
        assert out.detail["longest_run_hours"] == 25


class TestTomcastDSV:
    def test_severity_lookup_matches_the_published_table(self):
        # 21-25 C band, cut points [3, 6, 13, 21]
        days = risk_models.summarise_days(build_day(0, 23.0, 14))
        assert risk_models._dsv_for_day(days[0]) == 3

    def test_no_wetness_scores_zero(self):
        days = risk_models.summarise_days(build_day(0, 23.0, 0))
        assert risk_models._dsv_for_day(days[0]) == 0

    def test_accumulation_reaches_the_spray_threshold(self):
        points = []
        for d in range(6):  # 6 days x 3 DSV = 18, above the 15 threshold
            points += build_day(d, 23.0, 14)
        out = risk_models.tomcast_dsv(risk_models.summarise_days(points))
        assert out.detail["total_dsv"] == 18
        assert out.triggered is True

    def test_cold_weather_produces_no_severity_values(self):
        points = build_day(0, 8.0, 20)
        out = risk_models.tomcast_dsv(risk_models.summarise_days(points))
        assert out.detail["total_dsv"] == 0


class TestDegreeDays:
    def test_accumulation_uses_the_base_temperature(self):
        points = build_day(0, 20.0, 0)  # flat 20 C -> 10 DD above a 10 C base
        days = risk_models.summarise_days(points)
        out = risk_models.degree_days(days, risk_models.PEST_MODELS["potato_tuber_moth"])
        assert out.detail["accumulated_dd"] == 10.0

    def test_below_base_temperature_accumulates_nothing(self):
        days = risk_models.summarise_days(build_day(0, 6.0, 0))
        out = risk_models.degree_days(days, risk_models.PEST_MODELS["potato_tuber_moth"])
        assert out.detail["accumulated_dd"] == 0.0

    def test_a_generation_completes_at_the_configured_threshold(self):
        points = []
        for d in range(36):  # 36 days x 10 DD = 360 = one generation
            points += build_day(d, 20.0, 0)
        days = risk_models.summarise_days(points)
        out = risk_models.degree_days(days, risk_models.PEST_MODELS["potato_tuber_moth"])
        assert out.detail["generations"] == 1.0
        assert out.triggered is True
