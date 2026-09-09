"""
Thermodynamics for ammonia cracking.

    2 NH3  <->  N2 + 3 H2      dH(298 K) = +91.8 kJ per 2 mol NH3

This module provides ideal-gas heat capacities, the temperature dependent
equilibrium constant, and the equilibrium conversion of ammonia. It contains
no process logic, so it can be tested against textbook values on its own.

All gases are treated as ideal. The reference pressure is 1 bar.
"""

import math

R = 8.314  # J/(mol*K)

# Ideal-gas heat capacity coefficients for Cp = a + b*T + c*T^2 + d*T^3,
# with Cp in J/(mol*K) and T in K. Valid from roughly 273 K to 1500 K.
# Standard polynomial fits (Reid, Prausnitz and Poling).
CP_COEFFS = {
    "NH3": (27.31, 2.383e-2, 1.707e-5, -1.185e-8),
    "N2": (31.15, -1.357e-2, 2.680e-5, -1.168e-8),
    "H2": (27.14, 9.274e-3, -1.381e-5, 7.645e-9),
}

T_REF = 298.15  # K

# Standard state values for 2 NH3 -> N2 + 3 H2 at 298.15 K.
# dH from dHf(NH3, g) = -45.9 kJ/mol.
# dS from S(N2) = 191.6, S(H2) = 130.7, S(NH3) = 192.8 J/(mol*K).
DH_RXN_REF = 91800.0  # J per 2 mol NH3
DS_RXN_REF = 198.1    # J/(K * 2 mol NH3)

# Latent heat of vaporisation of ammonia at its normal boiling point of
# -33.3 C, in J/mol (1371 kJ/kg). Treated as constant, which overstates the
# duty slightly when ammonia is stored warm under its own vapour pressure.
DH_VAP_NH3 = 23_300.0

# Lower heating values in J/mol, used for the burner and the efficiency figure.
LHV = {
    "H2": 241_800.0,
    "NH3": 316_800.0,
}

# Stoichiometric coefficients for the cracking direction, products positive.
STOICH = {"NH3": -2, "N2": 1, "H2": 3}


def _delta_coeffs():
    """Reaction-weighted sum of the Cp coefficients, per 2 mol NH3."""
    return tuple(
        sum(nu * CP_COEFFS[species][i] for species, nu in STOICH.items())
        for i in range(4)
    )


DCP_COEFFS = _delta_coeffs()


def cp(species, temperature_k):
    """Ideal-gas heat capacity in J/(mol*K)."""
    a, b, c, d = CP_COEFFS[species]
    t = temperature_k
    return a + b * t + c * t**2 + d * t**3


def enthalpy_change(species, t1_k, t2_k):
    """Sensible enthalpy change in J/mol when heating from t1_k to t2_k."""
    return _integral_cp(CP_COEFFS[species], t1_k, t2_k)


def _integral_cp(coeffs, t1, t2):
    """Integral of Cp dT from t1 to t2, in J/mol."""
    a, b, c, d = coeffs
    return (
        a * (t2 - t1)
        + b / 2 * (t2**2 - t1**2)
        + c / 3 * (t2**3 - t1**3)
        + d / 4 * (t2**4 - t1**4)
    )


def _integral_cp_over_t(coeffs, t1, t2):
    """Integral of (Cp / T) dT from t1 to t2, in J/(mol*K)."""
    a, b, c, d = coeffs
    return (
        a * math.log(t2 / t1)
        + b * (t2 - t1)
        + c / 2 * (t2**2 - t1**2)
        + d / 3 * (t2**3 - t1**3)
    )


def reaction_enthalpy(temperature_k):
    """Reaction enthalpy in J per 2 mol NH3 at the given temperature."""
    return DH_RXN_REF + _integral_cp(DCP_COEFFS, T_REF, temperature_k)


def reaction_entropy(temperature_k):
    """Reaction entropy in J/(K * 2 mol NH3) at the given temperature."""
    return DS_RXN_REF + _integral_cp_over_t(DCP_COEFFS, T_REF, temperature_k)


def gibbs_energy(temperature_k):
    """Standard Gibbs energy of reaction in J per 2 mol NH3."""
    return reaction_enthalpy(temperature_k) - temperature_k * reaction_entropy(
        temperature_k
    )


def equilibrium_constant(temperature_k):
    """
    Dimensionless equilibrium constant for cracking, K = exp(-dG / RT).

    K is large at high temperature, which is why cracking needs heat.
    """
    return math.exp(-gibbs_energy(temperature_k) / (R * temperature_k))


def equilibrium_conversion(temperature_k, pressure_bar):
    """
    Fractional equilibrium conversion of NH3, between 0 and 1.

    Starting from 1 mol of pure NH3 with conversion x, the outlet holds
    (1 - x) NH3, x/2 N2 and 3x/2 H2, so 1 + x moles in total. Substituting
    those mole fractions into

        K = (y_N2 * y_H2**3 / y_NH3**2) * P**2

    gives K = 1.6875 * x**4 * P**2 / (1 - x**2)**2, which solves in closed
    form. The P**2 term is Le Chatelier: cracking makes four moles out of
    two, so raising the pressure pushes the equilibrium back toward ammonia.
    """
    k = equilibrium_constant(temperature_k)
    # u = x**2 / (1 - x**2)
    u = math.sqrt(k / 1.6875) / pressure_bar
    return math.sqrt(u / (1 + u))
