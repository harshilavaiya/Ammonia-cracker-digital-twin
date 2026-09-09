# Digital Twin of a Modular Ammonia Cracker

## 1. Project Overview

This project is a simulation-based digital twin of a modular ammonia cracker for decentralized hydrogen production.

The digital twin predicts ammonia conversion from the reactor operating point, then calculates hydrogen production, nitrogen production, ammonia slip, reaction heat demand, heat recovery effect, and basic safety status.

The project is developed using Python and Streamlit.

### Files

| File | Purpose |
| --- | --- |
| `thermo.py` | Ideal-gas heat capacities, equilibrium constant, equilibrium conversion |
| `model.py` | Reactor kinetics, mass and energy balance, safety logic |
| `dashboard.py` | Streamlit user interface and charts |
| `test_model.py` | Test suite, run with `pytest -q` |

### Running

```bash
pip install -r requirements.txt
streamlit run dashboard.py
```

```bash
pytest -q
```

## 2. Motivation

Ammonia is a promising hydrogen carrier because it can store hydrogen in chemical form and can be transported more easily than pure hydrogen gas. At the point of use, ammonia can be cracked into hydrogen and nitrogen.

This project demonstrates how a digital twin can be used to understand and visualize the performance of an ammonia cracking system.

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

The model evaluates this enthalpy at reactor temperature rather than at 25 °C, which
raises it by roughly 18 % at 650 °C.

The model uses this reaction to calculate:

* ammonia conversion and the limiting regime
* hydrogen production
* nitrogen production
* unconverted ammonia, also called NH3 slip
* the full heat duty and how much of it the recuperator returns
* the hydrogen burned to fire the remainder, and the net hydrogen yield

This reaction is the foundation of the mass and energy balance used in the simulation.

## 4. How Conversion Is Predicted

Conversion is not an input to this model. It is calculated from reactor temperature,
pressure, space velocity and catalyst, because two separate limits decide how much
ammonia actually cracks.

### The equilibrium ceiling

The equilibrium constant is obtained from `ΔG°(T) = ΔH°(T) − T·ΔS°(T)`, using
temperature-dependent ideal-gas heat capacities rather than assuming ΔH and ΔS are
constant. For the cracking reaction:

```text
K = (y_N2 · y_H2³ / y_NH3²) · P²
```

Substituting the outlet mole fractions for a feed of pure ammonia at conversion `x`
gives a closed-form solution:

```text
K = 1.6875 · x⁴ · P² / (1 − x²)²
```

The `P²` term is Le Chatelier's principle in action. Cracking produces four moles of
gas from two, so raising the pressure pushes the equilibrium back toward ammonia.
This is a real design tension, because the downstream purification stage wants
pressure while the reactor does not.

Some resulting equilibrium conversions:

| Temperature | 1 bar | 10 bar |
| --- | --- | --- |
| 300 °C | 95.9 % | 73.1 % |
| 400 °C | 99.1 % | 92.3 % |
| 500 °C | 99.7 % | 97.5 % |
| 600 °C | 99.9 % | 99.0 % |

### The kinetic approach

Equilibrium only sets a ceiling. The catalyst decides how close the reactor gets to
that ceiling in the residence time available. The bed is treated as a plug flow
reactor with a lumped first-order rate, for which the approach to equilibrium decays
exponentially with space time:

```text
x = x_eq · (1 − e^(−Da))        Da = k(T) · activity / GHSV
```

`Da` is the Damköhler number, the ratio of residence time to reaction time. Above
roughly `Da = 3` the reactor sits on the equilibrium ceiling and extra catalyst buys
nothing. Below it, ammonia slip is set by reactor size rather than by thermodynamics.
The dashboard reports which of the two limits is binding.

Two catalysts are included. The rate parameters are illustrative rather than
measured: they are chosen so the model reproduces the behaviour reported in the open
literature, and the activation energies sit within the ranges usually quoted.

| Catalyst | Activation energy | Effective from |
| --- | --- | --- |
| Ru/Al₂O₃ | 75 kJ/mol | about 450 °C |
| Ni/Al₂O₃ | 190 kJ/mol | about 650 °C |

A catalyst activity factor between 0 and 1 scales the rate constant, so the effect of
catalyst deactivation over an operating campaign can be explored.

## 5. The Energy Balance

The reaction enthalpy alone understates the heat duty by more than half. Ammonia
arrives as a liquid, so it has to be vaporised and then heated to reactor temperature
before any of it reacts. The duty is the sum of three terms:

| Term | Basis | Share of duty at the default case |
| --- | --- | --- |
| Vaporisation | 23.3 kJ/mol NH₃ | 21 % |
| Feed preheat | ∫Cp dT from storage to reactor temperature | 25 % |
| Reaction | ΔH(T) for the fraction that converts | 49 % |
| Heat loss | user-set percentage | 5 % |

At 10 kg/h of ammonia, 650 °C and 5 bar the total duty is **18.2 kW**, against the
**7.5 kW** that a reaction-only calculation gives. The two sensible terms are the ones
a feed/effluent recuperator can give back, which is why its effectiveness dominates
the design. Recovery is capped by what the feed is able to absorb, since a recuperator
can only preheat the feed.

### Where the heat comes from

Whatever the recuperator does not return has to be fired. The model burns the tail gas
first, because the hydrogen the purifier rejects and the ammonia slip are otherwise
waste, and only then makes up the shortfall from product hydrogen:

```text
H2 burned = (net duty − tail gas credit) / (LHV_H2 × burner efficiency)
net H2    = H2 produced − H2 burned
```

This is the real cost of cracking. At the default operating point the burner takes
**25 %** of the hydrogen, which is in line with the 15–25 % reported for decentralised
units, and it falls as the recuperator improves:

| Recuperator effectiveness | Net duty | H₂ to burner | System efficiency |
| --- | --- | --- | --- |
| 0 % | 18.2 kW | 32.6 % | 73.1 % |
| 40 % | 15.8 kW | 27.5 % | 78.6 % |
| 80 % | 13.3 kW | 22.4 % | 84.1 % |

System efficiency is LHV out over LHV in. Note that cracking is endothermic, so the
hydrogen leaving carries *more* chemical energy than the ammonia entering; the
efficiency falls below 100 % only because the unit burns part of its own product to
supply that energy.

## 6. Chart Analysis

The dashboard includes four chart analyses:

1. **H₂ production vs NH₃ feed rate**
   Hydrogen output scales linearly with feed, because conversion is set by the
   reactor operating point rather than by throughput. The slope is the design yield
   in kg H₂ per kg NH₃.

2. **NH₃ slip vs space velocity**
   The reactor sizing trade-off. Low space velocity means a large catalyst bed and
   low slip. The chart also draws the equilibrium floor, which is the slip that
   thermodynamics allows at the selected temperature and pressure and which no amount
   of extra catalyst can beat. Where the two curves meet, the reactor is oversized.

3. **Heat demand and hydrogen cost vs recuperator effectiveness**
   Net duty on the left axis and the share of hydrogen diverted to the burner on the
   right. Every kilowatt the recuperator fails to return has to be fired, and the fuel
   is the product itself, so the right axis is the commercial consequence of the left.

4. **NH₃ conversion vs reactor temperature**
   Predicted conversion plotted against the equilibrium ceiling. The gap between the
   curves is the catalyst's shortfall. On the left the reactor is kinetically limited
   and conversion climbs steeply with temperature; on the right the curves merge and
   further heating gains almost nothing while costing fuel and catalyst life.
   Switching catalyst moves the knee.

These charts help understand the relationship between operating conditions and system performance.

## 7. Limitations

This is a conceptual model, not a design tool. The main simplifications are:

* NH₃ slip is reported as a percentage of feed. Fuel-cell grade hydrogen is specified
  in ppm, and reaching that specification requires a purification stage that is not
  yet modelled.
* System efficiency is a chemical energy balance only. Compression to storage or
  dispensing pressure and electrical parasitics are excluded, so the reported figure
  is an upper bound.
* The latent heat of ammonia is treated as constant at its normal boiling point value,
  which overstates the vaporisation duty slightly when ammonia is stored warm under
  its own vapour pressure.
* The burner is modelled as an efficiency only. NOx formation from firing a gas that
  carries ammonia is a real permitting concern and is not represented.
* The model is steady state, so start-up, load following and thermal inertia are out
  of scope.
* Kinetic parameters are illustrative and have not been fitted to experimental data.