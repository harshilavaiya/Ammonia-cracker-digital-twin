"""
Tests for the ammonia cracker model.

Run with:  pytest -q
"""

import math

import pytest

import thermo
from model import MW_NH3, ammonia_cracker_model, predict_conversion

BASE_CASE = dict(
    nh3_feed_kg_h=10,
    heat_recovery_percent=60,
    h2_recovery_percent=95,
    temperature_c=650,
    pressure_bar=5,
    ghsv_h=5000,
    catalyst="Ru/Al2O3",
)


# --- thermodynamics -------------------------------------------------------

def test_heat_capacities_match_reference_values_at_298k():
    # Reference Cp at 298 K in J/(mol*K): NH3 35.1, N2 29.1, H2 28.8
    assert thermo.cp("NH3", 298.15) == pytest.approx(35.1, abs=0.6)
    assert thermo.cp("N2", 298.15) == pytest.approx(29.1, abs=0.2)
    assert thermo.cp("H2", 298.15) == pytest.approx(28.8, abs=0.2)


def test_ammonia_is_stable_at_room_temperature():
    # Cracking is strongly unfavourable at 25 C, so K must be far below 1.
    assert thermo.equilibrium_constant(298.15) < 1e-4


def test_equilibrium_conversion_is_near_complete_above_400c():
    assert thermo.equilibrium_conversion(673.15, 1) > 0.98


def test_pressure_suppresses_equilibrium_conversion():
    # Le Chatelier: cracking makes four moles from two, so pressure hurts.
    low = thermo.equilibrium_conversion(773.15, 1)
    high = thermo.equilibrium_conversion(773.15, 10)
    assert high < low


def test_equilibrium_conversion_rises_with_temperature():
    values = [thermo.equilibrium_conversion(t, 5) for t in (700, 800, 900, 1000)]
    assert values == sorted(values)


# --- kinetics -------------------------------------------------------------

def test_conversion_never_exceeds_equilibrium():
    for temperature in (450, 550, 650, 750):
        for pressure in (1, 5, 10):
            result = predict_conversion(temperature, pressure, 5000)
            assert result["conversion"] <= result["equilibrium_conversion"]


def test_higher_space_velocity_lowers_conversion():
    # Less residence time per unit of catalyst means less conversion.
    slow = predict_conversion(500, 1, 2_000)["conversion"]
    fast = predict_conversion(500, 1, 200_000)["conversion"]
    assert fast < slow


def test_ruthenium_outperforms_nickel_at_low_temperature():
    ru = predict_conversion(450, 1, 5000, "Ru/Al2O3")["conversion"]
    ni = predict_conversion(450, 1, 5000, "Ni/Al2O3")["conversion"]
    assert ru > ni


def test_catalyst_deactivation_reduces_conversion():
    fresh = predict_conversion(600, 1, 5000, "Ni/Al2O3", catalyst_activity=1.0)
    aged = predict_conversion(600, 1, 5000, "Ni/Al2O3", catalyst_activity=0.5)
    assert aged["conversion"] < fresh["conversion"]


def test_regime_is_kinetic_when_catalyst_is_too_slow():
    # Nickel at 500 C is far from equilibrium.
    assert predict_conversion(500, 1, 5000, "Ni/Al2O3")["regime"] == "Kinetically limited"


def test_regime_is_equilibrium_when_catalyst_is_fast_and_pressure_is_high():
    assert predict_conversion(600, 10, 2000, "Ru/Al2O3")["regime"] == "Equilibrium limited"


def test_unknown_catalyst_is_rejected():
    with pytest.raises(ValueError):
        predict_conversion(600, 1, 5000, "Pt/Al2O3")


def test_non_positive_space_velocity_is_rejected():
    with pytest.raises(ValueError):
        predict_conversion(600, 1, 0)


# --- balances -------------------------------------------------------------

def test_mass_balance_closes():
    result = ammonia_cracker_model(**BASE_CASE)
    out = result["H2 raw kg/h"] + result["N2 kg/h"] + result["NH3 slip kg/h"]
    assert out == pytest.approx(BASE_CASE["nh3_feed_kg_h"], rel=1e-9)


def test_reaction_heat_matches_converted_ammonia():
    result = ammonia_cracker_model(**BASE_CASE)
    converted_kmol_h = (
        BASE_CASE["nh3_feed_kg_h"] / MW_NH3 * result["Conversion percent"] / 100
    )
    expected_kw = converted_kmol_h * 1000 * 46.2 / 3600
    assert result["Reaction heat kW"] == pytest.approx(expected_kw, rel=1e-9)


def test_heat_recovery_reduces_net_duty():
    result = ammonia_cracker_model(**BASE_CASE)
    assert result["Net heat demand kW"] == pytest.approx(
        result["Reaction heat kW"] * 0.4, rel=1e-9
    )


def test_hydrogen_output_is_proportional_to_feed():
    small = ammonia_cracker_model(**{**BASE_CASE, "nh3_feed_kg_h": 10})
    large = ammonia_cracker_model(**{**BASE_CASE, "nh3_feed_kg_h": 20})
    assert large["H2 product kg/h"] == pytest.approx(2 * small["H2 product kg/h"])


def test_bed_volume_scales_inversely_with_space_velocity():
    dense = ammonia_cracker_model(**{**BASE_CASE, "ghsv_h": 5000})
    sparse = ammonia_cracker_model(**{**BASE_CASE, "ghsv_h": 10000})
    assert sparse["Catalyst bed volume m3"] == pytest.approx(
        dense["Catalyst bed volume m3"] / 2
    )


def test_zero_feed_is_rejected_instead_of_dividing_by_zero():
    with pytest.raises(ValueError):
        ammonia_cracker_model(**{**BASE_CASE, "nh3_feed_kg_h": 0})


def test_conversion_override_bypasses_the_kinetic_model():
    result = ammonia_cracker_model(**BASE_CASE, conversion_override_percent=90)
    assert result["Conversion percent"] == pytest.approx(90)
    assert result["NH3 slip percent"] == pytest.approx(10)


# --- safety logic ---------------------------------------------------------

def test_normal_operating_point_is_safe():
    assert ammonia_cracker_model(**BASE_CASE)["Status"] == "Safe"


def test_overtemperature_triggers_shutdown():
    result = ammonia_cracker_model(**{**BASE_CASE, "temperature_c": 800})
    assert result["Status"] == "Shutdown"


def test_overpressure_triggers_shutdown():
    result = ammonia_cracker_model(**{**BASE_CASE, "pressure_bar": 9})
    assert result["Status"] == "Shutdown"


def test_high_slip_triggers_shutdown():
    result = ammonia_cracker_model(**BASE_CASE, conversion_override_percent=90)
    assert result["Status"] == "Shutdown"
    assert "slip" in result["Status reason"].lower()


def test_shutdown_takes_priority_over_warning():
    result = ammonia_cracker_model(
        **{**BASE_CASE, "pressure_bar": 9, "temperature_c": 720}
    )
    assert result["Status"] == "Shutdown"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
