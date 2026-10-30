"""Read only the requested machine and 60-minute context; never use labels."""
import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SENSORS = ["temperature", "vibration", "pressure", "rpm", "power_consumption"]
MACHINES = {f"M-{number}" for number in range(101, 106)}


def validate_scope(machine_id, cutoff_time):
    if machine_id not in MACHINES:
        raise ValueError("Expected a machine from M-101 through M-105.")
    cutoff = pd.Timestamp(cutoff_time)
    if pd.isna(cutoff) or cutoff.tzinfo is None:
        raise ValueError("Cutoff must include a timezone.")
    cutoff = cutoff.tz_convert("UTC")
    if cutoff != cutoff.floor("min"):
        raise ValueError("Cutoff must align to a minute.")
    return cutoff


def sensor_path():
    path = Path(os.getenv("NEBIUS_SENSOR_PATH", "data/yearly_experiment_v3/raw/sensors.csv"))
    return (path if path.is_absolute() else ROOT / path).resolve()


@lru_cache(maxsize=16)
def _read_context(path_string, file_size, modified_ns, machine_id, cutoff_string):
    path = Path(path_string)
    cutoff = pd.Timestamp(cutoff_string)
    start = cutoff - pd.Timedelta(minutes=59)
    parts = []
    for chunk in pd.read_csv(path, usecols=["machine_id", "timestamp", *SENSORS],
                             dtype={"machine_id": "string"}, chunksize=100000):
        chunk = chunk.loc[chunk["machine_id"].str.strip() == machine_id].copy()
        if chunk.empty:
            continue
        chunk["machine_id"] = chunk["machine_id"].str.strip()
        chunk["timestamp"] = pd.to_datetime(chunk["timestamp"], utc=True, errors="raise")
        if chunk["timestamp"].isna().any():
            raise ValueError("Missing sensor timestamp.")
        parts.append(chunk.loc[chunk["timestamp"].between(start, cutoff)])
    if not parts:
        raise ValueError(f"No sensor readings for {machine_id} in requested scope.")
    selected = pd.concat(parts, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    expected = pd.date_range(start, cutoff, freq="min")
    if not pd.DatetimeIndex(selected["timestamp"]).equals(expected):
        raise ValueError("Expected exactly 60 consecutive readings; missing/duplicate timestamps.")
    selected[SENSORS] = selected[SENSORS].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(selected[SENSORS].to_numpy(dtype=float)).all():
        raise ValueError("Non-finite sensor values.")
    after = path.stat()
    if (after.st_size, after.st_mtime_ns) != (file_size, modified_ns):
        raise ValueError("Sensor source changed during reading; retry with a fixed snapshot.")
    canonical = [{"machine_id": machine_id, "timestamp": row.timestamp.isoformat(),
                  **{sensor: float(getattr(row, sensor)) for sensor in SENSORS}}
                 for row in selected.itertuples(index=False)]
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()
    return selected, digest


def load_sensor_context(machine_id, cutoff_time):
    cutoff = validate_scope(machine_id, cutoff_time)
    path = sensor_path()
    stat = path.stat()
    frame, digest = _read_context(str(path), stat.st_size, stat.st_mtime_ns,
                                  machine_id, cutoff.isoformat())
    return frame.copy(deep=True), digest, str(path)
