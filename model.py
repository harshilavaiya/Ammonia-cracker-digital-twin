def ammonia_cracker_model(
    nh3_feed_kg_h,
    conversion_percent,
    heat_recovery_percent,
    h2_recovery_percent,
    temperature_c,
    pressure_bar
):
    # Molecular weights in kg/kmol
    MW_NH3 = 17.031
    MW_H2 = 2.016
    MW_N2 = 28.014

    # Convert percentages to fractions
    conversion = conversion_percent / 100
    heat_recovery = heat_recovery_percent / 100
    h2_recovery = h2_recovery_percent / 100

    # NH3 molar flow
    nh3_kmol_h = nh3_feed_kg_h / MW_NH3

    # Converted and unconverted NH3
    nh3_converted_kmol_h = nh3_kmol_h * conversion
    nh3_unconverted_kmol_h = nh3_kmol_h * (1 - conversion)

    # Reaction: 2NH3 → N2 + 3H2
    h2_kmol_h = 1.5 * nh3_converted_kmol_h
    n2_kmol_h = 0.5 * nh3_converted_kmol_h

    # Convert to kg/h
    h2_kg_h_raw = h2_kmol_h * MW_H2
    n2_kg_h = n2_kmol_h * MW_N2
    nh3_slip_kg_h = nh3_unconverted_kmol_h * MW_NH3

    # Hydrogen purification recovery
    h2_kg_h_product = h2_kg_h_raw * h2_recovery

    # Hydrogen volume at normal conditions
    h2_Nm3_h = h2_kmol_h * 22.414 * h2_recovery

    # Reaction heat demand
    # Approx. 46.2 kJ/mol NH3 converted
    q_reaction_kJ_h = nh3_converted_kmol_h * 1000 * 46.2
    q_reaction_kW = q_reaction_kJ_h / 3600

    # Net heat demand after heat recovery
    q_net_kW = q_reaction_kW * (1 - heat_recovery)

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
        "H2 raw kg/h": h2_kg_h_raw,
        "H2 product kg/h": h2_kg_h_product,
        "H2 product Nm3/h": h2_Nm3_h,
        "N2 kg/h": n2_kg_h,
        "NH3 slip kg/h": nh3_slip_kg_h,
        "NH3 slip percent": nh3_slip_percent,
        "Reaction heat kW": q_reaction_kW,
        "Net heat demand kW": q_net_kW,
        "Status": status,
        "Status reason": status_reason,
        "Recommended action": recommended_action
    }