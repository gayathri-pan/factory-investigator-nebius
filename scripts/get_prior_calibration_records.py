import hashlib
import io
import json
import os
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "data/yearly_experiment_v3/raw/maintenance_history.csv"


def get_prior_calibration_records(machine_id, cutoff_time):
    from sensor_context import validate_scope
    cutoff = validate_scope(machine_id, cutoff_time)
    if cutoff.tzinfo is None:
        raise ValueError("Cutoff must include a timezone.")
    cutoff = cutoff.tz_convert("UTC")

    # Read one immutable snapshot of the source file.
    source_path = Path(os.getenv("NEBIUS_MAINTENANCE_PATH", SOURCE))
    if not source_path.is_absolute():
        source_path = ROOT / source_path
    raw = source_path.read_bytes()
    data = pd.read_csv(
        io.BytesIO(raw),
        dtype=str,
        keep_default_na=False,
    )

    required = {
        "maintenance_id",
        "machine_id",
        "date",
        "maintenance_type",
    }
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    data["machine_id"] = data["machine_id"].str.strip()
    machine = data[data["machine_id"] == machine_id].copy()

    # Preserve date-only semantics; reject malformed record dates.
    if not machine["date"].str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
        raise ValueError("Expected maintenance dates as YYYY-MM-DD.")

    dates = pd.to_datetime(
        machine["date"], format="%Y-%m-%d", errors="raise"
    )

    calibration = (
        machine["maintenance_type"].str.strip().str.casefold()
        == "calibration"
    )

    # Same-day records cannot establish ordering relative to the alert.
    selected = machine[
        calibration & (dates.dt.date < cutoff.date())
    ].sort_values(
        ["date", "maintenance_id"],
        ascending=[False, True],
    )

    truncated = len(selected) > 20
    records = [
        {
            key: value if value.strip() else None
            for key, value in row.items()
        }
        for row in selected.head(20).to_dict(orient="records")
    ]

    source_hash = hashlib.sha256(raw).hexdigest()
    identity = f"{machine_id}|{cutoff.isoformat()}|{source_hash}"

    return {
        "evidence_id": (
            "calibration_"
            + hashlib.sha256(identity.encode()).hexdigest()[:16]
        ),
        "source": str(source_path.resolve()),
        "source_sha256": source_hash,
        "synthetic": True,
        "machine_id": machine_id,
        "cutoff_time": cutoff.isoformat(),
        "date_exclusive_upper_bound": cutoff.date().isoformat(),
        "records_returned": len(records),
        "truncated": truncated,
        "status": "records_found" if records else "no_matching_records",
        "records": records,
        "limitations": [
            "Only records explicitly typed Calibration were selected.",
            "Same-day and later records were excluded.",
            "Record dates do not prove when their contents became available.",
            "Calibration history does not establish current sensor health.",
        ],
    }
