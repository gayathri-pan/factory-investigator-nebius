"""Pure identity/scope helpers shared by dashboard and event worker."""
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone

PROJECT = 'factory-investigator-nebius'
BUCKET = 'factory-investigator-nebius-assets-126939332706'
DEMO_PREFIX = ('job_outputs/7070309369d24969850792ca84a9e559/batches/'
               'batch_3033f37a48254d8b8049bda4aac005e7')
MACHINES = tuple(f'M-{n}' for n in range(101, 106))


def timestamp(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timestamp must include timezone.')
    return result.astimezone(timezone.utc)


def report_id(path):
    return 'inv_' + hashlib.sha256(path.encode()).hexdigest()


def case_event(case):
    machine = case['machine_id']
    if machine not in MACHINES:
        raise ValueError('Unknown demo machine.')
    probability, threshold = float(case['fault_probability']), float(case['threshold'])
    if not all(math.isfinite(x) and 0 <= x <= 1 for x in (probability,threshold)):
        raise ValueError('Invalid classifier probability/threshold.')
    if int(case['predicted_fault']) != 1 or probability < threshold:
        raise ValueError('Demonstration must be an actually flagged prediction.')
    if case['model_version'] != 'xgboost_30m_v3_dataset' or case['partition'] != 'test':
        raise ValueError('Expected frozen-model held-out demo prediction.')
    start, end = timestamp(case['start_time']), timestamp(case['cutoff_time'])
    if end - start != timedelta(minutes=29):
        raise ValueError('Invalid demo window.')
    identity = json.dumps([machine, start.isoformat(), end.isoformat(), case['source_run_id']])
    return {
        'event_id': 'case_' + hashlib.sha256(identity.encode()).hexdigest(),
        'machine_id': machine, 'start_time': start, 'end_time': end,
        'first_detected_at': end, 'source_run_id': case['source_run_id'],
        'model_version': case['model_version'], 'partition': case['partition'],
        'flagged_window_count': 1, 'max_fault_probability': float(case['fault_probability']),
        'threshold': float(case['threshold']), 'window_minutes': 30, 'window_step_minutes': 5,
        'scope_label': 'Selected flagged test window; precomputed cloud demonstration',
        'demo_case': True,
    }


def investigation_scope(event):
    start = timestamp(event['start_time'])
    cutoff = timestamp(event.get('first_detected_at') or start + timedelta(minutes=29))
    if cutoff - start != timedelta(minutes=29):
        raise ValueError('First alert must cover exactly 30 one-minute readings.')
    return start, cutoff


def validate_package(package, trace, machine, cutoff):
    if package.get('machine_id') != machine or trace.get('machine_id') != machine:
        raise ValueError('Report machine mismatch.')
    expected = timestamp(cutoff)
    if timestamp(package['cutoff_time']) != expected or timestamp(trace['cutoff_time']) != expected:
        raise ValueError('Report cutoff mismatch.')
    if not package.get('synthetic') or not isinstance(package.get('report'), dict):
        raise ValueError('Expected structured synthetic report.')
    if not isinstance(package.get('sources'), dict) or not trace.get('evidence'):
        raise ValueError('Report lacks traceable evidence.')
