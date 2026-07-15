import streamlit as st
import pandas as pd
import plotly.express as px
from model import ammonia_cracker_model


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

    Approximate reaction heat:

    **ΔH ≈ +92.4 kJ per 2 mol NH₃**  
    **ΔH ≈ +46.2 kJ per mol NH₃**

    In this digital twin, the value **46.2 kJ/mol NH₃** is used to estimate the reaction heat demand.

    The model uses this reaction to calculate:

    - Hydrogen production
    - Nitrogen production
    - NH₃ slip
    - Reaction heat demand
    - Net heat demand after heat recovery
    """)
st.sidebar.header("Input Parameters")

nh3_feed = st.sidebar.slider("NH3 feed rate kg/h", 1.0, 100.0, 10.0)
conversion = st.sidebar.slider("NH3 conversion %", 70.0, 99.9, 98.0)
temperature = st.sidebar.slider("Reactor temperature °C", 500, 750, 650)
pressure = st.sidebar.slider("Pressure bar", 1.0, 10.0, 5.0)
heat_recovery = st.sidebar.slider("Heat recovery efficiency %", 0.0, 80.0, 60.0)
h2_recovery = st.sidebar.slider("H2 purification recovery %", 70.0, 99.0, 95.0)

result = ammonia_cracker_model(
    nh3_feed_kg_h=nh3_feed,
    conversion_percent=conversion,
    heat_recovery_percent=heat_recovery,
    h2_recovery_percent=h2_recovery,
    temperature_c=temperature,
    pressure_bar=pressure
)

st.header("Main Results")

col1, col2, col3 = st.columns(3)

col1.metric("H2 Production", f"{result['H2 product kg/h']:.3f} kg/h")
col2.metric("H2 Production", f"{result['H2 product Nm3/h']:.2f} Nm³/h")
col3.metric("N2 Production", f"{result['N2 kg/h']:.3f} kg/h")

col4, col5, col6 = st.columns(3)

col4.metric("NH3 Slip", f"{result['NH3 slip kg/h']:.4f} kg/h")
col5.metric("NH3 Slip", f"{result['NH3 slip percent']:.2f} %")
col6.metric("Reaction Heat Demand", f"{result['Reaction heat kW']:.2f} kW")

col7 = st.columns(1)[0]

col7.metric("Net Heat Demand", f"{result['Net heat demand kW']:.2f} kW")

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
    use_container_width=True
)

st.header("Chart Analysis")

st.markdown("""
These charts show the sensitivity of the ammonia cracker model to key operating parameters. 
Each chart changes one parameter while keeping the other selected dashboard inputs constant.
""")


st.subheader("1. H₂ Production vs NH₃ Feed Rate")

feed_values = list(range(1, 101, 5))
h2_values = []

for feed in feed_values:
    temp_result = ammonia_cracker_model(
        nh3_feed_kg_h=feed,
        conversion_percent=conversion,
        heat_recovery_percent=heat_recovery,
        h2_recovery_percent=h2_recovery,
        temperature_c=temperature,
        pressure_bar=pressure
    )
    h2_values.append(temp_result["H2 product kg/h"])

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

st.plotly_chart(fig_h2, use_container_width=True)

st.caption(
    "This chart shows the hydrogen product flow rate calculated from ammonia feed rate at the selected conversion and H2 recovery."
)

st.subheader("2. NH₃ Slip vs NH₃ Conversion")

conversion_values = [x / 10 for x in range(900, 1000, 5)]
slip_values = []

for conv in conversion_values:
    temp_result = ammonia_cracker_model(
        nh3_feed_kg_h=nh3_feed,
        conversion_percent=conv,
        heat_recovery_percent=heat_recovery,
        h2_recovery_percent=h2_recovery,
        temperature_c=temperature,
        pressure_bar=pressure
    )
    slip_values.append(temp_result["NH3 slip percent"])

df_slip = pd.DataFrame({
    "NH3 conversion (%)": conversion_values,
    "NH3 slip (%)": slip_values
})

fig_slip = px.line(
    df_slip,
    x="NH3 conversion (%)",
    y="NH3 slip (%)",
    markers=True,
    title="Ammonia Slip as a Function of Ammonia Conversion"
)

fig_slip.update_layout(
    xaxis_title="NH3 conversion (%)",
    yaxis_title="NH3 slip relative to feed (%)",
    hovermode="x unified"
)

fig_slip.update_xaxes(
    dtick=1,
    range=[90, 100]
)

fig_slip.update_yaxes(
    rangemode="tozero"
)

st.plotly_chart(fig_slip, use_container_width=True)

st.caption(
    "This chart shows that ammonia slip decreases as ammonia conversion increases. Lower NH3 slip is important for downstream purification and safety."
)

st.subheader("3. Net Heat Demand vs Heat Recovery Efficiency")

heat_recovery_values = list(range(0, 85, 5))
net_heat_values = []

for hr in heat_recovery_values:
    temp_result = ammonia_cracker_model(
        nh3_feed_kg_h=nh3_feed,
        conversion_percent=conversion,
        heat_recovery_percent=hr,
        h2_recovery_percent=h2_recovery,
        temperature_c=temperature,
        pressure_bar=pressure
    )
    net_heat_values.append(temp_result["Net heat demand kW"])

df_heat = pd.DataFrame({
    "Heat recovery efficiency (%)": heat_recovery_values,
    "Net heat demand (kW)": net_heat_values
})

fig_heat = px.line(
    df_heat,
    x="Heat recovery efficiency (%)",
    y="Net heat demand (kW)",
    markers=True,
    title="Effect of Heat Recovery on Net Heat Demand"
)

fig_heat.update_layout(
    xaxis_title="Heat recovery efficiency (%)",
    yaxis_title="Net heat demand (kW)",
    hovermode="x unified"
)

fig_heat.update_xaxes(
    dtick=10,
    range=[0, 80]
)

fig_heat.update_yaxes(
    rangemode="tozero"
)

st.plotly_chart(fig_heat, use_container_width=True)

st.caption(
    "This chart shows how increasing heat recovery efficiency reduces the external heat demand of the ammonia cracker."
)
st.subheader("4. Estimated NH₃ Conversion vs Reactor Temperature")

temperature_values = [500, 550, 600, 650, 700, 750]
conversion_estimates = [70, 85, 95, 98, 99, 99.5]

df_temp = pd.DataFrame({
    "Reactor temperature (°C)": temperature_values,
    "Estimated NH3 conversion (%)": conversion_estimates
})

fig_temp = px.line(
    df_temp,
    x="Reactor temperature (°C)",
    y="Estimated NH3 conversion (%)",
    markers=True,
    title="Estimated Ammonia Conversion as a Function of Reactor Temperature"
)

fig_temp.update_layout(
    xaxis_title="Reactor temperature (°C)",
    yaxis_title="Estimated NH3 conversion (%)",
    hovermode="x unified"
)

fig_temp.update_xaxes(
    dtick=50,
    range=[500, 750]
)

fig_temp.update_yaxes(
    range=[60, 100]
)

st.plotly_chart(fig_temp, use_container_width=True)

st.caption(
    "This simplified chart shows the assumed relationship between reactor temperature and ammonia conversion used for conceptual analysis."
)

st.subheader("Summary of Current Operating Point")

summary_df = pd.DataFrame({
    "Parameter": [
        "NH₃ feed rate",
        "Conversion",
        "H₂ product",
        "NH₃ slip",
        "Reaction heat demand",
        "Net heat demand"
    ],
    "Value": [
        f"{nh3_feed:.2f} kg/h",
        f"{conversion:.2f} %",
        f"{result['H2 product kg/h']:.3f} kg/h",
        f"{result['NH3 slip percent']:.2f} %",
        f"{result['Reaction heat kW']:.2f} kW",
        f"{result['Net heat demand kW']:.2f} kW"
    ]
})

st.table(summary_df)
































