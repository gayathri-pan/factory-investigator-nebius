"""Offline boundary tests with generated fixtures; no model or cloud calls."""
import os
from pathlib import Path
import tempfile

import pandas as pd

from sensor_context import SENSORS
from compare_sensor_windows import compare_sensor_windows
from inspect_trigger_readings import inspect_trigger_readings
from get_prior_calibration_records import get_prior_calibration_records
from get_prior_machine_logs import get_prior_machine_logs


def must_fail(fn):
    try:
        fn()
    except (ValueError, FileNotFoundError):
        return
    raise AssertionError("Invalid data/scope was accepted")


def main():
    cutoff = pd.Timestamp("2026-11-17T11:49:00Z")
    with tempfile.TemporaryDirectory() as name:
        directory = Path(name)
        rows = []
        for number in range(101, 106):
            for i, timestamp in enumerate(pd.date_range(cutoff-pd.Timedelta(minutes=59), periods=61, freq="min")):
                rows.append({"machine_id": f"M-{number}", "timestamp": timestamp.isoformat(),
                             **{sensor: float(number+i) for sensor in SENSORS}})
        original = pd.DataFrame(rows)
        path = directory / "sensors.csv"
        original.to_csv(path, index=False)
        os.environ["NEBIUS_SENSOR_PATH"] = str(path)
        ids = set()
        for number in range(101, 106):
            machine = f"M-{number}"
            result = compare_sensor_windows(machine, cutoff.isoformat())
            readings = inspect_trigger_readings(machine, cutoff.isoformat())
            assert result["comparisons"]["temperature"]["trigger_mean_minus_reference_mean"] == 30
            assert readings["records_returned"] == 30
            assert all(pd.Timestamp(row["timestamp"]) <= cutoff for row in readings["readings"])
            assert result["selected_readings_sha256"] == readings["selected_readings_sha256"]
            ids.add(result["evidence_id"])
        assert len(ids) == 5
        before = compare_sensor_windows("M-103", cutoff.isoformat())
        changed = original.copy()
        changed.loc[(changed.machine_id == "M-103") & (changed.timestamp > cutoff.isoformat()), "temperature"] = 99999
        changed.to_csv(path, index=False)
        assert compare_sensor_windows("M-103", cutoff.isoformat())["evidence_id"] == before["evidence_id"]
        changed = original.copy()
        changed.loc[(changed.machine_id == "M-103") & (changed.timestamp == cutoff.isoformat()), "temperature"] = 999
        changed.to_csv(path, index=False)
        assert compare_sensor_windows("M-103", cutoff.isoformat())["evidence_id"] != before["evidence_id"]
        for invalid in [original.drop(index=125), pd.concat([original, original.iloc[[125]]]),
                        original.assign(temperature=float("nan"))]:
            invalid.to_csv(path, index=False)
            must_fail(lambda: compare_sensor_windows("M-103", cutoff.isoformat()))
        original.to_csv(path, index=False)
        must_fail(lambda: compare_sensor_windows("M-999", cutoff.isoformat()))
        must_fail(lambda: compare_sensor_windows("M-103", "2026-11-17T11:49:00"))
        must_fail(lambda: compare_sensor_windows("M-103", "2026-11-17T11:49:30Z"))
        compressed = directory / "sensors.csv.gz"
        original.to_csv(compressed, index=False, compression="gzip")
        os.environ["NEBIUS_SENSOR_PATH"] = str(compressed)
        assert compare_sensor_windows("M-103", cutoff.isoformat())["selected_readings_sha256"] == before["selected_readings_sha256"]
        maintenance = directory / "maintenance.csv"
        pd.DataFrame([
            {"maintenance_id": "A", "machine_id": "M-104", "date": "2026-11-16", "maintenance_type": "Calibration"},
            {"maintenance_id": "B", "machine_id": "M-104", "date": "2026-11-17", "maintenance_type": "Calibration"},
            {"maintenance_id": "C", "machine_id": "M-103", "date": "2026-11-16", "maintenance_type": "Calibration"},
        ]).to_csv(maintenance, index=False)
        os.environ["NEBIUS_MAINTENANCE_PATH"] = str(maintenance)
        records = get_prior_calibration_records("M-104", cutoff.isoformat())
        assert [row["maintenance_id"] for row in records["records"]] == ["A"]
        assert get_prior_calibration_records("M-105", cutoff.isoformat())["records_returned"] == 0
        logs = directory / "logs.csv"
        pd.DataFrame([
            {"machine_id": machine, "timestamp": time, "component": "drive", "message": "test"}
            for machine, time in [("M-104", "2026-11-17T10:50:00Z"), ("M-104", "2026-11-17T11:49:00Z"),
                                  ("M-104", "2026-11-17T11:50:00Z"), ("M-103", "2026-11-17T11:49:00Z")]
        ]).to_csv(logs, index=False)
        os.environ["NEBIUS_LOGS_PATH"] = str(logs)
        records = get_prior_machine_logs("M-104", cutoff.isoformat())
        assert records["records_found"] == 2 and records["trigger_window_records_found"] == 1
        assert all(row["machine_id"] == "M-104" for row in records["records"])
        assert get_prior_machine_logs("M-105", cutoff.isoformat())["records_found"] == 0
    print("PASS: five-machine arithmetic, IDs, shared snapshot, future exclusion, changed readings,")
    print("missing/duplicate/nonfinite rejection, machine/time scope, gzip, history and log boundaries.")
    print("Synthetic test fixtures only; real datasets, retrieval and Nemotron calls were not executed.")


if __name__ == "__main__":
    main()
