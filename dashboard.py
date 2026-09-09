import csv
import io

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dynamics import simulate, summarise
from twin import (
    CAMPAIGN_PATH,
    CSV_FIELDS,
    DEFAULT_PROCESS,
    default_bed_volume_m3,
    diagnose,
    read_csv,
    reconcile,
)
from model import (
    CATALYSTS,
    ISO_14687_LIMITS,
    ammonia_cracker_model,
    predict_conversion,
)


st.set_page_config(page_title="Ammonia Cracker Digital Twin", layout="wide")

st.title("Digital Twin of a Modular Ammonia Cracker")
st.write("Simulation-based model for decentralized hydrogen production from ammonia.")
st.info(
    "This is a conceptual simulation model. It is not intended for real plant operation or safety certification."
)

with st.expander("Main Reaction and Model Explanation"):
    st.markdown("""
    The main chemical reaction in this project is ammonia cracking:

    **2 NH₃ → N₂ + 3 H₂**

    This reaction shows that ammonia decomposes into nitrogen and hydrogen.
    For every **2 moles of NH₃**, the reactor produces **1 mole of N₂** and **3 moles of H₂**.

    Ammonia cracking is an **endothermic reaction**, which means heat must be supplied to the reactor.

    Approximate reaction heat at standard conditions:

    **ΔH ≈ +92.4 kJ per 2 mol NH₃**
    **ΔH ≈ +46.2 kJ per mol NH₃**

    The model evaluates this enthalpy at reactor temperature rather than at 25 °C,
    which raises it by roughly 18 % at 650 °C.

    ### How the heat duty is built up

    The reaction enthalpy is only part of the story. Ammonia arrives as a liquid, so
    the duty is the sum of three terms:

    1. **Vaporisation** of the liquid ammonia, about 23.3 kJ/mol
    2. **Preheat** of the vapour from storage temperature to reactor temperature
    3. **Reaction** enthalpy at reactor temperature, for the fraction that converts

    Together these are roughly twice the reaction term alone. Only the two sensible
    terms can be given back by the feed/effluent recuperator, which is why its
    effectiveness matters so much.

    Whatever the recuperator does not return has to be **fired**. The purification
    stage rejects a tail gas containing the hydrogen it could not recover plus the
    ammonia slip, and that is burned first because it is otherwise waste. Only the
    shortfall is made up by diverting product hydrogen. Hydrogen burned is hydrogen
    that cannot be sold, so **net yield**, not raw production, is the number that
    decides whether the unit is worth running.

    ### How the product is purified

    ISO 14687 Grade D, the specification for PEM fuel cell vehicles, allows
    **0.1 ppmv of ammonia**, 300 ppmv of nitrogen and 99.97 % overall purity.
    A reactor at 99.7 % conversion still leaves roughly **1600 ppmv** of ammonia,
    so the train has to remove a factor of more than ten thousand.

    No single stage does that, so the model uses two in series:

    1. A **scrubber or adsorbent guard bed** takes out the bulk of the ammonia.
       What it captures leaves as aqueous waste, not as burner fuel.
    2. The **PSA** passes a fraction 1/DF of the ammonia that reaches it, rejects
       most of the nitrogen, and recovers only part of the hydrogen. Everything it
       rejects goes to the burner as tail gas.

    Because the two stages multiply, the specification is reachable. It is worth
    noticing that a better reactor does not rescue an undersized PSA: nitrogen and
    overall purity are separation problems, not reaction problems.

    ### How conversion is predicted

    Conversion is **not** an input to this model. It is calculated from the reactor
    operating point, because two separate limits decide how much ammonia actually cracks.

    **1. The equilibrium ceiling.** The equilibrium constant is obtained from
    ΔG°(T) = ΔH°(T) − T·ΔS°(T), with temperature-dependent heat capacities, and

    **K = (y_N₂ · y_H₂³ / y_NH₃²) · P²**

    The **P²** term matters: cracking makes four moles of gas out of two, so raising
    the pressure pushes the equilibrium back toward ammonia. This is why a cracker
    wants low pressure even though the downstream purification wants high pressure.

    **2. The kinetic approach.** The catalyst decides how close the reactor gets to
    that ceiling in the residence time available. The bed is treated as a plug flow
    reactor with a lumped first-order rate:

    **x = x_eq · (1 − e^(−Da))**, with **Da = k(T) · activity / GHSV**

    Da is the Damköhler number, the ratio of residence time to reaction time. Above
    roughly Da = 3 the reactor sits at equilibrium and extra catalyst buys nothing.
    Below it, ammonia slip is set by reactor size rather than by thermodynamics.

    The rate parameters are illustrative rather than measured. They are chosen so the
    model reproduces published behaviour: ruthenium is effective from about 450 °C,
    while nickel needs roughly 600–650 °C.

    The model uses this to calculate:

    - Ammonia conversion and the limiting regime
    - Hydrogen production
    - Nitrogen production
    - NH₃ slip
    - Reaction heat demand
    - Net heat demand after heat recovery
    """)
st.sidebar.header("Input Parameters")

nh3_feed = st.sidebar.slider("NH3 feed rate kg/h", 1.0, 100.0, 10.0)

st.sidebar.subheader("Reactor")
catalyst = st.sidebar.selectbox("Catalyst", list(CATALYSTS.keys()))
st.sidebar.caption(CATALYSTS[catalyst]["note"])
temperature = st.sidebar.slider("Reactor temperature °C", 500, 750, 650)
pressure = st.sidebar.slider("Pressure bar", 1.0, 10.0, 5.0)
ghsv = st.sidebar.slider("Space velocity GHSV 1/h", 1000, 50000, 5000, step=500)
catalyst_activity = st.sidebar.slider("Catalyst activity %", 10.0, 100.0, 100.0)

st.sidebar.subheader("Heat integration")
feed_temperature = st.sidebar.slider("NH3 feed temperature °C", -40, 40, 25)
heat_recovery = st.sidebar.slider("Recuperator effectiveness %", 0.0, 95.0, 60.0)
burner_efficiency = st.sidebar.slider("Burner efficiency %", 60.0, 95.0, 85.0)
heat_loss = st.sidebar.slider("Heat loss %", 0.0, 20.0, 5.0)

st.sidebar.subheader("Purification")
nh3_guard_removal = st.sidebar.slider("Guard bed NH3 removal %", 0.0, 99.99, 99.0, step=0.01)
psa_nh3_df = st.sidebar.slider("PSA NH3 decontamination factor", 1, 1000, 200, step=10)
psa_n2_rejection = st.sidebar.slider("PSA N2 rejection %", 99.0, 99.99, 99.9, step=0.01)
h2_recovery = st.sidebar.slider("PSA H2 recovery %", 70.0, 99.0, 95.0)

model_inputs = dict(
    heat_recovery_percent=heat_recovery,
    h2_recovery_percent=h2_recovery,
    temperature_c=temperature,
    pressure_bar=pressure,
    ghsv_h=ghsv,
    catalyst=catalyst,
    catalyst_activity_percent=catalyst_activity,
    feed_temperature_c=feed_temperature,
    burner_efficiency_percent=burner_efficiency,
    heat_loss_percent=heat_loss,
    nh3_guard_removal_percent=nh3_guard_removal,
    psa_nh3_decontamination_factor=psa_nh3_df,
    psa_n2_rejection_percent=psa_n2_rejection,
)

result = ammonia_cracker_model(nh3_feed_kg_h=nh3_feed, **model_inputs)

st.header("Reactor Performance")

st.write(
    "Conversion is predicted from temperature, pressure, space velocity and catalyst. "
    "It is not a dashboard input."
)

col_a, col_b, col_c, col_d = st.columns(4)

col_a.metric(
    "Predicted NH3 Conversion",
    f"{result['Conversion percent']:.3f} %",
    delta=f"{result['Conversion percent'] - result['Equilibrium conversion percent']:.3f} pp vs equilibrium",
    delta_color="off",
)
col_b.metric("Equilibrium Ceiling", f"{result['Equilibrium conversion percent']:.3f} %")
col_c.metric("Damköhler Number", f"{result['Damkohler number']:.2f}")
col_d.metric("Catalyst Bed Volume", f"{result['Catalyst bed volume m3'] * 1000:.2f} L")

if result["Limiting regime"] == "Kinetically limited":
    st.warning(
        f"**{result['Limiting regime']}.** The reactor reaches only "
        f"{result['Approach to equilibrium percent']:.1f} % of the equilibrium ceiling. "
        "Raise the temperature, lower the space velocity, or use a more active catalyst."
    )
elif result["Limiting regime"] == "Equilibrium limited":
    st.info(
        f"**{result['Limiting regime']}.** The catalyst is fast enough, but thermodynamics "
        f"caps conversion at {result['Equilibrium conversion percent']:.3f} % at "
        f"{temperature} °C and {pressure} bar. Lower the pressure or raise the temperature."
    )
else:
    st.success(
        f"**{result['Limiting regime']}.** The reactor is at its equilibrium ceiling and "
        "extra catalyst volume would not improve conversion."
    )

st.header("Main Results")

col1, col2, col3 = st.columns(3)

col1.metric("H2 Production", f"{result['H2 product kg/h']:.3f} kg/h")
col2.metric("H2 Production", f"{result['H2 product Nm3/h']:.2f} Nm³/h")
col3.metric("N2 Production", f"{result['N2 kg/h']:.3f} kg/h")

col4, col5, col6 = st.columns(3)

col4.metric("NH3 Slip", f"{result['NH3 slip kg/h']:.4f} kg/h")
col5.metric("NH3 Slip", f"{result['NH3 slip percent']:.3f} %")
col6.metric("Total Heat Duty", f"{result['Total heat duty kW']:.2f} kW")

st.header("Hydrogen Product Quality")

st.write(
    "Slip as a percentage of feed flatters the process. What the customer buys is "
    "measured in ppmv, and ISO 14687 allows 0.1 ppmv of ammonia for PEM fuel cell "
    "vehicles. This is the specification that decides whether the unit has a market."
)

col_q1, col_q2, col_q3 = st.columns(3)


def spec_metric(column, label, value, limit, unit, above_is_good=False, fmt=",.4g"):
    passed = value >= limit if above_is_good else value <= limit
    comparator = "min" if above_is_good else "max"
    column.metric(
        label,
        f"{value:{fmt}} {unit}",
        delta=f"{'PASS' if passed else 'FAIL'} · {comparator} {limit:g} {unit}",
        delta_color="normal" if passed else "inverse",
    )


spec_metric(col_q1, "NH₃ in Product", result["NH3 product ppmv"], ISO_14687_LIMITS["nh3_ppmv"], "ppmv")
spec_metric(col_q2, "N₂ in Product", result["N2 product ppmv"], ISO_14687_LIMITS["n2_ppmv"], "ppmv")
spec_metric(
    col_q3,
    "H₂ Purity",
    result["H2 purity percent"],
    ISO_14687_LIMITS["h2_purity_percent"],
    "%",
    above_is_good=True,
    fmt=".5f",
)

if result["Meets ISO 14687"]:
    st.success(
        "**Meets ISO 14687 Grade D.** The product is within specification for PEM "
        "fuel cell vehicles on ammonia, nitrogen and overall purity."
    )
else:
    st.error(
        "**Off specification for ISO 14687 Grade D** on "
        f"{', '.join(result['ISO 14687 failures'])}. Improve the guard bed, the PSA "
        "decontamination factor, or the nitrogen rejection. Note that a better reactor "
        "does not fix nitrogen or overall purity, because those are separation problems."
    )

cascade = [
    ("Reactor outlet", result["NH3 reactor outlet ppmv"]),
    ("After guard bed", result["NH3 after guard bed ppmv"]),
    ("After PSA (product)", result["NH3 product ppmv"]),
]

df_cascade = pd.DataFrame(
    [{"Stage": stage, "NH3 (ppmv)": max(value, 1e-6)} for stage, value in cascade]
)

fig_cascade = px.bar(
    df_cascade,
    x="Stage",
    y="NH3 (ppmv)",
    log_y=True,
    text="NH3 (ppmv)",
    title="Ammonia Through the Purification Train",
)

fig_cascade.update_traces(texttemplate="%{y:.3g}", textposition="outside")

fig_cascade.add_hline(
    y=ISO_14687_LIMITS["nh3_ppmv"],
    line_dash="dash",
    line_color="firebrick",
    annotation_text=f"ISO 14687 limit, {ISO_14687_LIMITS['nh3_ppmv']} ppmv",
    annotation_position="bottom right",
)

fig_cascade.update_layout(
    xaxis_title="",
    yaxis_title="NH3 concentration (ppmv), log scale",
    height=380,
)

st.plotly_chart(fig_cascade, width="stretch")

st.caption(
    f"The reactor leaves {result['NH3 reactor outlet ppmv']:,.0f} ppmv of ammonia and the "
    f"specification allows {ISO_14687_LIMITS['nh3_ppmv']}, so the train has to remove a factor of "
    f"{result['NH3 reactor outlet ppmv'] / ISO_14687_LIMITS['nh3_ppmv']:,.0f}. No single stage does "
    "that, which is why a scrubber or adsorbent guard bed sits ahead of the PSA. The ammonia the "
    f"guard bed captures leaves as {result['NH3 captured kg/h']:.4f} kg/h of aqueous waste rather "
    "than as burner fuel."
)

st.header("Energy Balance and Hydrogen Yield")

st.write(
    "Cracking is endothermic, and in a decentralised unit that heat comes from "
    "burning hydrogen. Hydrogen sent to the burner is hydrogen that cannot be sold, "
    "which makes net yield the number that decides whether the unit is worth running."
)

if not result["Energy self-sufficient"]:
    st.error(
        "**Not energy self-sufficient.** The burner needs more hydrogen than the "
        "reactor produces, so this operating point cannot sustain itself. Improve "
        "the recuperator, reduce heat losses, or lower the reactor temperature."
    )

col_e1, col_e2, col_e3, col_e4 = st.columns(4)

col_e1.metric(
    "Net H2 Product",
    f"{result['H2 net kg/h']:.3f} kg/h",
    delta=f"{result['H2 burned kg/h']:.3f} kg/h to burner",
    delta_color="inverse",
)
col_e2.metric("H2 Diverted to Burner", f"{result['H2 burned percent']:.1f} %")
col_e3.metric("System Efficiency (LHV)", f"{result['System efficiency percent']:.1f} %")
col_e4.metric("Net Heat Demand", f"{result['Net heat demand kW']:.2f} kW")

duty_parts = [
    ("Vaporisation", result["Vaporisation duty kW"]),
    ("Feed preheat", result["Feed preheat duty kW"]),
    ("Reaction", result["Reaction heat kW"]),
    ("Heat loss", result["Heat loss kW"]),
]

df_duty = pd.DataFrame(
    [{"Duty": "Heat duty", "Component": name, "kW": value} for name, value in duty_parts]
)

fig_duty = px.bar(
    df_duty,
    x="kW",
    y="Duty",
    color="Component",
    orientation="h",
    title="Where the Heat Duty Goes",
)

fig_duty.update_layout(
    xaxis_title="Heat duty (kW)",
    yaxis_title="",
    legend_title="",
    height=240,
    hovermode="y unified",
)

st.plotly_chart(fig_duty, width="stretch")

st.caption(
    f"The reaction itself is only {result['Reaction heat kW'] / result['Total heat duty kW'] * 100:.0f} % "
    "of the duty. Vaporising the liquid ammonia and heating it to reactor temperature "
    "account for most of the rest, and those are the two terms the recuperator can give "
    f"back. Recuperation returns {result['Recovered heat kW']:.2f} kW and the tail gas "
    f"rejected by the purifier is worth another {result['Tail gas fuel kW']:.2f} kW of fuel, "
    f"leaving {result['H2 burned kg/h']:.3f} kg/h of product hydrogen to be burned."
)

st.header("Safety Assessment")

col_status, col_reason = st.columns([1, 2])

with col_status:
    if result["Status"] == "Safe":
        st.success("SAFE")
    elif result["Status"] == "Warning":
        st.warning("WARNING")
    else:
        st.error("SHUTDOWN")

with col_reason:
    st.write("**Reason:**")
    st.write(result["Status reason"])

st.info(f"Recommended action: {result['Recommended action']}")

st.header("Start-up and Load Following")

st.write(
    "Everything above is the settled operating point. A unit at a refuelling site "
    "spends a real part of its life warming up or chasing demand, and while it does "
    "the product is off specification. This section integrates the reactor thermal "
    "balance over time to show how long that lasts."
)

with st.expander("Transient scenario settings"):
    tcol1, tcol2, tcol3 = st.columns(3)
    sim_duration = tcol1.slider("Simulated duration min", 30, 300, 130, step=10)
    max_ramp = tcol1.slider("Max ramp rate °C/min", 1.0, 30.0, 10.0)
    burner_capacity = tcol2.slider("Burner capacity kW", 5.0, 80.0, 30.0)
    thermal_mass = tcol2.slider("Reactor thermal mass kg", 10.0, 300.0, 40.0)
    feed_admission = tcol3.slider("Feed admission temperature °C", 200, 600, 400)
    apply_turndown = tcol3.checkbox("Include a load change", value=True)
    turndown_fraction = tcol3.slider("Turndown to fraction of feed", 0.1, 1.0, 0.4)


# The transient model sets its own temperature, space velocity and heat loss,
# so those are held back from the steady-state inputs it inherits.
transient_inherited = {
    key: value
    for key, value in model_inputs.items()
    if key not in ("temperature_c", "ghsv_h", "heat_loss_percent")
}


@st.cache_data(show_spinner=False)
def run_transient(
    duration, ramp, capacity, mass, admission, turndown, fraction,
    feed, target_c, design_ghsv, inherited,
):
    """Cached so moving an unrelated slider does not re-integrate the run."""
    history = simulate(
        duration_min=duration,
        dt_s=5,
        target_temperature_c=target_c,
        max_ramp_c_per_min=ramp,
        burner_capacity_kw=capacity,
        thermal_mass_kg=mass,
        feed_admission_c=admission,
        nh3_feed_kg_h=feed,
        design_ghsv_h=design_ghsv,
        turndown_start_min=duration * 0.7 if turndown else None,
        turndown_end_min=duration * 0.82 if turndown else None,
        turndown_fraction=fraction,
        **inherited,
    )
    return history, summarise(history, target_temperature_c=target_c)


history, transient = run_transient(
    sim_duration,
    max_ramp,
    burner_capacity,
    thermal_mass,
    feed_admission,
    apply_turndown,
    turndown_fraction,
    nh3_feed,
    temperature,
    ghsv,
    transient_inherited,
)

df_transient = pd.DataFrame(history)

tm1, tm2, tm3, tm4 = st.columns(4)

tm1.metric(
    "Time to Temperature",
    f"{transient['Time to temperature min']:.0f} min"
    if transient["Reached temperature"]
    else "not reached",
    delta=f"limited by {transient['Limited by'].lower()}",
    delta_color="off",
)
tm2.metric(
    "Time to On-Spec Product",
    f"{transient['Time to on-specification min']:.0f} min"
    if transient["Reached specification"]
    else "never",
)
tm3.metric(
    "NH3 Fed Before On-Spec",
    f"{transient['Ammonia fed before on-spec kg']:.2f} kg",
)
tm4.metric("Peak Firing", f"{transient['Peak firing kW']:.1f} kW")

if not transient["Reached temperature"]:
    st.error(
        "**The burner cannot reach the setpoint.** Firing sits at its limit and the "
        "reactor stalls below temperature. Increase burner capacity, cut heat losses, "
        "or improve the recuperator."
    )
elif not transient["Reached specification"]:
    st.warning(
        "**The product never reaches specification.** The reactor gets hot, but the "
        "purification train cannot meet ISO 14687 even at steady state, so warming up "
        "does not rescue it. This is a separation problem, not a start-up problem."
    )

fig_temp_time = make_subplots(specs=[[{"secondary_y": True}]])

fig_temp_time.add_trace(
    go.Scatter(
        x=df_transient["Time min"], y=df_transient["Setpoint C"],
        name="Setpoint (°C)", mode="lines", line=dict(dash="dot"),
    ),
    secondary_y=False,
)
fig_temp_time.add_trace(
    go.Scatter(
        x=df_transient["Time min"], y=df_transient["Temperature C"],
        name="Bed temperature (°C)", mode="lines",
    ),
    secondary_y=False,
)
fig_temp_time.add_trace(
    go.Scatter(
        x=df_transient["Time min"], y=df_transient["Fired kW"],
        name="Firing rate (kW)", mode="lines",
    ),
    secondary_y=True,
)

fig_temp_time.update_layout(
    title="Reactor Temperature and Firing Rate Over Time",
    xaxis_title="Time (min)",
    legend_title="",
    hovermode="x unified",
)
fig_temp_time.update_yaxes(title_text="Temperature (°C)", secondary_y=False)
fig_temp_time.update_yaxes(title_text="Firing rate (kW)", rangemode="tozero", secondary_y=True)

st.plotly_chart(fig_temp_time, width="stretch")

fig_quality_time = make_subplots(specs=[[{"secondary_y": True}]])

fig_quality_time.add_trace(
    go.Scatter(
        x=df_transient["Time min"], y=df_transient["Conversion percent"],
        name="Conversion (%)", mode="lines",
    ),
    secondary_y=False,
)
fig_quality_time.add_trace(
    go.Scatter(
        x=df_transient["Time min"],
        # Break the line while the reactor is dry rather than drawing a
        # meaningless zero on a log axis.
        y=df_transient["NH3 product ppmv"].where(df_transient["NH3 feed kg/h"] > 0),
        name="NH3 in product (ppmv)", mode="lines",
    ),
    secondary_y=True,
)

fig_quality_time.add_hline(
    y=ISO_14687_LIMITS["nh3_ppmv"],
    line_dash="dash",
    line_color="firebrick",
    annotation_text="ISO 14687 limit",
    annotation_position="top right",
    secondary_y=True,
)

fig_quality_time.update_layout(
    title="Conversion and Product Quality Over Time",
    xaxis_title="Time (min)",
    legend_title="",
    hovermode="x unified",
)
fig_quality_time.update_yaxes(title_text="Conversion (%)", range=[0, 105], secondary_y=False)
fig_quality_time.update_yaxes(
    title_text="NH3 in product (ppmv), log scale", type="log", secondary_y=True
)

st.plotly_chart(fig_quality_time, width="stretch")

st.caption(
    "Ammonia is withheld until the bed is hot enough to crack it, which is why nothing "
    "happens on the quality trace early on. When feed is admitted the endothermic load "
    "arrives faster than the controller learns it, so the bed dips before recovering. "
    "The load change later in the run does the same in reverse. Note that the bed is a "
    "fixed physical size here, so turning the plant down lengthens residence time rather "
    "than shrinking the reactor: space velocity follows the feed instead of setting it."
)

st.header("Live Data and Model Divergence")

st.write(
    "Everything above is prediction. This section is the part that makes the project "
    "a twin rather than a simulator: it reads what the asset actually did, runs the "
    "model on the same measured inputs, and watches the gap. A model that agrees with "
    "the plant tells you nothing. A residual that drifts tells you something changed."
)

uploaded = st.file_uploader(
    "Measurement file (CSV). Leave empty to use the bundled demonstration campaign.",
    type="csv",
)


@st.cache_data(show_spinner=False)
def load_campaign(file_bytes):
    """Read measurements, either uploaded or from the committed campaign."""
    if file_bytes is None:
        return read_csv(CAMPAIGN_PATH), CAMPAIGN_PATH
    text = io.StringIO(file_bytes.decode("utf-8"))
    rows = [
        {field: float(row[field]) for field in CSV_FIELDS}
        for row in csv.DictReader(text)
    ]
    return rows, "uploaded file"


try:
    measurements, source = load_campaign(uploaded.getvalue() if uploaded else None)
except (OSError, KeyError, ValueError) as error:
    st.error(
        f"Could not read the measurement file: {error}. Expected columns: "
        f"{', '.join(CSV_FIELDS)}. Regenerate the bundled campaign with "
        "`python twin.py`."
    )
    measurements, source = [], None

if measurements:

    @st.cache_data(show_spinner=False)
    def analyse(rows, bed_volume):
        reconciled = reconcile(rows, bed_volume_m3=bed_volume, **DEFAULT_PROCESS)
        return reconciled, diagnose(reconciled, **DEFAULT_PROCESS)

    reconciled, findings = analyse(measurements, default_bed_volume_m3())
    df_twin = pd.DataFrame(reconciled)

    st.caption(
        f"{len(measurements):,} samples from {source}, covering "
        f"{measurements[-1]['time_h']:,.0f} operating hours. The measured channels are "
        "flow, temperature, pressure, an outlet ammonia analyser, burner firing and "
        "product flow. Conversion and catalyst activity are **inferred**, not measured."
    )

    if findings["Healthy"]:
        st.success(
            "**No divergence detected.** Residuals sit within noise, so the asset is "
            "behaving as the model says it should."
        )
    else:
        for finding in findings["Findings"]:
            st.warning(finding)

    dc1, dc2, dc3, dc4 = st.columns(4)
    dc1.metric(
        "Estimated Catalyst Activity",
        f"{findings['Estimated activity percent']:.1f} %"
        if findings["Estimated activity percent"] is not None
        else "n/a",
    )
    dc2.metric(
        "Activity Loss per 1000 h",
        f"{findings['Activity loss per 1000 h']:.2f} pp"
        if findings["Activity loss per 1000 h"]
        else "not significant",
    )
    dc3.metric(
        "Off-Spec Threshold",
        f"{findings['Critical activity percent']:.1f} %"
        if findings["Critical activity percent"] is not None
        else "n/a",
    )
    dc4.metric(
        "Catalyst Replacement Due In",
        f"{findings['Hours to catalyst replacement'] / 24:,.0f} days"
        if findings["Hours to catalyst replacement"]
        else "no trend",
    )

    fig_divergence = make_subplots(specs=[[{"secondary_y": True}]])
    fig_divergence.add_trace(
        go.Scatter(
            x=df_twin["time_h"], y=df_twin["nh3_outlet_ppmv"],
            name="Measured NH3 outlet (ppmv)", mode="lines", opacity=0.7,
        ),
        secondary_y=False,
    )
    fig_divergence.add_trace(
        go.Scatter(
            x=df_twin["time_h"], y=df_twin["Predicted NH3 outlet ppmv"],
            name="Model prediction (ppmv)", mode="lines", line=dict(dash="dash"),
        ),
        secondary_y=False,
    )
    fig_divergence.add_trace(
        go.Scatter(
            x=df_twin["time_h"], y=df_twin["Estimated activity percent"],
            name="Inferred catalyst activity (%)", mode="lines",
        ),
        secondary_y=True,
    )
    fig_divergence.update_layout(
        title="What the Plant Did Against What the Model Expected",
        xaxis_title="Operating hours",
        legend_title="",
        hovermode="x unified",
    )
    fig_divergence.update_yaxes(title_text="NH3 at reactor outlet (ppmv)", secondary_y=False)
    fig_divergence.update_yaxes(
        title_text="Inferred activity (%)", range=[0, 120], secondary_y=True
    )

    st.plotly_chart(fig_divergence, width="stretch")

    st.caption(
        "The dashed line is the model running on nameplate parameters. It stays flat, "
        "because nothing in the operating conditions changed. The measurement climbs "
        "away from it, and the gap, converted back into a catalyst activity, is the "
        "diagnosis. Over this campaign conversion falls by roughly a quarter of a "
        "percentage point, which nobody would notice on a trend display, while the "
        "ammonia the purification train has to handle rises by half again."
    )

    fig_residuals = make_subplots(specs=[[{"secondary_y": True}]])
    fig_residuals.add_trace(
        go.Scatter(
            x=df_twin["time_h"], y=df_twin["Conversion residual pp"],
            name="Conversion residual (pp)", mode="lines", opacity=0.8,
        ),
        secondary_y=False,
    )
    fig_residuals.add_trace(
        go.Scatter(
            x=df_twin["time_h"], y=df_twin["Fired residual kW"],
            name="Firing residual (kW)", mode="lines", opacity=0.8,
        ),
        secondary_y=True,
    )
    fig_residuals.add_hline(y=0, line_dash="dot", line_color="grey")
    fig_residuals.update_layout(
        title="Two Residuals, Two Different Faults",
        xaxis_title="Operating hours",
        legend_title="",
        hovermode="x unified",
    )
    fig_residuals.update_yaxes(
        title_text="Measured minus predicted conversion (pp)", secondary_y=False
    )
    fig_residuals.update_yaxes(
        title_text="Measured minus predicted firing (kW)", secondary_y=True
    )

    st.plotly_chart(fig_residuals, width="stretch")

    st.caption(
        "One residual cannot say what is wrong, only that something is. Conversion "
        "falling short of prediction points at the catalyst. Firing running above "
        "prediction at the same duty points at the heat exchanger. Reading them "
        "together separates a fouled recuperator from an ageing catalyst, which a "
        "single overall performance number would confuse."
    )

st.header("Process Flow Diagram")

st.image(
    "Ammonia Process Diagram.png",
    caption="Conceptual process flow diagram of the modular ammonia cracker for decentralized hydrogen production",
    width="stretch",
)

st.header("Chart Analysis")

st.markdown("""
These charts show the sensitivity of the ammonia cracker model to key operating parameters.
Each chart changes one parameter while keeping the other selected dashboard inputs constant.
""")


st.subheader("1. H₂ Production vs NH₃ Feed Rate")

feed_values = list(range(1, 101, 5))
h2_values = [
    ammonia_cracker_model(nh3_feed_kg_h=feed, **model_inputs)["H2 product kg/h"]
    for feed in feed_values
]

df_h2 = pd.DataFrame({
    "NH3 feed rate (kg/h)": feed_values,
    "H2 product (kg/h)": h2_values
})

fig_h2 = px.line(
    df_h2,
    x="NH3 feed rate (kg/h)",
    y="H2 product (kg/h)",
    markers=True,
    title="Hydrogen Production as a Function of Ammonia Feed Rate"
)

fig_h2.update_layout(
    xaxis_title="NH3 feed rate (kg/h)",
    yaxis_title="H2 product flow rate (kg/h)",
    hovermode="x unified"
)

fig_h2.update_xaxes(
    dtick=10,
    rangemode="tozero"
)

fig_h2.update_yaxes(
    rangemode="tozero"
)

st.plotly_chart(fig_h2, width="stretch")

st.caption(
    "Hydrogen output scales linearly with feed because conversion is set by the reactor "
    "operating point, which does not change along this sweep. The slope is the design "
    "yield in kg H2 per kg NH3."
)

st.subheader("2. NH₃ Slip vs Space Velocity")

ghsv_values = [1000 * i for i in range(1, 101)]
slip_rows = []

for value in ghsv_values:
    reactor = predict_conversion(
        temperature_c=temperature,
        pressure_bar=pressure,
        ghsv_h=value,
        catalyst=catalyst,
        catalyst_activity=catalyst_activity / 100,
    )
    slip_rows.append({
        "GHSV (1/h)": value,
        "NH3 slip (%)": (1 - reactor["conversion"]) * 100,
        "Equilibrium floor (%)": (1 - reactor["equilibrium_conversion"]) * 100,
    })

df_slip = pd.DataFrame(slip_rows)

fig_slip = px.line(
    df_slip,
    x="GHSV (1/h)",
    y=["NH3 slip (%)", "Equilibrium floor (%)"],
    log_x=True,
    title="Ammonia Slip as a Function of Space Velocity"
)

fig_slip.update_layout(
    xaxis_title="Space velocity GHSV (1/h), log scale",
    yaxis_title="NH3 slip relative to feed (%)",
    legend_title="",
    hovermode="x unified"
)

fig_slip.update_traces(
    line=dict(dash="dash"), selector=dict(name="Equilibrium floor (%)")
)

fig_slip.update_yaxes(rangemode="tozero")

st.plotly_chart(fig_slip, width="stretch")

st.caption(
    "This is the reactor sizing trade-off. Low space velocity means a large catalyst bed "
    "and low slip. The dashed equilibrium floor is the slip that thermodynamics allows at "
    "this temperature and pressure, and no amount of extra catalyst can go below it. "
    "Where the two curves meet, the reactor is oversized."
)

st.subheader("3. Heat Demand and Hydrogen Cost vs Recuperator Effectiveness")

heat_recovery_values = list(range(0, 100, 5))
heat_rows = []

for value in heat_recovery_values:
    swept = ammonia_cracker_model(
        nh3_feed_kg_h=nh3_feed,
        **{**model_inputs, "heat_recovery_percent": value},
    )
    heat_rows.append({
        "Recuperator effectiveness (%)": value,
        "Net heat demand (kW)": swept["Net heat demand kW"],
        "H2 diverted to burner (%)": swept["H2 burned percent"],
    })

df_heat = pd.DataFrame(heat_rows)

fig_heat = make_subplots(specs=[[{"secondary_y": True}]])

fig_heat.add_trace(
    go.Scatter(
        x=df_heat["Recuperator effectiveness (%)"],
        y=df_heat["Net heat demand (kW)"],
        name="Net heat demand (kW)",
        mode="lines+markers",
    ),
    secondary_y=False,
)

fig_heat.add_trace(
    go.Scatter(
        x=df_heat["Recuperator effectiveness (%)"],
        y=df_heat["H2 diverted to burner (%)"],
        name="H2 diverted to burner (%)",
        mode="lines+markers",
    ),
    secondary_y=True,
)

fig_heat.update_layout(
    title="Effect of Heat Recovery on Duty and on Hydrogen Yield",
    xaxis_title="Recuperator effectiveness (%)",
    legend_title="",
    hovermode="x unified",
)

fig_heat.update_xaxes(dtick=10, range=[0, 95])
fig_heat.update_yaxes(title_text="Net heat demand (kW)", rangemode="tozero", secondary_y=False)
fig_heat.update_yaxes(title_text="H2 diverted to burner (%)", rangemode="tozero", secondary_y=True)

st.plotly_chart(fig_heat, width="stretch")

st.caption(
    "Heat integration is not a comfort feature. Every kilowatt the recuperator fails to "
    "return has to be fired, and the fuel is the product itself, so the right hand axis "
    "is the commercial consequence of the left. This is why a cracker is built around its "
    "heat exchanger rather than around its reactor."
)

st.subheader("4. NH₃ Conversion vs Reactor Temperature")

temperature_values = list(range(400, 760, 10))
conversion_rows = []

for value in temperature_values:
    reactor = predict_conversion(
        temperature_c=value,
        pressure_bar=pressure,
        ghsv_h=ghsv,
        catalyst=catalyst,
        catalyst_activity=catalyst_activity / 100,
    )
    conversion_rows.append({
        "Reactor temperature (°C)": value,
        "Predicted conversion (%)": reactor["conversion"] * 100,
        "Equilibrium ceiling (%)": reactor["equilibrium_conversion"] * 100,
    })

df_temp = pd.DataFrame(conversion_rows)

fig_temp = px.line(
    df_temp,
    x="Reactor temperature (°C)",
    y=["Predicted conversion (%)", "Equilibrium ceiling (%)"],
    title=f"Ammonia Conversion vs Temperature for {catalyst} at {pressure} bar"
)

fig_temp.update_layout(
    xaxis_title="Reactor temperature (°C)",
    yaxis_title="NH3 conversion (%)",
    legend_title="",
    hovermode="x unified"
)

fig_temp.update_xaxes(
    dtick=50,
    range=[400, 750]
)

fig_temp.update_yaxes(
    range=[0, 105]
)

fig_temp.add_vline(
    x=temperature,
    line_dash="dot",
    annotation_text="Operating point",
    annotation_position="top left",
)

st.plotly_chart(fig_temp, width="stretch")

st.caption(
    "The gap between the two curves is the catalyst's shortfall. On the left the reactor is "
    "kinetically limited and conversion climbs steeply with temperature. On the right the "
    "curves merge, the reactor sits on the equilibrium ceiling, and further heating gains "
    "almost nothing while costing fuel and catalyst life. Switching catalyst moves the knee."
)

st.subheader("5. Product NH₃ vs Guard Bed Removal")

guard_values = [90 + i * 0.5 for i in range(20)] + [99.9, 99.95, 99.99]
guard_rows = []

for value in guard_values:
    swept = ammonia_cracker_model(
        nh3_feed_kg_h=nh3_feed,
        **{**model_inputs, "nh3_guard_removal_percent": value},
    )
    guard_rows.append({
        "Guard bed removal (%)": value,
        "NH3 in product (ppmv)": max(swept["NH3 product ppmv"], 1e-6),
    })

df_guard = pd.DataFrame(guard_rows)

fig_guard = px.line(
    df_guard,
    x="Guard bed removal (%)",
    y="NH3 in product (ppmv)",
    log_y=True,
    markers=True,
    title="How Much Guard Bed Duty the Specification Demands",
)

fig_guard.add_hline(
    y=ISO_14687_LIMITS["nh3_ppmv"],
    line_dash="dash",
    line_color="firebrick",
    annotation_text="ISO 14687 limit",
    annotation_position="bottom left",
)

fig_guard.update_layout(
    xaxis_title="Guard bed NH3 removal (%)",
    yaxis_title="NH3 in product (ppmv), log scale",
    hovermode="x unified",
)

st.plotly_chart(fig_guard, width="stretch")

st.caption(
    "Everything on this chart is at the currently selected PSA performance, so the curve "
    "moves when the decontamination factor changes. The two stages multiply, which is the "
    "only reason the specification is reachable at all: neither a scrubber nor a PSA gets "
    "there alone. Where the curve crosses the limit is the guard bed duty this design has "
    "to buy."
)

st.subheader("Summary of Current Operating Point")

summary_df = pd.DataFrame({
    "Parameter": [
        "NH₃ feed rate",
        "Catalyst",
        "Space velocity",
        "Catalyst bed volume",
        "Predicted conversion",
        "Equilibrium ceiling",
        "Limiting regime",
        "NH₃ slip",
        "NH₃ in product",
        "N₂ in product",
        "H₂ purity",
        "ISO 14687 Grade D",
        "H₂ produced",
        "H₂ burned for heat",
        "H₂ net product",
        "Total heat duty",
        "Net heat demand",
        "System efficiency (LHV)",
    ],
    "Value": [
        f"{nh3_feed:.2f} kg/h",
        result["Catalyst"],
        f"{ghsv:,} 1/h",
        f"{result['Catalyst bed volume m3'] * 1000:.2f} L",
        f"{result['Conversion percent']:.3f} %",
        f"{result['Equilibrium conversion percent']:.3f} %",
        result["Limiting regime"],
        f"{result['NH3 slip percent']:.3f} %",
        f"{result['NH3 product ppmv']:,.4g} ppmv",
        f"{result['N2 product ppmv']:,.4g} ppmv",
        f"{result['H2 purity percent']:.5f} %",
        "Pass" if result["Meets ISO 14687"] else f"Fail on {', '.join(result['ISO 14687 failures'])}",
        f"{result['H2 product kg/h']:.3f} kg/h",
        f"{result['H2 burned kg/h']:.3f} kg/h  ({result['H2 burned percent']:.1f} %)",
        f"{result['H2 net kg/h']:.3f} kg/h",
        f"{result['Total heat duty kW']:.2f} kW",
        f"{result['Net heat demand kW']:.2f} kW",
        f"{result['System efficiency percent']:.1f} %",
    ]
})

st.table(summary_df)
