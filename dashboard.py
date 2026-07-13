import streamlit as st
from model import ammonia_cracker_model

st.set_page_config(page_title="Ammonia Cracker Digital Twin", layout="wide")

st.title("Digital Twin of a Modular Ammonia Cracker")
st.write("Simulation-based model for decentralized hydrogen production from ammonia.")

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

#col1.metric("H2 Product", f"{result['H2 product kg/h']:.3f} kg/h")
col2.metric("H2 Product", f"{result['H2 product Nm3/h']:.2f} Nm³/h")
col3.metric("N2 Production", f"{result['N2 kg/h']:.3f} kg/h")

col4, col5, col6 = st.columns(3)

col4.metric("NH3 Slip", f"{result['NH3 slip kg/h']:.4f} kg/h")
col5.metric("Reaction Heat", f"{result['Reaction heat kW']:.2f} kW")
col6.metric("Net Heat Demand", f"{result['Net heat demand kW']:.2f} kW")

st.header("Safety Status")

if result["Status"] == "Safe":
    st.success("System Status: SAFE")
elif result["Status"] == "Warning":
    st.warning("System Status: WARNING")
else:
    st.error("System Status: SHUTDOWN")

st.header("Process Flow")

st.code("""
NH3 Feed → Evaporator → Preheater → Cracker Reactor → Cooler → NH3 Removal → H2 Purification → H2 Product
""")