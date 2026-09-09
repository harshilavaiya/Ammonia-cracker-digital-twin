"""
Steady-state model of a modular ammonia cracker.

Conversion is not an input. It is predicted from reactor temperature,
pressure, space velocity and catalyst, capped by chemical equilibrium.
"""

import math

import thermo

# Molecular weights in kg/kmol
MW_NH3 = 17.031
MW_H2 = 2.016
MW_N2 = 28.014

# Molar volume of an ideal gas at normal conditions, Nm3/kmol
V_MOLAR_NORMAL = 22.414

# Molar quantities from thermo are in J/mol, which is numerically equal to
# kJ/kmol. Flows here are in kmol/h, so their product is directly kJ/h.
SECONDS_PER_HOUR = 3600

# Lumped first-order rate parameters per catalyst.
#
# These are illustrative parameters, not measured kinetics. They were chosen
# so the model reproduces the behaviour reported in the open literature:
# ruthenium reaches near-complete conversion around 450 C, while nickel needs
# roughly 600-650 C for the same duty. The activation energies are within the
# ranges usually quoted for each system.
CATALYSTS = {
    "Ru/Al2O3": {
        "pre_exponential_h": 5.0e9,
        "activation_energy_J_mol": 75_000,
        "note": "High activity at low temperature. Expensive.",
    },
    "Ni/Al2O3": {
        "pre_exponential_h": 2.0e15,
        "activation_energy_J_mol": 190_000,
        "note": "Low cost. Needs roughly 600 C or more to be effective.",
    },
}

DEFAULT_CATALYST = "Ru/Al2O3"


def predict_conversion(
    temperature_c,
    pressure_bar,
    ghsv_h,
    catalyst=DEFAULT_CATALYST,
    catalyst_activity=1.0,
):
    """
    Predict fractional NH3 conversion from the reactor operating point.

    Two limits act in series. Equilibrium sets the ceiling, and the catalyst
    decides how close to that ceiling the reactor actually gets in the
    residence time available.

    The kinetic term treats the bed as a plug flow reactor with a lumped
    first-order rate, for which the approach to equilibrium decays
    exponentially with space time:

        x = x_eq * (1 - exp(-Da)),    Da = k(T) * activity / GHSV

    Da is the Damkohler number, the ratio of residence time to reaction time.
    Above about Da = 3 the reactor sits at equilibrium and adding catalyst
    volume buys nothing. Below it the reactor is kinetically limited, and
    slip is set by reactor size rather than by thermodynamics.

    Returns a dict with the equilibrium ceiling, the predicted conversion,
    the Damkohler number and which of the two limits is binding.
    """
    if catalyst not in CATALYSTS:
        raise ValueError(
            "Unknown catalyst " + repr(catalyst) + ". Options: " + str(sorted(CATALYSTS))
        )
    if ghsv_h <= 0:
        raise ValueError("GHSV must be greater than zero.")

    temperature_k = temperature_c + 273.15
    params = CATALYSTS[catalyst]

    x_eq = thermo.equilibrium_conversion(temperature_k, pressure_bar)

    rate_constant_h = params["pre_exponential_h"] * math.exp(
        -params["activation_energy_J_mol"] / (thermo.R * temperature_k)
    )
    damkohler = rate_constant_h * catalyst_activity / ghsv_h
    approach = 1 - math.exp(-min(damkohler, 700))  # clamp guards the exp
    conversion = x_eq * approach

    if approach < 0.95:
        regime = "Kinetically limited"
    elif x_eq < 0.995:
        regime = "Equilibrium limited"
    else:
        regime = "Near-complete conversion"

    return {
        "conversion": conversion,
        "equilibrium_conversion": x_eq,
        "approach_to_equilibrium": approach,
        "damkohler": damkohler,
        "regime": regime,
    }


def ammonia_cracker_model(
    nh3_feed_kg_h,
    heat_recovery_percent,
    h2_recovery_percent,
    temperature_c,
    pressure_bar,
    ghsv_h=5000.0,
    catalyst=DEFAULT_CATALYST,
    catalyst_activity_percent=100.0,
    feed_temperature_c=25.0,
    burner_efficiency_percent=85.0,
    heat_loss_percent=5.0,
    conversion_override_percent=None,
):
    """
    Solve the mass and energy balance for one cracker module.

    heat_recovery_percent is the effectiveness of the feed/effluent
    recuperator, not a fraction of the reaction duty.

    Pass conversion_override_percent to force a conversion, for example when
    reconciling the model against a measured value from a real unit.
    """
    if nh3_feed_kg_h <= 0:
        raise ValueError("NH3 feed rate must be greater than zero.")

    # Convert percentages to fractions
    heat_recovery = heat_recovery_percent / 100
    h2_recovery = h2_recovery_percent / 100

    reactor = predict_conversion(
        temperature_c=temperature_c,
        pressure_bar=pressure_bar,
        ghsv_h=ghsv_h,
        catalyst=catalyst,
        catalyst_activity=catalyst_activity_percent / 100,
    )
    if conversion_override_percent is None:
        conversion = reactor["conversion"]
    else:
        conversion = conversion_override_percent / 100

    # NH3 molar flow
    nh3_kmol_h = nh3_feed_kg_h / MW_NH3

    # Converted and unconverted NH3
    nh3_converted_kmol_h = nh3_kmol_h * conversion
    nh3_unconverted_kmol_h = nh3_kmol_h * (1 - conversion)

    # Reaction: 2NH3 -> N2 + 3H2
    h2_kmol_h = 1.5 * nh3_converted_kmol_h
    n2_kmol_h = 0.5 * nh3_converted_kmol_h

    # Convert to kg/h
    h2_kg_h_raw = h2_kmol_h * MW_H2
    n2_kg_h = n2_kmol_h * MW_N2
    nh3_slip_kg_h = nh3_unconverted_kmol_h * MW_NH3

    # Hydrogen purification recovery
    h2_kg_h_product = h2_kg_h_raw * h2_recovery

    # Hydrogen volume at normal conditions
    h2_Nm3_h = h2_kmol_h * V_MOLAR_NORMAL * h2_recovery

    # Catalyst bed volume implied by the chosen space velocity
    nh3_feed_Nm3_h = nh3_kmol_h * V_MOLAR_NORMAL
    bed_volume_m3 = nh3_feed_Nm3_h / ghsv_h

    # --- Energy balance ---------------------------------------------------
    #
    # The reaction enthalpy alone understates the duty by roughly half. Feed
    # ammonia arrives as a liquid and has to be vaporised, then heated from
    # storage temperature to reactor temperature, before any of it reacts.
    # The three terms are tracked separately because they behave differently:
    # only the two sensible terms can be recovered from the product stream.
    temperature_k = temperature_c + 273.15
    feed_temperature_k = feed_temperature_c + 273.15

    q_vaporisation_kJ_h = nh3_kmol_h * thermo.DH_VAP_NH3
    q_preheat_kJ_h = nh3_kmol_h * thermo.enthalpy_change(
        "NH3", feed_temperature_k, temperature_k
    )
    # reaction_enthalpy is per 2 mol NH3, and is evaluated at reactor
    # temperature rather than at 298 K, which adds about 18 percent.
    q_reaction_kJ_h = (
        nh3_converted_kmol_h * thermo.reaction_enthalpy(temperature_k) / 2
    )

    q_process_kJ_h = q_vaporisation_kJ_h + q_preheat_kJ_h + q_reaction_kJ_h
    q_loss_kJ_h = q_process_kJ_h * (heat_loss_percent / 100)
    q_total_kJ_h = q_process_kJ_h + q_loss_kJ_h

    # Heat available in the hot product gas, cooled back to feed temperature.
    q_products_kJ_h = (
        h2_kmol_h * thermo.enthalpy_change("H2", feed_temperature_k, temperature_k)
        + n2_kmol_h * thermo.enthalpy_change("N2", feed_temperature_k, temperature_k)
        + nh3_unconverted_kmol_h
        * thermo.enthalpy_change("NH3", feed_temperature_k, temperature_k)
    )

    # A feed/effluent recuperator can only put heat back into the feed, so
    # recovery is capped by what the feed is able to absorb.
    q_recovered_kJ_h = min(
        heat_recovery * q_products_kJ_h,
        q_vaporisation_kJ_h + q_preheat_kJ_h,
    )
    q_net_kJ_h = q_total_kJ_h - q_recovered_kJ_h

    # --- Burner -----------------------------------------------------------
    #
    # The net duty has to be fired. The purification stage rejects a tail gas
    # carrying the hydrogen it could not recover plus the ammonia slip, and
    # that gas is burned first because it is otherwise waste. Only the
    # shortfall is made up by diverting product hydrogen, which is the real
    # cost of cracking: hydrogen burned is hydrogen not sold.
    burner_efficiency = burner_efficiency_percent / 100

    h2_rejected_kmol_h = h2_kmol_h * (1 - h2_recovery)
    q_tail_gas_kJ_h = (
        h2_rejected_kmol_h * thermo.LHV["H2"]
        + nh3_unconverted_kmol_h * thermo.LHV["NH3"]
    ) * burner_efficiency

    q_shortfall_kJ_h = max(0.0, q_net_kJ_h - q_tail_gas_kJ_h)
    h2_burned_kmol_h = q_shortfall_kJ_h / (thermo.LHV["H2"] * burner_efficiency)
    h2_burned_kg_h = h2_burned_kmol_h * MW_H2

    h2_net_kg_h = h2_kg_h_product - h2_burned_kg_h
    h2_net_Nm3_h = (h2_kmol_h * h2_recovery - h2_burned_kmol_h) * V_MOLAR_NORMAL
    h2_burned_percent = (
        h2_burned_kg_h / h2_kg_h_product * 100 if h2_kg_h_product > 0 else 0.0
    )
    energy_self_sufficient = h2_net_kg_h > 0

    # LHV out over LHV in. This excludes compression and electrical
    # parasitics, so it is an upper bound on real system efficiency.
    system_efficiency_percent = (
        (h2_net_kg_h / MW_H2) * thermo.LHV["H2"] / (nh3_kmol_h * thermo.LHV["NH3"]) * 100
    )

    q_vaporisation_kW = q_vaporisation_kJ_h / SECONDS_PER_HOUR
    q_preheat_kW = q_preheat_kJ_h / SECONDS_PER_HOUR
    q_reaction_kW = q_reaction_kJ_h / SECONDS_PER_HOUR
    q_loss_kW = q_loss_kJ_h / SECONDS_PER_HOUR
    q_total_kW = q_total_kJ_h / SECONDS_PER_HOUR
    q_recovered_kW = q_recovered_kJ_h / SECONDS_PER_HOUR
    q_net_kW = q_net_kJ_h / SECONDS_PER_HOUR
    q_tail_gas_kW = q_tail_gas_kJ_h / SECONDS_PER_HOUR

    # NH3 slip percentage relative to feed
    nh3_slip_percent = (nh3_slip_kg_h / nh3_feed_kg_h) * 100

    # Safety logic
    shutdown_reasons = []
    warning_reasons = []

    # Temperature checks
    if temperature_c > 750:
        shutdown_reasons.append("Reactor temperature is above 750°C.")
    elif temperature_c < 500:
        shutdown_reasons.append("Reactor temperature is below 500°C.")
    elif temperature_c > 700:
        warning_reasons.append("Reactor temperature is high, above the preferred operating range.")
    elif temperature_c < 550:
        warning_reasons.append("Reactor temperature is low, which may reduce ammonia conversion.")

    # Pressure checks
    if pressure_bar > 8:
        shutdown_reasons.append("Pressure is above 8 bar.")
    elif pressure_bar > 6:
        warning_reasons.append("Pressure is above the normal operating range.")

    # NH3 slip checks
    if nh3_slip_percent > 5:
        shutdown_reasons.append("NH3 slip is above 5%, which is too high.")
    elif nh3_slip_percent > 1:
        warning_reasons.append("NH3 slip is above 1%, which may require process adjustment.")

    # Final status decision
    if shutdown_reasons:
        status = "Shutdown"
        status_reason = " ".join(shutdown_reasons)
        recommended_action = (
            "Stop the operation and check reactor temperature, pressure, and ammonia conversion. "
            "Do not continue operation until the unsafe condition is corrected."
        )
    elif warning_reasons:
        status = "Warning"
        status_reason = " ".join(warning_reasons)
        recommended_action = (
            "Continue monitoring. Adjust reactor temperature, reduce NH3 feed rate, "
            "or improve conversion to reduce NH3 slip."
        )
    else:
        status = "Safe"
        status_reason = (
            "Normal operation. Reactor temperature, pressure, and NH3 slip are within acceptable limits."
        )
        recommended_action = (
            "No immediate action required. Continue normal monitoring of the process."
        )

    return {
        "Conversion percent": conversion * 100,
        "Equilibrium conversion percent": reactor["equilibrium_conversion"] * 100,
        "Approach to equilibrium percent": reactor["approach_to_equilibrium"] * 100,
        "Damkohler number": reactor["damkohler"],
        "Limiting regime": reactor["regime"],
        "Catalyst": catalyst,
        "Catalyst bed volume m3": bed_volume_m3,
        "H2 raw kg/h": h2_kg_h_raw,
        "H2 product kg/h": h2_kg_h_product,
        "H2 product Nm3/h": h2_Nm3_h,
        "N2 kg/h": n2_kg_h,
        "NH3 slip kg/h": nh3_slip_kg_h,
        "NH3 slip percent": nh3_slip_percent,
        "Vaporisation duty kW": q_vaporisation_kW,
        "Feed preheat duty kW": q_preheat_kW,
        "Reaction heat kW": q_reaction_kW,
        "Heat loss kW": q_loss_kW,
        "Total heat duty kW": q_total_kW,
        "Recovered heat kW": q_recovered_kW,
        "Net heat demand kW": q_net_kW,
        "Tail gas fuel kW": q_tail_gas_kW,
        "H2 burned kg/h": h2_burned_kg_h,
        "H2 burned percent": h2_burned_percent,
        "H2 net kg/h": h2_net_kg_h,
        "H2 net Nm3/h": h2_net_Nm3_h,
        "System efficiency percent": system_efficiency_percent,
        "Energy self-sufficient": energy_self_sufficient,
        "Status": status,
        "Status reason": status_reason,
        "Recommended action": recommended_action,
    }
