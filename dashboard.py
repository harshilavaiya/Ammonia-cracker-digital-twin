import streamlit as st
import pandas as pd
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
st.write("The following charts show how key operating parameters affect hydrogen production, ammonia slip, and heat demand.")

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
    "NH₃ feed rate kg/h": feed_values,
    "H₂ product kg/h": h2_values
})

st.line_chart(df_h2.set_index("NH₃ feed rate kg/h"))

st.caption(
    "This chart shows how hydrogen production increases with ammonia feed rate at the selected conversion and purification recovery."
)

st.subheader("2. NH₃ Slip vs Conversion")

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
    "NH₃ conversion %": conversion_values,
    "NH₃ slip %": slip_values
})

st.line_chart(df_slip.set_index("NH₃ conversion %"))

st.caption(
    "This chart shows that ammonia slip decreases strongly as ammonia conversion approaches 100%."
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
    "Heat recovery efficiency %": heat_recovery_values,
    "Net heat demand kW": net_heat_values
})

st.line_chart(df_heat.set_index("Heat recovery efficiency %"))

st.caption(
    "This chart shows how heat recovery reduces the external heat demand of the ammonia cracker."
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
































