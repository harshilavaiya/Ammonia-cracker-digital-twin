"""
The layer that makes this a twin rather than a simulator.

A simulator predicts. A twin also listens: it reads what the physical asset
actually did, runs the model on the same inputs, and watches the gap between
the two. That gap is the useful signal. A model that agrees with the plant
tells you nothing new, but a residual that drifts tells you something in the
plant has changed before anyone notices it on a trend display.

The module does three things:

    generate_campaign  invent a plausible measurement history, because there
                       is no real asset attached to this project
    reconcile          run the model on the measured inputs and difference
                       the outputs
    diagnose           turn the residuals into a statement an operator can
                       act on, including an estimate of remaining catalyst life

Only the sensors a real unit would actually have are recorded: flow,
temperature, pressure, an ammonia analyser on the reactor outlet, the burner
firing rate and the product flow. Conversion is not measured directly, it is
derived from the analyser, and space velocity is derived from the flow and the
known bed volume. Getting that boundary right matters, because a twin that
assumes it can measure its own internal states is not one.
"""

import csv
import math
import random
from pathlib import Path

import thermo
from model import CATALYSTS, MW_NH3, V_MOLAR_NORMAL, ammonia_cracker_model

# Sensor noise, one standard deviation.
NOISE = {
    "temperature_c": 2.0,
    "nh3_feed_kg_h": 0.05,
    "pressure_bar": 0.05,
    "nh3_outlet_ppmv_relative": 0.03,
    "fired_kw": 0.25,
    "h2_product_relative": 0.01,
}

CSV_FIELDS = [
    "time_h",
    "nh3_feed_kg_h",
    "temperature_c",
    "pressure_bar",
    "nh3_outlet_ppmv",
    "fired_kw",
    "h2_product_kg_h",
]


def conversion_from_outlet_ppmv(nh3_outlet_ppmv):
    """
    Back out fractional conversion from an outlet ammonia analyser reading.

    For a feed of pure ammonia the outlet holds (1 - x) NH3 in (1 + x) total
    moles, so y = (1 - x) / (1 + x) inverts to x = (1 - y) / (1 + y).
    """
    y = nh3_outlet_ppmv / 1e6
    return (1 - y) / (1 + y)


def estimate_activity(
    measured_conversion, temperature_c, pressure_bar, ghsv_h, catalyst
):
    """
    Estimate the catalyst activity factor implied by a measured conversion.

    The forward model is x = x_eq * (1 - exp(-Da)) with Da = k(T)*a/GHSV, so
    the inversion is closed form:

        approach = x / x_eq
        Da       = -ln(1 - approach)
        a        = Da * GHSV / k(T)

    Returns None when the measurement sits at or above the equilibrium
    ceiling, where the inversion carries no information: any sufficiently
    active catalyst would produce the same reading.
    """
    temperature_k = temperature_c + 273.15
    x_eq = thermo.equilibrium_conversion(temperature_k, pressure_bar)
    approach = measured_conversion / x_eq

    if approach <= 0 or approach >= 1 - 1e-12:
        return None

    damkohler = -math.log(1 - approach)
    params = CATALYSTS[catalyst]
    rate_constant_h = params["pre_exponential_h"] * math.exp(
        -params["activation_energy_J_mol"] / (thermo.R * temperature_k)
    )
    return damkohler * ghsv_h / rate_constant_h


def generate_campaign(
    duration_h=4000,
    sample_interval_h=2,
    nh3_feed_kg_h=10.0,
    temperature_c=600.0,
    pressure_bar=5.0,
    bed_volume_m3=None,
    design_ghsv_h=20_000.0,
    deactivation_time_constant_h=12_000.0,
    fouling_end_effectiveness=0.48,
    design_effectiveness=None,
    seed=20260909,
    **model_kwargs,
):
    """
    Invent a measurement history for a unit that is slowly going off.

    Two faults are injected, neither of which the model is told about:

      * the catalyst loses activity exponentially, which is what catalysts do
      * the recuperator fouls, so heat recovery decays linearly

    Both are deliberately subtle. Over the campaign conversion falls by only a
    fraction of a percentage point, which is invisible on a trend display, yet
    the ammonia leaving the reactor roughly triples. Catching that early is
    the entire argument for running a twin.
    """
    rng = random.Random(seed)

    # Both of these are driven by the fault profile below, so they are taken
    # out of the process parameters a caller may have passed straight through.
    # The recuperator's nameplate effectiveness becomes the campaign's
    # starting point unless one was given explicitly.
    nameplate_effectiveness = model_kwargs.pop("heat_recovery_percent", 60.0) / 100
    model_kwargs.pop("catalyst_activity_percent", None)
    if design_effectiveness is None:
        design_effectiveness = nameplate_effectiveness

    if bed_volume_m3 is None:
        feed_Nm3_h = nh3_feed_kg_h / MW_NH3 * V_MOLAR_NORMAL
        bed_volume_m3 = feed_Nm3_h / design_ghsv_h

    records = []
    time_h = 0.0

    while time_h <= duration_h:
        progress = time_h / duration_h

        activity = math.exp(-time_h / deactivation_time_constant_h)
        effectiveness = design_effectiveness + progress * (
            fouling_end_effectiveness - design_effectiveness
        )

        # The true state of the plant at this moment.
        feed_true = nh3_feed_kg_h
        ghsv_true = feed_true / MW_NH3 * V_MOLAR_NORMAL / bed_volume_m3
        truth = ammonia_cracker_model(
            nh3_feed_kg_h=feed_true,
            temperature_c=temperature_c,
            pressure_bar=pressure_bar,
            ghsv_h=ghsv_true,
            catalyst_activity_percent=activity * 100,
            heat_recovery_percent=effectiveness * 100,
            **model_kwargs,
        )

        records.append(
            {
                "time_h": round(time_h, 3),
                "nh3_feed_kg_h": round(
                    feed_true + rng.gauss(0, NOISE["nh3_feed_kg_h"]), 4
                ),
                "temperature_c": round(
                    temperature_c + rng.gauss(0, NOISE["temperature_c"]), 3
                ),
                "pressure_bar": round(
                    pressure_bar + rng.gauss(0, NOISE["pressure_bar"]), 3
                ),
                "nh3_outlet_ppmv": round(
                    truth["NH3 reactor outlet ppmv"]
                    * (1 + rng.gauss(0, NOISE["nh3_outlet_ppmv_relative"])),
                    3,
                ),
                # What the burner actually had to fire to hold temperature.
                "fired_kw": round(
                    truth["Net heat demand kW"]
                    - truth["Tail gas fuel kW"]
                    + rng.gauss(0, NOISE["fired_kw"]),
                    4,
                ),
                "h2_product_kg_h": round(
                    truth["H2 product kg/h"]
                    * (1 + rng.gauss(0, NOISE["h2_product_relative"])),
                    5,
                ),
            }
        )
        time_h += sample_interval_h

    return records


def write_csv(records, path):
    """Write a campaign to disk in the format read_csv expects."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(records)


def read_csv(path):
    """
    Read a measurement file.

    This is the seam a real deployment would replace. Swapping this for an
    MQTT subscription or a historian query changes nothing downstream, because
    everything after it works on a list of records.
    """
    with open(path, newline="", encoding="utf-8") as handle:
        return [
            {field: float(row[field]) for field in CSV_FIELDS}
            for row in csv.DictReader(handle)
        ]


def reconcile(records, bed_volume_m3, nameplate_activity_percent=100.0, **model_kwargs):
    """
    Run the model against the measurements and difference the two.

    The model is given the measured inputs and its nameplate parameters, which
    is the point: it is asked what a healthy unit would have done under these
    conditions. Where the plant disagrees, the plant has changed.
    """
    # The nameplate value is the whole point of the comparison, so a caller
    # passing the live process settings through does not get to override it.
    model_kwargs.pop("catalyst_activity_percent", None)
    reconciled = []

    for row in records:
        ghsv_h = row["nh3_feed_kg_h"] / MW_NH3 * V_MOLAR_NORMAL / bed_volume_m3
        predicted = ammonia_cracker_model(
            nh3_feed_kg_h=row["nh3_feed_kg_h"],
            temperature_c=row["temperature_c"],
            pressure_bar=row["pressure_bar"],
            ghsv_h=ghsv_h,
            catalyst_activity_percent=nameplate_activity_percent,
            **model_kwargs,
        )

        measured_conversion = conversion_from_outlet_ppmv(row["nh3_outlet_ppmv"])
        predicted_fired_kw = (
            predicted["Net heat demand kW"] - predicted["Tail gas fuel kW"]
        )
        activity = estimate_activity(
            measured_conversion,
            row["temperature_c"],
            row["pressure_bar"],
            ghsv_h,
            model_kwargs.get("catalyst", "Ru/Al2O3"),
        )

        reconciled.append(
            {
                **row,
                "GHSV 1/h": ghsv_h,
                "Measured conversion percent": measured_conversion * 100,
                "Predicted conversion percent": predicted["Conversion percent"],
                "Conversion residual pp": measured_conversion * 100
                - predicted["Conversion percent"],
                "Predicted NH3 outlet ppmv": predicted["NH3 reactor outlet ppmv"],
                "NH3 residual ppmv": row["nh3_outlet_ppmv"]
                - predicted["NH3 reactor outlet ppmv"],
                "Predicted fired kW": predicted_fired_kw,
                "Fired residual kW": row["fired_kw"] - predicted_fired_kw,
                "Estimated activity percent": activity * 100 if activity else None,
            }
        )

    return reconciled


def _slope_per_hour(times_h, values):
    """Least squares slope, in units of value per hour. None if degenerate."""
    points = [(t, v) for t, v in zip(times_h, values) if v is not None]
    if len(points) < 2:
        return None

    n = len(points)
    mean_t = sum(t for t, _ in points) / n
    mean_v = sum(v for _, v in points) / n
    denominator = sum((t - mean_t) ** 2 for t, _ in points)
    if denominator == 0:
        return None
    numerator = sum((t - mean_t) * (v - mean_v) for t, v in points)
    return numerator / denominator


def _tail_mean(values, window):
    tail = [v for v in values[-window:] if v is not None]
    return sum(tail) / len(tail) if tail else None


def critical_activity(
    temperature_c,
    pressure_bar,
    ghsv_h,
    nh3_feed_kg_h=10.0,
    tolerance=1e-4,
    **model_kwargs,
):
    """
    Find the catalyst activity at which the product falls off specification.

    Bisection on activity, which is monotonic in conversion and therefore in
    product purity. The feed rate makes no difference to the answer, since
    purity is a ratio and every stream scales with it, but it is accepted so
    the call can carry the real operating point.

    Returns None when the unit is off specification even with a perfect
    catalyst, since there is then no activity worth reporting.
    """

    model_kwargs.pop("catalyst_activity_percent", None)

    def on_spec(activity_fraction):
        return ammonia_cracker_model(
            nh3_feed_kg_h=nh3_feed_kg_h,
            temperature_c=temperature_c,
            pressure_bar=pressure_bar,
            ghsv_h=ghsv_h,
            catalyst_activity_percent=activity_fraction * 100,
            **model_kwargs,
        )["Meets ISO 14687"]

    if not on_spec(1.0):
        return None
    if on_spec(1e-6):
        return 0.0

    low, high = 1e-6, 1.0
    while high - low > tolerance:
        middle = (low + high) / 2
        if on_spec(middle):
            high = middle
        else:
            low = middle
    return high


def diagnose(
    reconciled,
    window=200,
    conversion_alarm_pp=0.05,
    fired_alarm_kw=0.5,
    min_activity_loss_per_1000h=0.5,
    **model_kwargs
):
    """
    Turn residuals into something an operator can act on.

    Two residuals are watched, because one alone cannot say what is wrong.
    Conversion falling short of prediction points at the catalyst. Firing
    running above prediction points at the heat integration. Reading them
    together separates the two faults, which a single overall performance
    number would confuse.
    """
    model_kwargs.pop("catalyst_activity_percent", None)

    times = [row["time_h"] for row in reconciled]
    conversion_residuals = [row["Conversion residual pp"] for row in reconciled]
    fired_residuals = [row["Fired residual kW"] for row in reconciled]
    activities = [row["Estimated activity percent"] for row in reconciled]

    recent_conversion = _tail_mean(conversion_residuals, window)
    recent_fired = _tail_mean(fired_residuals, window)
    activity_now = _tail_mean(activities, window)
    activity_slope = _slope_per_hour(times, activities)

    findings = []
    if recent_conversion is not None and recent_conversion < -conversion_alarm_pp:
        findings.append(
            "Conversion is running below prediction, which points at loss of "
            "catalyst activity rather than at operating conditions."
        )
    if recent_fired is not None and recent_fired > fired_alarm_kw:
        findings.append(
            "Firing is running above prediction at the same duty, which points "
            "at degraded heat recovery, most likely a fouled recuperator."
        )

    activity_loss_per_1000h = -activity_slope * 1000 if activity_slope else None

    # Project when the catalyst stops holding the product on specification,
    # but only once the decline is big enough to mean something. Noise alone
    # will always fit some slope, and turning that into a replacement date
    # would be false precision dressed up as a maintenance plan.
    hours_to_replacement = None
    threshold_percent = None
    if (
        reconciled
        and activity_now is not None
        and activity_loss_per_1000h is not None
        and activity_loss_per_1000h >= min_activity_loss_per_1000h
    ):
        last = reconciled[-1]
        threshold = critical_activity(
            temperature_c=last["temperature_c"],
            pressure_bar=last["pressure_bar"],
            ghsv_h=last["GHSV 1/h"],
            nh3_feed_kg_h=last["nh3_feed_kg_h"],
            **model_kwargs,
        )
        if threshold is not None:
            threshold_percent = threshold * 100
            remaining = activity_now - threshold_percent
            if remaining > 0:
                hours_to_replacement = remaining / -activity_slope

    return {
        "Recent conversion residual pp": recent_conversion,
        "Recent fired residual kW": recent_fired,
        "Estimated activity percent": activity_now,
        "Activity loss per 1000 h": activity_loss_per_1000h,
        "Critical activity percent": threshold_percent,
        "Hours to catalyst replacement": hours_to_replacement,
        "Findings": findings,
        "Healthy": not findings,
    }


# Default campaign settings, also used by the dashboard so the numbers it
# shows match the file on disk.
DEFAULT_CAMPAIGN = dict(
    duration_h=4000,
    sample_interval_h=2,
    nh3_feed_kg_h=10.0,
    temperature_c=600.0,
    pressure_bar=5.0,
    design_ghsv_h=20_000.0,
)

DEFAULT_PROCESS = dict(
    heat_recovery_percent=60.0,
    h2_recovery_percent=95.0,
    catalyst="Ru/Al2O3",
    nh3_guard_removal_percent=99.9,
    psa_nh3_decontamination_factor=500,
    psa_n2_rejection_percent=99.95,
)

# Anchored to this file rather than the working directory, so the campaign is
# found however the app is launched. A hosted deployment does not necessarily
# start the process in the repository root.
CAMPAIGN_PATH = Path(__file__).resolve().parent / "data" / "plant_campaign.csv"


def default_bed_volume_m3():
    """Bed volume implied by the default campaign's design point."""
    feed_Nm3_h = DEFAULT_CAMPAIGN["nh3_feed_kg_h"] / MW_NH3 * V_MOLAR_NORMAL
    return feed_Nm3_h / DEFAULT_CAMPAIGN["design_ghsv_h"]


if __name__ == "__main__":
    # Regenerate the committed demonstration campaign.
    CAMPAIGN_PATH.parent.mkdir(parents=True, exist_ok=True)
    campaign = generate_campaign(**DEFAULT_CAMPAIGN, **DEFAULT_PROCESS)
    write_csv(campaign, CAMPAIGN_PATH)
    print(f"wrote {len(campaign)} samples to {CAMPAIGN_PATH}")
