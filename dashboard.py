import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from model import CATALYSTS, ammonia_cracker_model, predict_conversion


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

st.sidebar.subheader("Downstream")
h2_recovery = st.sidebar.slider("H2 purification recovery %", 70.0, 99.0, 95.0)

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
        f"{result['H2 product kg/h']:.3f} kg/h",
        f"{result['H2 burned kg/h']:.3f} kg/h  ({result['H2 burned percent']:.1f} %)",
        f"{result['H2 net kg/h']:.3f} kg/h",
        f"{result['Total heat duty kW']:.2f} kW",
        f"{result['Net heat demand kW']:.2f} kW",
        f"{result['System efficiency percent']:.1f} %",
    ]
})

st.table(summary_df)
