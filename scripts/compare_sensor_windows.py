import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from sensor_context import SENSORS, load_sensor_context, validate_scope


def compare_sensor_windows(machine_id, cutoff_time):
    """Compare the trigger window with the preceding 30 minutes."""
    cutoff = validate_scope(machine_id, cutoff_time)
    selected, readings_hash, source = load_sensor_context(machine_id, cutoff_time)
    trigger_start = cutoff - pd.Timedelta(minutes=29)
    reference_end = trigger_start - pd.Timedelta(minutes=1)
    reference_start = cutoff - pd.Timedelta(minutes=59)

    reference = selected.iloc[:30]
    trigger = selected.iloc[30:]

    def summarize(frame, sensor):
        values = frame[sensor]
        return {
            "count": len(values),
            "minimum": float(values.min()),
            "mean": float(values.mean()),
            "maximum": float(values.max()),
            "first": float(values.iloc[0]),
            "last": float(values.iloc[-1]),
            "last_minus_first": float(
                values.iloc[-1] - values.iloc[0]
            ),
        }

    comparisons = {}

    for sensor in SENSORS:
        earlier = summarize(reference, sensor)
        current = summarize(trigger, sensor)

        comparisons[sensor] = {
            "reference": earlier,
            "trigger": current,
            "trigger_mean_minus_reference_mean": (
                current["mean"] - earlier["mean"]
            ),
        }

    return {
        "evidence_id": "sensor_comparison_" + hashlib.sha256(
            f"{machine_id}|{cutoff.isoformat()}|{readings_hash}|comparison_v2".encode()
        ).hexdigest()[:24],
        "source": source,
        "selected_readings_sha256": readings_hash,
        "synthetic": True,
        "machine_id": machine_id,
        "cutoff_time": cutoff.isoformat(),
        "reference_window": {
            "start": reference_start.isoformat(),
            "end": reference_end.isoformat(),
        },
        "trigger_window": {
            "start": trigger_start.isoformat(),
            "end": cutoff.isoformat(),
        },
        "comparisons": comparisons,
        "limitations": [
            "The reference window is not a verified normal baseline.",
            "Sensor units and operating limits are not established.",
            "Mean differences and endpoint changes do not prove a fault.",
            "No observations after the cutoff were used.",
        ],
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--machine-id", required=True)
    parser.add_argument("--cutoff", required=True)
    args = parser.parse_args()
    print(json.dumps(compare_sensor_windows(args.machine_id, args.cutoff), indent=2, allow_nan=False))
