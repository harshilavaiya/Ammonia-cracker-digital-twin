# Digital Twin of a Modular Ammonia Cracker

## 1. Project Overview

This project is a simulation-based digital twin of a modular ammonia cracker for decentralized hydrogen production.

The digital twin calculates hydrogen production, nitrogen production, ammonia slip, reaction heat demand, heat recovery effect, and basic safety status based on user-defined operating conditions.

The project is developed using Python and Streamlit.

## 2. Motivation

Ammonia is a promising hydrogen carrier because it can store hydrogen in chemical form and can be transported more easily than pure hydrogen gas. At the point of use, ammonia can be cracked into hydrogen and nitrogen.

This project demonstrates how a digital twin can be used to understand and visualize the performance of an ammonia cracking system.

## 3. Main Reaction

## 3. Main Reaction

The main chemical reaction in this project is ammonia cracking:

```text
2 NH3 → N2 + 3 H2
```

This reaction shows that ammonia decomposes into nitrogen and hydrogen. For every 2 moles of ammonia, the reactor produces 1 mole of nitrogen and 3 moles of hydrogen.

Ammonia cracking is an endothermic reaction, which means that heat must be supplied to the reactor for the reaction to occur.

The approximate reaction heat is:

```text
ΔH ≈ +92.4 kJ per 2 mol NH3
ΔH ≈ +46.2 kJ per mol NH3
```

In this digital twin, the value of 46.2 kJ/mol NH3 is used to estimate the reaction heat demand of the ammonia cracker.

The model uses this reaction to calculate:

* hydrogen production
* nitrogen production
* unconverted ammonia, also called NH3 slip
* reaction heat demand
* net heat demand after heat recovery

This reaction is the foundation of the mass and energy balance used in the simulation.

