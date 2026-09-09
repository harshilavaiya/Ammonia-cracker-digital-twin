"""
Transient model of a modular ammonia cracker.

The steady-state model answers what the unit does once it has settled. This
one answers how long it takes to get there, and what comes out of the pipe in
the meantime. Both matter for a decentralised unit, because demand at a
refuelling site is intermittent and the reactor spends a real fraction of its
life warming up or following load.

The reactor is treated as one lumped thermal mass, catalyst and vessel
together, with the energy balance

    M*cp * dT/dt = Q_fired - Q_process(T) - Q_loss(T)

Conversion is evaluated from the instantaneous temperature at every step, so
a cold reactor produces off-specification gas until it catches up.

One detail matters more than it first appears. In the steady-state model the
space velocity is an input and the catalyst bed volume follows from it. Here
the bed is a physical object of fixed size, so the space velocity follows the
feed rate instead. Turning the plant down therefore lengthens residence time
and improves conversion, and ramping it up does the opposite.
"""

from model import V_MOLAR_NORMAL, MW_NH3, ammonia_cracker_model

# Thermal mass of the hot assembly, catalyst plus vessel plus internals.
DEFAULT_THERMAL_MASS_KG = 40.0
DEFAULT_THERMAL_MASS_CP = 500.0  # J/(kg*K), roughly stainless steel

# Overall heat loss coefficient of the insulated reactor, W/K.
DEFAULT_UA_LOSS_W_PER_K = 2.0

# Proportional gain of the firing controller, kW per K of error.
DEFAULT_CONTROLLER_GAIN = 0.5

# The controller feeds forward the heat the process is drawing, but it learns
# that load through a first-order lag rather than knowing it instantly. Without
# this the controller is clairvoyant and load changes produce no excursion at
# all, which is not what a real unit does.
DEFAULT_FEEDFORWARD_LAG_S = 60.0

# The setpoint is rate limited, but it is also not allowed to run far ahead
# of the measured temperature, which would wind the controller up.
SETPOINT_LEAD_LIMIT_K = 25.0

# Ammonia is not admitted until the bed is hot enough to crack it. Feeding a
# cold bed would push raw ammonia straight through to the purification train.
DEFAULT_FEED_ADMISSION_C = 400.0


def simulate(
    duration_min=120.0,
    dt_s=5.0,
    initial_temperature_c=20.0,
    target_temperature_c=650.0,
    max_ramp_c_per_min=10.0,
    burner_capacity_kw=30.0,
    thermal_mass_kg=DEFAULT_THERMAL_MASS_KG,
    thermal_mass_cp=DEFAULT_THERMAL_MASS_CP,
    ua_loss_w_per_k=DEFAULT_UA_LOSS_W_PER_K,
    controller_gain_kw_per_k=DEFAULT_CONTROLLER_GAIN,
    feedforward_lag_s=DEFAULT_FEEDFORWARD_LAG_S,
    feed_admission_c=DEFAULT_FEED_ADMISSION_C,
    ambient_temperature_c=20.0,
    nh3_feed_kg_h=10.0,
    bed_volume_m3=None,
    design_ghsv_h=5000.0,
    turndown_start_min=None,
    turndown_end_min=None,
    turndown_fraction=0.4,
    **steady_state_kwargs,
):
    """
    Integrate the reactor thermal balance and return a time series.

    bed_volume_m3 defaults to the volume the design feed rate implies at
    design_ghsv_h, which keeps the transient run consistent with the
    steady-state design point shown elsewhere.

    Set turndown_start_min and turndown_end_min to apply a load change of
    turndown_fraction during that window.

    Returns a list of dicts, one per timestep.
    """
    if dt_s <= 0:
        raise ValueError("Timestep must be greater than zero.")
    if duration_min <= 0:
        raise ValueError("Duration must be greater than zero.")

    # Losses are temperature dependent here rather than a flat percentage, so
    # the steady-state setting is dropped if a caller passes its whole input
    # dictionary straight through.
    steady_state_kwargs.pop("heat_loss_percent", None)

    if bed_volume_m3 is None:
        design_feed_Nm3_h = nh3_feed_kg_h / MW_NH3 * V_MOLAR_NORMAL
        bed_volume_m3 = design_feed_Nm3_h / design_ghsv_h
    if bed_volume_m3 <= 0:
        raise ValueError("Bed volume must be greater than zero.")

    heat_capacity_kJ_per_k = thermal_mass_kg * thermal_mass_cp / 1000
    steps = int(duration_min * 60 / dt_s)

    temperature_c = initial_temperature_c
    setpoint_c = initial_temperature_c
    feed_admitted = False
    feedforward_kw = 0.0

    history = []

    for step in range(steps + 1):
        time_min = step * dt_s / 60

        # The bed is not fed until it is hot enough, and once ammonia is
        # flowing it stays on rather than chattering around the threshold.
        if not feed_admitted and temperature_c >= feed_admission_c:
            feed_admitted = True

        feed_kg_h = nh3_feed_kg_h if feed_admitted else 0.0
        if (
            feed_admitted
            and turndown_start_min is not None
            and turndown_end_min is not None
            and turndown_start_min <= time_min < turndown_end_min
        ):
            feed_kg_h *= turndown_fraction

        # Fixed bed, so space velocity follows the feed.
        if feed_kg_h > 0:
            feed_Nm3_h = feed_kg_h / MW_NH3 * V_MOLAR_NORMAL
            ghsv_h = feed_Nm3_h / bed_volume_m3
            state = ammonia_cracker_model(
                nh3_feed_kg_h=feed_kg_h,
                temperature_c=temperature_c,
                ghsv_h=ghsv_h,
                heat_loss_percent=0.0,  # losses are modelled explicitly below
                **steady_state_kwargs,
            )
            q_process_kw = state["Net heat demand kW"]
        else:
            ghsv_h = 0.0
            state = None
            q_process_kw = 0.0

        q_loss_kw = ua_loss_w_per_k * (temperature_c - ambient_temperature_c) / 1000

        # Rate-limited setpoint, held back so it cannot run away from the
        # measurement while the reactor is struggling to keep up.
        setpoint_c = min(
            target_temperature_c,
            setpoint_c + max_ramp_c_per_min * dt_s / 60,
            temperature_c + SETPOINT_LEAD_LIMIT_K,
        )

        # The feedforward estimate chases the true load through a lag, so a
        # step change in feed shows up as a temperature excursion before the
        # controller catches up.
        feedforward_kw += (q_process_kw + q_loss_kw - feedforward_kw) * min(
            1.0, dt_s / feedforward_lag_s
        )

        q_fired_kw = feedforward_kw + controller_gain_kw_per_k * (
            setpoint_c - temperature_c
        )
        q_fired_kw = max(0.0, min(burner_capacity_kw, q_fired_kw))
        burner_saturated = q_fired_kw >= burner_capacity_kw - 1e-9

        history.append(
            {
                "Time min": time_min,
                "Temperature C": temperature_c,
                "Setpoint C": setpoint_c,
                "Fired kW": q_fired_kw,
                "Process duty kW": q_process_kw,
                "Heat loss kW": q_loss_kw,
                "NH3 feed kg/h": feed_kg_h,
                "GHSV 1/h": ghsv_h,
                "Conversion percent": state["Conversion percent"] if state else 0.0,
                "NH3 product ppmv": state["NH3 product ppmv"] if state else 0.0,
                "H2 net kg/h": state["H2 net kg/h"] if state else 0.0,
                "On specification": bool(state["Meets ISO 14687"]) if state else False,
                "Burner saturated": burner_saturated,
            }
        )

        # Explicit Euler. The timestep is far below the thermal time constant,
        # so this is stable without needing an implicit solver.
        net_kw = q_fired_kw - q_process_kw - q_loss_kw
        temperature_c += net_kw * dt_s / heat_capacity_kJ_per_k

    return history


def summarise(history, target_temperature_c=650.0, tolerance_k=5.0):
    """
    Pull the numbers an operator would actually ask for out of a run.

    Returns time to reach temperature, time to first on-specification gas,
    the ammonia sent to the purification train before that point, and the
    peak firing rate.
    """
    time_to_temperature = None
    time_to_spec = None
    off_spec_nh3_kg = 0.0
    peak_fired_kw = 0.0
    previous_time_min = 0.0
    saturated_minutes = 0.0
    worst_undershoot_k = 0.0

    for row in history:
        if row["Burner saturated"]:
            saturated_minutes += row["Time min"] - previous_time_min
        worst_undershoot_k = max(
            worst_undershoot_k, row["Setpoint C"] - row["Temperature C"]
        )

        if (
            time_to_temperature is None
            and row["Temperature C"] >= target_temperature_c - tolerance_k
        ):
            time_to_temperature = row["Time min"]

        if time_to_spec is None and row["On specification"]:
            time_to_spec = row["Time min"]

        if time_to_spec is None:
            interval_h = (row["Time min"] - previous_time_min) / 60
            off_spec_nh3_kg += row["NH3 feed kg/h"] * interval_h

        peak_fired_kw = max(peak_fired_kw, row["Fired kW"])
        previous_time_min = row["Time min"]

    return {
        "Time to temperature min": time_to_temperature,
        "Time to on-specification min": time_to_spec,
        "Ammonia fed before on-spec kg": off_spec_nh3_kg,
        "Peak firing kW": peak_fired_kw,
        "Minutes at burner limit": saturated_minutes,
        "Worst undershoot K": worst_undershoot_k,
        "Reached temperature": time_to_temperature is not None,
        "Reached specification": time_to_spec is not None,
        # Which constraint set the start-up time. If the burner never
        # saturated, the operator's ramp limit was the binding one.
        "Limited by": "Burner capacity" if saturated_minutes > 0 else "Ramp rate",
    }
