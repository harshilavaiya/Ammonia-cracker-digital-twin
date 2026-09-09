"""
Tests for the ammonia cracker model.

Run with:  pytest -q
"""

import math

import pytest

import thermo
from model import (
    ISO_14687_LIMITS,
    MW_NH3,
    ammonia_cracker_model,
    predict_conversion,
)

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
    dh_per_mol_nh3 = thermo.reaction_enthalpy(BASE_CASE["temperature_c"] + 273.15) / 2
    expected_kw = converted_kmol_h * dh_per_mol_nh3 / 3600
    assert result["Reaction heat kW"] == pytest.approx(expected_kw, rel=1e-9)


def test_reaction_enthalpy_grows_with_temperature():
    # Evaluating at reactor temperature rather than 298 K matters: the duty
    # is roughly 18 percent higher at 650 C than the textbook 92 kJ figure.
    assert thermo.reaction_enthalpy(298.15) == pytest.approx(91800, rel=1e-9)
    assert thermo.reaction_enthalpy(923.15) > 105_000


def test_energy_balance_sums_to_total_duty():
    result = ammonia_cracker_model(**BASE_CASE)
    parts = (
        result["Vaporisation duty kW"]
        + result["Feed preheat duty kW"]
        + result["Reaction heat kW"]
        + result["Heat loss kW"]
    )
    assert parts == pytest.approx(result["Total heat duty kW"], rel=1e-9)
    assert result["Net heat demand kW"] == pytest.approx(
        result["Total heat duty kW"] - result["Recovered heat kW"], rel=1e-9
    )


def test_reaction_heat_alone_understates_the_duty():
    # The whole point of the energy balance: vaporising and preheating the
    # feed costs about as much as the reaction itself.
    result = ammonia_cracker_model(**BASE_CASE)
    assert result["Total heat duty kW"] > 1.8 * result["Reaction heat kW"]


def test_heat_recovery_reduces_net_duty():
    none = ammonia_cracker_model(**{**BASE_CASE, "heat_recovery_percent": 0})
    lots = ammonia_cracker_model(**{**BASE_CASE, "heat_recovery_percent": 80})
    assert none["Recovered heat kW"] == 0
    assert lots["Net heat demand kW"] < none["Net heat demand kW"]


def test_recovery_cannot_exceed_what_the_feed_can_absorb():
    # A feed/effluent recuperator only preheats the feed, so recovery is
    # capped by the vaporisation plus preheat duty.
    result = ammonia_cracker_model(**{**BASE_CASE, "heat_recovery_percent": 100})
    ceiling = result["Vaporisation duty kW"] + result["Feed preheat duty kW"]
    assert result["Recovered heat kW"] <= ceiling + 1e-9


def test_burning_hydrogen_reduces_saleable_product():
    result = ammonia_cracker_model(**BASE_CASE)
    assert result["H2 burned kg/h"] > 0
    assert result["H2 net kg/h"] == pytest.approx(
        result["H2 product kg/h"] - result["H2 burned kg/h"], rel=1e-9
    )
    assert result["H2 net kg/h"] < result["H2 product kg/h"]


def test_hydrogen_burn_is_in_the_expected_range():
    # Published decentralised crackers divert roughly 15 to 25 percent of
    # their hydrogen to fire the reaction.
    result = ammonia_cracker_model(**{**BASE_CASE, "heat_recovery_percent": 70})
    assert 10 < result["H2 burned percent"] < 30


def test_better_recuperation_burns_less_hydrogen():
    poor = ammonia_cracker_model(**{**BASE_CASE, "heat_recovery_percent": 0})
    good = ammonia_cracker_model(**{**BASE_CASE, "heat_recovery_percent": 80})
    assert good["H2 burned percent"] < poor["H2 burned percent"]
    assert good["System efficiency percent"] > poor["System efficiency percent"]


def test_tail_gas_offsets_the_burner_duty():
    # The hydrogen the purifier rejects is burned rather than wasted, so a
    # lower recovery leaves more tail gas fuel.
    lean = ammonia_cracker_model(**{**BASE_CASE, "h2_recovery_percent": 99})
    rich = ammonia_cracker_model(**{**BASE_CASE, "h2_recovery_percent": 75})
    assert rich["Tail gas fuel kW"] > lean["Tail gas fuel kW"]


def test_system_efficiency_is_below_unity_and_plausible():
    result = ammonia_cracker_model(**BASE_CASE)
    assert 50 < result["System efficiency percent"] < 100


def test_heat_losses_raise_the_duty():
    tight = ammonia_cracker_model(**{**BASE_CASE, "heat_loss_percent": 0})
    leaky = ammonia_cracker_model(**{**BASE_CASE, "heat_loss_percent": 20})
    assert tight["Heat loss kW"] == 0
    assert leaky["Total heat duty kW"] > tight["Total heat duty kW"]
    assert leaky["System efficiency percent"] < tight["System efficiency percent"]


# --- purification and product spec ----------------------------------------

def test_reactor_outlet_ammonia_is_orders_of_magnitude_over_spec():
    # The point of the whole purification section: 0.3 percent slip sounds
    # small but is roughly 1600 ppmv against a 0.1 ppmv limit.
    result = ammonia_cracker_model(**BASE_CASE)
    assert result["NH3 reactor outlet ppmv"] > 1000
    assert (
        result["NH3 reactor outlet ppmv"] / ISO_14687_LIMITS["nh3_ppmv"] > 10_000
    )


def test_purification_stages_reduce_ammonia_monotonically():
    result = ammonia_cracker_model(**BASE_CASE)
    assert (
        result["NH3 product ppmv"]
        < result["NH3 after guard bed ppmv"]
        < result["NH3 reactor outlet ppmv"]
    )


def test_default_train_misses_the_spec():
    # Defensible mid-range equipment is not good enough, which is the
    # engineering problem this section exists to show.
    result = ammonia_cracker_model(**BASE_CASE)
    assert not result["Meets ISO 14687"]
    assert result["ISO 14687 failures"]


def test_an_upgraded_train_meets_the_spec():
    result = ammonia_cracker_model(
        **BASE_CASE,
        nh3_guard_removal_percent=99.9,
        psa_nh3_decontamination_factor=500,
        psa_n2_rejection_percent=99.95,
    )
    assert result["Meets ISO 14687"]
    assert result["ISO 14687 failures"] == []
    assert result["NH3 product ppmv"] <= ISO_14687_LIMITS["nh3_ppmv"]
    assert result["N2 product ppmv"] <= ISO_14687_LIMITS["n2_ppmv"]
    assert result["H2 purity percent"] >= ISO_14687_LIMITS["h2_purity_percent"]


def test_a_better_guard_bed_lowers_product_ammonia():
    poor = ammonia_cracker_model(**{**BASE_CASE, "nh3_guard_removal_percent": 90})
    good = ammonia_cracker_model(**{**BASE_CASE, "nh3_guard_removal_percent": 99.9})
    assert good["NH3 product ppmv"] < poor["NH3 product ppmv"]


def test_perfect_conversion_alone_cannot_meet_the_spec():
    # Nitrogen and overall purity are purification problems, not reactor
    # problems, so a better reactor does not rescue an undersized PSA.
    result = ammonia_cracker_model(**BASE_CASE, conversion_override_percent=99.99)
    assert result["NH3 product ppmv"] <= ISO_14687_LIMITS["nh3_ppmv"]
    assert not result["Meets ISO 14687"]
    assert "N2" in result["ISO 14687 failures"]


def test_product_composition_sums_to_one_million_ppmv():
    result = ammonia_cracker_model(**BASE_CASE)
    total = (
        result["H2 purity percent"] * 10_000
        + result["N2 product ppmv"]
        + result["NH3 product ppmv"]
    )
    assert total == pytest.approx(1e6, rel=1e-9)


def test_captured_ammonia_leaves_the_tail_gas():
    # Ammonia caught by the scrubber becomes aqueous waste, so it is no
    # longer available to the burner as fuel.
    scrubbed = ammonia_cracker_model(**{**BASE_CASE, "nh3_guard_removal_percent": 99.9})
    unscrubbed = ammonia_cracker_model(**{**BASE_CASE, "nh3_guard_removal_percent": 0})
    assert scrubbed["Tail gas fuel kW"] < unscrubbed["Tail gas fuel kW"]
    assert scrubbed["NH3 captured kg/h"] > unscrubbed["NH3 captured kg/h"]


def test_lower_psa_recovery_costs_product_but_feeds_the_burner():
    lean = ammonia_cracker_model(**{**BASE_CASE, "h2_recovery_percent": 98})
    rich = ammonia_cracker_model(**{**BASE_CASE, "h2_recovery_percent": 75})
    assert rich["H2 product kg/h"] < lean["H2 product kg/h"]
    assert rich["Tail gas fuel kW"] > lean["Tail gas fuel kW"]


def test_cold_feed_costs_more_preheat():
    warm = ammonia_cracker_model(**{**BASE_CASE, "feed_temperature_c": 25})
    cold = ammonia_cracker_model(**{**BASE_CASE, "feed_temperature_c": -33})
    assert cold["Feed preheat duty kW"] > warm["Feed preheat duty kW"]


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
