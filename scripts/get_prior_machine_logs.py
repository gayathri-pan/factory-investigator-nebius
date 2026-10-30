import hashlib
import io
import json
import os
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "data/yearly_experiment_v3/raw/machine_logs.csv"


def get_prior_machine_logs(machine_id, cutoff_time):
    from sensor_context import validate_scope
    cutoff = validate_scope(machine_id, cutoff_time)
    if cutoff.tzinfo is None:
        raise ValueError("Cutoff must include a timezone.")
    cutoff = cutoff.tz_convert("UTC")

    # Bounded search: trigger window plus the preceding 30 minutes.
    search_start = cutoff - pd.Timedelta(minutes=59)
    trigger_start = cutoff - pd.Timedelta(minutes=29)

    source_path = Path(os.getenv("NEBIUS_LOGS_PATH", SOURCE))
    if not source_path.is_absolute():
        source_path = ROOT / source_path
    raw = source_path.read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()

    data = pd.read_csv(
        io.BytesIO(raw),
        dtype=str,
        keep_default_na=False,
    )

    required = {"machine_id", "timestamp", "component", "message"}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    data["machine_id"] = data["machine_id"].str.strip()
    machine = data[data["machine_id"] == machine_id].copy()

    times = pd.to_datetime(
        machine["timestamp"], utc=True, errors="raise"
    )
    if times.isna().any():
        raise ValueError("Missing log timestamps.")

    machine["_parsed_time"] = times
    selected = machine[
        times.between(search_start, cutoff)
    ].sort_values("_parsed_time", kind="stable")

    inside_count = int(
        (selected["_parsed_time"] >= trigger_start).sum()
    )

    records = []
    for source_row, row in selected.head(50).iterrows():
        timestamp = row["_parsed_time"]
        identity = f"{source_hash}|{source_row}"

        record = {
            key: value if value.strip() else None
            for key, value in row.items()
            if key != "_parsed_time"
        }
        record.update({
            "log_id": (
                "log_"
                + hashlib.sha256(identity.encode()).hexdigest()[:16]
            ),
            "timestamp": timestamp.isoformat(),
            "scope": (
                "trigger_window"
                if timestamp >= trigger_start
                else "preceding_window"
            ),
        })
        records.append(record)

    identity = f"{machine_id}|{cutoff.isoformat()}|{source_hash}"

    return {
        "evidence_id": (
            "machine_logs_"
            + hashlib.sha256(identity.encode()).hexdigest()[:16]
        ),
        "source": str(source_path.resolve()),
        "source_sha256": source_hash,
        "synthetic": True,
        "machine_id": machine_id,
        "search_start": search_start.isoformat(),
        "trigger_start": trigger_start.isoformat(),
        "cutoff_time": cutoff.isoformat(),
        "records_found": len(selected),
        "trigger_window_records_found": inside_count,
        "preceding_window_records_found": len(selected) - inside_count,
        "records_returned": len(records),
        "truncated": len(selected) > 50,
        "status": (
            "records_found" if records else "no_matching_records"
        ),
        "records": records,
        "limitations": [
            "Search covers only the stated machine and time interval.",
            "Preceding-window logs are labelled separately.",
            "Missing logs do not prove that nothing happened.",
            "Log messages do not independently establish root cause.",
            "Timestamps without an offset are interpreted as UTC.",
        ],
    }
