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

    # Safety logic
    if temperature_c > 750 or pressure_bar > 8 or nh3_slip_kg_h > 0.2:
        status = "Shutdown"
    elif temperature_c < 550 or pressure_bar > 6 or nh3_slip_kg_h > 0.05:
        status = "Warning"
    else:
        status = "Safe"

    return {
        "H2 raw kg/h": h2_kg_h_raw,
        "H2 product kg/h": h2_kg_h_product,
        "H2 product Nm3/h": h2_Nm3_h,
        "N2 kg/h": n2_kg_h,
        "NH3 slip kg/h": nh3_slip_kg_h,
        "Reaction heat kW": q_reaction_kW,
        "Net heat demand kW": q_net_kW,
        "Status": status
    }