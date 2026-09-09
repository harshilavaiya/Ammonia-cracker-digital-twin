"""
Tests for the measurement ingestion and reconciliation layer.

Run with:  pytest -q
"""

import pytest

from model import MW_NH3, V_MOLAR_NORMAL, predict_conversion
from twin import (
    DEFAULT_CAMPAIGN,
    DEFAULT_PROCESS,
    conversion_from_outlet_ppmv,
    critical_activity,
    diagnose,
    estimate_activity,
    generate_campaign,
    read_csv,
    reconcile,
    write_csv,
)

FEED = DEFAULT_CAMPAIGN["nh3_feed_kg_h"]
TEMPERATURE = DEFAULT_CAMPAIGN["temperature_c"]
PRESSURE = DEFAULT_CAMPAIGN["pressure_bar"]
GHSV = DEFAULT_CAMPAIGN["design_ghsv_h"]
BED_VOLUME = FEED / MW_NH3 * V_MOLAR_NORMAL / GHSV

HEALTHY = dict(deactivation_time_constant_h=1e12, fouling_end_effectiveness=0.60)
DEACTIVATION_ONLY = dict(fouling_end_effectiveness=0.60)
FOULING_ONLY = dict(deactivation_time_constant_h=1e12)


def campaign(**overrides):
    return generate_campaign(**{**DEFAULT_CAMPAIGN, **DEFAULT_PROCESS, **overrides})


def reconciled(**overrides):
    return reconcile(campaign(**overrides), bed_volume_m3=BED_VOLUME, **DEFAULT_PROCESS)


# --- the sensor boundary --------------------------------------------------

def test_conversion_inverts_the_outlet_analyser():
    # 1636 ppmv corresponds to about 99.67 percent conversion.
    assert conversion_from_outlet_ppmv(1636) == pytest.approx(0.99673, abs=1e-5)
    assert conversion_from_outlet_ppmv(0) == 1.0


def test_activity_estimate_recovers_a_known_value():
    # Run the forward model at a known activity, then invert the result.
    for activity in (0.4, 0.7, 1.0):
        forward = predict_conversion(
            TEMPERATURE, PRESSURE, GHSV, "Ru/Al2O3", catalyst_activity=activity
        )
        recovered = estimate_activity(
            forward["conversion"], TEMPERATURE, PRESSURE, GHSV, "Ru/Al2O3"
        )
        assert recovered == pytest.approx(activity, rel=1e-6)


def test_activity_estimate_gives_up_at_the_equilibrium_ceiling():
    # A reactor sitting on the ceiling carries no information about how
    # active its catalyst is, and the estimator must say so rather than
    # inventing a number.
    ceiling = predict_conversion(650, 1, 2000, "Ru/Al2O3")["equilibrium_conversion"]
    assert estimate_activity(ceiling, 650, 1, 2000, "Ru/Al2O3") is None


# --- data handling --------------------------------------------------------

def test_campaign_is_reproducible():
    assert campaign() == campaign()


def test_campaign_length_matches_the_sampling():
    records = campaign(duration_h=100, sample_interval_h=5)
    assert len(records) == 21
    assert records[0]["time_h"] == 0
    assert records[-1]["time_h"] == 100


def test_csv_round_trips(tmp_path):
    path = tmp_path / "campaign.csv"
    original = campaign(duration_h=50)
    write_csv(original, path)
    assert read_csv(path) == original


def test_campaign_only_contains_measurable_quantities():
    # Conversion and activity are inferred, never measured, so they must not
    # appear in the data file.
    row = campaign(duration_h=10)[0]
    assert "conversion" not in " ".join(row).lower()
    assert "activity" not in " ".join(row).lower()


# --- reconciliation -------------------------------------------------------

def test_a_healthy_unit_agrees_with_the_model():
    rows = reconciled(**HEALTHY)
    residuals = [row["Conversion residual pp"] for row in rows]
    mean_residual = sum(residuals) / len(residuals)
    assert abs(mean_residual) < 0.01


def test_a_degrading_unit_diverges_from_the_model():
    rows = reconciled()
    early = sum(row["Conversion residual pp"] for row in rows[:100]) / 100
    late = sum(row["Conversion residual pp"] for row in rows[-100:]) / 100
    assert late < early
    assert late < -0.05


def test_measured_ammonia_rises_while_the_prediction_does_not():
    # The point of the demonstration: the reactor outlet worsens materially
    # while the model, told nothing, keeps predicting the design value.
    rows = reconciled()
    first, last = rows[0], rows[-1]
    assert last["nh3_outlet_ppmv"] > 1.4 * first["nh3_outlet_ppmv"]
    assert last["Predicted NH3 outlet ppmv"] == pytest.approx(
        first["Predicted NH3 outlet ppmv"], rel=0.05
    )


# --- diagnosis ------------------------------------------------------------

def test_a_healthy_unit_raises_nothing():
    result = diagnose(reconciled(**HEALTHY), **DEFAULT_PROCESS)
    assert result["Healthy"]
    assert result["Findings"] == []
    assert result["Estimated activity percent"] == pytest.approx(100, abs=3)


def test_deactivation_is_reported_as_a_catalyst_problem():
    result = diagnose(reconciled(**DEACTIVATION_ONLY), **DEFAULT_PROCESS)
    assert not result["Healthy"]
    assert any("catalyst" in finding for finding in result["Findings"])
    assert not any("recuperator" in finding for finding in result["Findings"])


def test_fouling_is_reported_as_a_heat_recovery_problem():
    result = diagnose(reconciled(**FOULING_ONLY), **DEFAULT_PROCESS)
    assert not result["Healthy"]
    assert any("recuperator" in finding for finding in result["Findings"])
    assert not any("catalyst" in finding for finding in result["Findings"])


def test_both_faults_together_raise_both_findings():
    result = diagnose(reconciled(), **DEFAULT_PROCESS)
    assert len(result["Findings"]) == 2


def test_estimated_activity_tracks_the_injected_decay():
    # The campaign decays with a 12000 h time constant, so after 4000 h the
    # true activity is exp(-1/3), about 71.7 percent. The estimator has to
    # recover that from noisy analyser readings.
    result = diagnose(reconciled(**DEACTIVATION_ONLY), **DEFAULT_PROCESS)
    assert result["Estimated activity percent"] == pytest.approx(71.7, abs=4)


def test_remaining_catalyst_life_is_projected():
    result = diagnose(reconciled(), **DEFAULT_PROCESS)
    assert result["Activity loss per 1000 h"] > 0
    assert result["Hours to catalyst replacement"] > 0
    assert result["Critical activity percent"] < result["Estimated activity percent"]


def test_no_replacement_projected_for_a_stable_catalyst():
    result = diagnose(reconciled(**HEALTHY), **DEFAULT_PROCESS)
    assert result["Hours to catalyst replacement"] is None


# --- the specification threshold ------------------------------------------

def test_critical_activity_is_the_point_where_the_product_fails():
    threshold = critical_activity(
        TEMPERATURE, PRESSURE, GHSV, nh3_feed_kg_h=FEED, **DEFAULT_PROCESS
    )
    assert 0 < threshold < 1

    from model import ammonia_cracker_model

    just_above = ammonia_cracker_model(
        nh3_feed_kg_h=FEED, temperature_c=TEMPERATURE, pressure_bar=PRESSURE,
        ghsv_h=GHSV, catalyst_activity_percent=(threshold + 0.01) * 100,
        **DEFAULT_PROCESS,
    )
    just_below = ammonia_cracker_model(
        nh3_feed_kg_h=FEED, temperature_c=TEMPERATURE, pressure_bar=PRESSURE,
        ghsv_h=GHSV, catalyst_activity_percent=(threshold - 0.01) * 100,
        **DEFAULT_PROCESS,
    )
    assert just_above["Meets ISO 14687"]
    assert not just_below["Meets ISO 14687"]


def test_no_threshold_when_the_train_cannot_meet_spec_anyway():
    # With a weak purification train the product fails at any activity, so
    # there is no catalyst threshold worth reporting.
    assert (
        critical_activity(
            TEMPERATURE, PRESSURE, GHSV,
            heat_recovery_percent=60, h2_recovery_percent=95, catalyst="Ru/Al2O3",
        )
        is None
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
