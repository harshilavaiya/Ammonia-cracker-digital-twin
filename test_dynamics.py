"""
Tests for the transient reactor model.

Run with:  pytest -q
"""

import pytest

from dynamics import simulate, summarise

# A purification train good enough to reach specification, so that the
# start-up tests have a specification to reach.
GOOD_TRAIN = dict(
    nh3_guard_removal_percent=99.9,
    psa_nh3_decontamination_factor=500,
    psa_n2_rejection_percent=99.95,
)

RUN = dict(
    duration_min=120,
    dt_s=5,
    heat_recovery_percent=60,
    h2_recovery_percent=95,
    pressure_bar=5,
    catalyst="Ru/Al2O3",
)


def run(**overrides):
    return simulate(**{**RUN, **GOOD_TRAIN, **overrides})


# --- integration sanity ---------------------------------------------------

def test_simulation_returns_the_expected_number_of_steps():
    history = run(duration_min=10, dt_s=5)
    assert len(history) == 10 * 60 // 5 + 1
    assert history[0]["Time min"] == 0
    assert history[-1]["Time min"] == pytest.approx(10)


def test_non_positive_timestep_is_rejected():
    with pytest.raises(ValueError):
        run(dt_s=0)


def test_non_positive_duration_is_rejected():
    with pytest.raises(ValueError):
        run(duration_min=0)


def test_results_are_insensitive_to_the_timestep():
    coarse = summarise(run(dt_s=10))
    fine = summarise(run(dt_s=1))
    assert coarse["Time to temperature min"] == pytest.approx(
        fine["Time to temperature min"], abs=1.0
    )


# --- start-up -------------------------------------------------------------

def test_cold_start_reaches_operating_temperature():
    result = summarise(run())
    assert result["Reached temperature"]
    assert result["Time to temperature min"] > 0


def test_startup_time_follows_the_ramp_limit():
    # From 20 C to 650 C at 10 C/min cannot beat 63 minutes.
    result = summarise(run(max_ramp_c_per_min=10))
    assert result["Time to temperature min"] == pytest.approx(63, abs=3)


def test_a_slower_ramp_takes_longer():
    slow = summarise(run(max_ramp_c_per_min=5, duration_min=180))
    fast = summarise(run(max_ramp_c_per_min=20))
    assert slow["Time to temperature min"] > fast["Time to temperature min"]


def test_the_setpoint_never_ramps_faster_than_the_limit():
    history = run(max_ramp_c_per_min=10, dt_s=5)
    for previous, current in zip(history, history[1:]):
        interval_min = current["Time min"] - previous["Time min"]
        rate = (current["Setpoint C"] - previous["Setpoint C"]) / interval_min
        assert rate <= 10 + 1e-9


def test_measured_temperature_tracks_the_ramp_without_running_away():
    # The limit constrains the setpoint, not the measurement, so the bed can
    # briefly climb faster while recovering from a load disturbance. What it
    # must not do is overshoot the setpoint or exceed the rate by much.
    history = run(max_ramp_c_per_min=10, dt_s=5)
    for previous, current in zip(history, history[1:]):
        interval_min = current["Time min"] - previous["Time min"]
        rate = (current["Temperature C"] - previous["Temperature C"]) / interval_min
        assert rate <= 15
        assert current["Temperature C"] <= current["Setpoint C"] + 10


def test_more_thermal_mass_starts_more_slowly():
    light = summarise(run(thermal_mass_kg=20, max_ramp_c_per_min=60))
    heavy = summarise(run(thermal_mass_kg=200, max_ramp_c_per_min=60))
    assert heavy["Time to temperature min"] > light["Time to temperature min"]


def test_an_undersized_burner_becomes_the_binding_constraint():
    generous = summarise(run(burner_capacity_kw=60, max_ramp_c_per_min=30))
    starved = summarise(run(burner_capacity_kw=16, max_ramp_c_per_min=30, duration_min=240))
    assert generous["Limited by"] == "Ramp rate"
    assert starved["Limited by"] == "Burner capacity"
    assert starved["Minutes at burner limit"] > 0


def test_a_burner_that_cannot_hold_temperature_never_gets_there():
    result = summarise(run(burner_capacity_kw=6, duration_min=180))
    assert not result["Reached temperature"]
    assert result["Time to temperature min"] is None


# --- feed admission -------------------------------------------------------

def test_ammonia_is_withheld_until_the_bed_is_hot():
    history = run(feed_admission_c=400)
    fed = [row for row in history if row["NH3 feed kg/h"] > 0]
    assert fed, "feed was never admitted"
    assert all(row["Temperature C"] > 350 for row in fed)
    assert history[0]["NH3 feed kg/h"] == 0


def test_no_conversion_and_no_duty_before_feed_is_admitted():
    history = run()
    before = [row for row in history if row["NH3 feed kg/h"] == 0]
    assert all(row["Conversion percent"] == 0 for row in before)
    assert all(row["Process duty kW"] == 0 for row in before)


def test_feed_admission_causes_a_temperature_excursion():
    # The controller learns the new load through a lag, so admitting feed
    # pulls the bed below where it would otherwise have been.
    history = run()
    admission = next(i for i, row in enumerate(history) if row["NH3 feed kg/h"] > 0)
    before = history[admission - 1]["Temperature C"]
    during = min(row["Temperature C"] for row in history[admission : admission + 24])
    assert during < before


# --- load following -------------------------------------------------------

def test_space_velocity_follows_the_feed_on_a_fixed_bed():
    history = run(turndown_start_min=90, turndown_end_min=105, turndown_fraction=0.4)
    full = next(r for r in history if r["Time min"] == 85)
    turned_down = next(r for r in history if r["Time min"] == 95)
    assert turned_down["NH3 feed kg/h"] == pytest.approx(0.4 * full["NH3 feed kg/h"])
    assert turned_down["GHSV 1/h"] == pytest.approx(0.4 * full["GHSV 1/h"])


def test_turndown_disturbs_the_temperature_and_it_recovers():
    history = run(
        duration_min=130, turndown_start_min=90, turndown_end_min=105, turndown_fraction=0.4
    )
    settled = next(r for r in history if r["Time min"] == 89)["Temperature C"]
    peak = max(r["Temperature C"] for r in history if 90 <= r["Time min"] <= 95)
    recovered = next(r for r in history if r["Time min"] == 104)["Temperature C"]
    assert peak > settled + 2
    assert recovered == pytest.approx(settled, abs=1.0)


def test_turndown_reduces_firing():
    history = run(turndown_start_min=90, turndown_end_min=105, turndown_fraction=0.4)
    full = next(r for r in history if r["Time min"] == 89)["Fired kW"]
    turned_down = next(r for r in history if r["Time min"] == 100)["Fired kW"]
    assert turned_down < full


# --- what the operator asks for -------------------------------------------

def test_off_spec_ammonia_is_counted_until_the_product_is_good():
    result = summarise(run())
    assert result["Reached specification"]
    assert result["Ammonia fed before on-spec kg"] > 0


def test_product_can_be_on_spec_before_the_bed_reaches_setpoint():
    # Ruthenium is active well below 650 C and the purification train cleans
    # up the rest, so saleable gas arrives before the reactor has settled.
    result = summarise(run())
    assert (
        result["Time to on-specification min"] < result["Time to temperature min"]
    )


def test_a_weak_purification_train_never_reaches_specification():
    # The default train fails the specification at steady state, so no amount
    # of warming up rescues it.
    result = summarise(simulate(**RUN))
    assert result["Reached temperature"]
    assert not result["Reached specification"]
    assert result["Time to on-specification min"] is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
