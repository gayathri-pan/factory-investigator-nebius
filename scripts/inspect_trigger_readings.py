import hashlib
import json

import pandas as pd

from sensor_context import SENSORS, load_sensor_context, validate_scope


def inspect_trigger_readings(machine_id, cutoff_time):
    cutoff = validate_scope(machine_id, cutoff_time)
    context, readings_hash, source = load_sensor_context(machine_id, cutoff_time)
    window = context.iloc[30:]
    records = [{"timestamp": row.timestamp.isoformat(),
                **{sensor: float(getattr(row, sensor)) for sensor in SENSORS}}
               for row in window.itertuples(index=False)]
    identity = f"{machine_id}|{cutoff.isoformat()}|{readings_hash}|trigger_v2"
    return {
        "evidence_id": "trigger_readings_" + hashlib.sha256(identity.encode()).hexdigest()[:24],
        "source": source,
        "selected_readings_sha256": readings_hash,
        "synthetic": True,
        "machine_id": machine_id,
        "start_time": records[0]["timestamp"],
        "cutoff_time": cutoff.isoformat(),
        "records_returned": len(records),
        "timestamp_spacing": "one minute",
        "sensor_units": "unknown",
        "readings": records,
    }
