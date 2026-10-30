"""Separate-project dashboard; read-only historical source, Nebius reports and jobs."""
import hashlib
import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import firebase_admin
from firebase_admin import auth
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from google.cloud import bigquery, firestore, run_v2, storage
from pydantic import BaseModel, Field

from nebius_common import (BUCKET, DEMO_PREFIX, MACHINES, PROJECT, case_event,
                           investigation_scope, report_id, timestamp, validate_package)

if os.getenv('GOOGLE_CLOUD_PROJECT', PROJECT) != PROJECT:
    raise RuntimeError('Nebius dashboard project configuration mismatch.')
SOURCE_DATASET = f'{PROJECT}.factory_ai_investigator'
firebase_admin.initialize_app(options={'projectId': PROJECT})
db = firestore.Client(project=PROJECT)
bq = bigquery.Client(project=PROJECT, location='asia-south1')
gcs = storage.Client(project=PROJECT)
jobs = run_v2.JobsClient()
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
SENSORS = ('temperature', 'vibration', 'pressure', 'rpm', 'power_consumption')


@app.middleware('http')
async def no_cache(request, call_next):
    response = await call_next(request)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


def authorized(authorization: str = Header(default='')):
    scheme, _, token = authorization.partition(' ')
    if scheme.lower() != 'bearer' or not token:
        raise HTTPException(401, 'Sign in required.')
    try:
        claims = auth.verify_id_token(token)
    except Exception:
        raise HTTPException(401, 'Sign-in could not be verified. Please sign in again.')
    if claims.get('firebase', {}).get('sign_in_provider') != 'google.com' or not claims.get('email_verified'):
        raise HTTPException(403, 'Sign in with a verified Google account.')
    return claims['uid']


def query(sql, params=()):
    # This client can run billed jobs in the new project; source access is read-only IAM.
    if not sql.lstrip().upper().startswith('SELECT'):
        raise ValueError('Historical source queries must be read-only SELECTs.')
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter(*p) for p in params],
        maximum_bytes_billed=2_000_000_000,
    )
    return [dict(r.items()) for r in bq.query(sql, job_config=config, location='asia-south1').result(timeout=45)]


def check_machine(machine):
    if machine not in MACHINES:
        raise HTTPException(400, 'Unknown machine.')


def download_json(path):
    return json.loads(gcs.bucket(BUCKET).blob(path).download_as_text(timeout=45))


@lru_cache(maxsize=1)
def demo_catalog():
    cases = download_json(DEMO_PREFIX + '/input_cases.json')
    if len(cases) != 5 or {r['machine_id'] for r in cases} != set(MACHINES):
        raise ValueError('Invalid verified demo cases.')
    events = {e['event_id']: e for e in map(case_event, cases)}
    reports = {}
    for blob in gcs.list_blobs(BUCKET, prefix=DEMO_PREFIX + '/', timeout=45):
        if not blob.name.endswith('_report.json'):
            continue
        package = json.loads(blob.download_as_text(timeout=45))
        source_trace = package['source_trace']
        if '/' in source_trace or '\\' in source_trace:
            raise ValueError('Invalid report trace filename.')
        trace_path = blob.name.rsplit('/', 1)[0] + '/' + source_trace
        trace = download_json(trace_path)
        validate_package(package, trace, package['machine_id'], package['cutoff_time'])
        reports[report_id(blob.name)] = {
            'report_path': blob.name, 'trace_path': trace_path,
            'package': package, 'trace': trace,
            'created_at': blob.updated,
        }
    return events, reports


def get_event(event_id):
    if re.fullmatch(r'case_[0-9a-f]{64}', event_id):
        event = demo_catalog()[0].get(event_id)
        if event is None:
            raise HTTPException(404, 'Demo window not found.')
        return event
    if not re.fullmatch(r'evt_[0-9a-f]{64}', event_id):
        raise HTTPException(400, 'Invalid event ID.')
    rows = query(f'SELECT * FROM `{SOURCE_DATASET}.anomaly_events` WHERE event_id=@id LIMIT 2', [('id','STRING',event_id)])
    if len(rows) != 1:
        raise HTTPException(404 if not rows else 409, 'Event not found or duplicated.')
    rows[0]['scope_label'] = 'First flagged window of grouped historical event'
    return rows[0]


def demo_saved(event):
    _, cutoff = investigation_scope(event)
    catalog, saved_reports = demo_catalog()
    matching_case = next((case for case in catalog.values()
                          if case['machine_id'] == event['machine_id']
                          and timestamp(case['first_detected_at']) == cutoff), None)
    if matching_case is None or any(event.get(key) != matching_case.get(key)
                                    for key in ('source_run_id','model_version','partition')):
        return None, None
    for rid, entry in saved_reports.items():
        package = entry['package']
        if package['machine_id'] == event['machine_id'] and timestamp(package['cutoff_time']) == cutoff:
            return rid, entry
    return None, None


def context_adapter(package, trace):
    items = list(trace['evidence'].values())
    logs = [r for item in items if 'trigger_window_records_found' in item for r in item.get('records', [])]
    calibration = [r for item in items if item['evidence_id'].startswith('calibration_') for r in item.get('records', [])]
    manuals = [p for item in items for p in item.get('passages', [])]
    return {
        'technical_evidence': manuals, 'machine_logs': logs,
        'maintenance_history': calibration, 'historical_incidents': [],
        'investigation_cutoff': package['cutoff_time'],
        'agent_trace': trace, 'structured_report': package,
    }


def get_report_entry(rid):
    if not re.fullmatch(r'inv_[0-9a-f]{64}', rid):
        raise HTTPException(400, 'Invalid report ID.')
    saved = db.collection('nebius_reports').document(rid).get(timeout=20)
    if saved.exists:
        record = saved.to_dict()
        path = record['report_path']
        if not path.startswith('event_outputs/') or not record['trace_path'].startswith('event_outputs/'):
            raise HTTPException(409, 'Unexpected saved report location.')
        package, trace = download_json(path), download_json(record['trace_path'])
        validate_package(package, trace, record['machine_id'], record['cutoff_time'])
        return {**record, 'package': package, 'trace': trace}
    entry = demo_catalog()[1].get(rid)
    if entry is None:
        raise HTTPException(404, 'Saved report not found.')
    return entry


@app.get('/health')
@app.get('/api/health')
def health():
    return {'status': 'ready', 'project': PROJECT, 'version': 'nebius-dashboard-v1'}


@app.get('/api/machines')
def machines(uid=Depends(authorized)):
    metadata = query(f'SELECT * FROM `{SOURCE_DATASET}.factory_machines` ORDER BY machine_id')
    counts = query(f'SELECT machine_id, COUNT(*) AS event_count FROM `{SOURCE_DATASET}.anomaly_events` GROUP BY machine_id')
    by_id = {r['machine_id']: r['event_count'] for r in counts}
    return {'machines': [{**m, 'event_count': by_id.get(m['machine_id'],0), 'live_available':False}
                         for m in metadata if m['machine_id'] in MACHINES]}


@app.get('/api/events')
def events(machine_id: str = Query(...), uid=Depends(authorized)):
    check_machine(machine_id)
    rows = query(f'SELECT * FROM `{SOURCE_DATASET}.anomaly_events` WHERE machine_id=@machine ORDER BY start_time DESC,event_id LIMIT 101', [('machine','STRING',machine_id)])
    demos = [e for e in demo_catalog()[0].values() if e['machine_id'] == machine_id]
    return {'events': demos + rows[:100], 'historical_count':len(rows[:100]), 'truncated':len(rows)>100}


@app.get('/api/machines/{machine_id}/records')
def records(machine_id: str, uid=Depends(authorized)):
    check_machine(machine_id)
    p = [('machine','STRING',machine_id)]
    return {'maintenance_history':query(f'SELECT * FROM `{SOURCE_DATASET}.maintenance_history` WHERE machine_id=@machine ORDER BY date DESC,maintenance_id LIMIT 101',p),
            'historical_incidents':query(f'SELECT * FROM `{SOURCE_DATASET}.historical_incidents` WHERE machine_id=@machine ORDER BY date DESC,incident_id LIMIT 101',p)}


@app.get('/api/events/{event_id}/context')
def context(event_id: str, uid=Depends(authorized)):
    event = get_event(event_id)
    start, cutoff = investigation_scope(event)
    machine = event['machine_id']
    wp = [('machine','STRING',machine),('start','TIMESTAMP',start),('end','TIMESTAMP',cutoff)]
    hp = [('machine','STRING',machine),('day','DATE',start.date())]
    aggs = ','.join(f'MIN({s}) AS min_{s},MAX({s}) AS max_{s},AVG({s}) AS mean_{s}' for s in SENSORS)
    summary = query(f'SELECT COUNT(*) AS sensor_readings_found,{aggs} FROM `{SOURCE_DATASET}.sensors` WHERE machine_id=@machine AND timestamp BETWEEN @start AND @end',wp)[0]
    readings = query(f'SELECT timestamp,machine_id,{",".join(SENSORS)} FROM `{SOURCE_DATASET}.sensors` WHERE machine_id=@machine AND timestamp BETWEEN @start AND @end ORDER BY timestamp LIMIT 31',wp)
    logs = query(f'SELECT * FROM `{SOURCE_DATASET}.machine_logs` WHERE machine_id=@machine AND timestamp BETWEEN @start AND @end ORDER BY timestamp LIMIT 201',wp)
    maintenance = query(f'SELECT * FROM `{SOURCE_DATASET}.maintenance_history` WHERE machine_id=@machine AND date<@day ORDER BY date DESC,maintenance_id LIMIT 21',hp)
    incidents = query(f'SELECT * FROM `{SOURCE_DATASET}.historical_incidents` WHERE machine_id=@machine AND date<@day ORDER BY date DESC,incident_id LIMIT 21',hp)
    return {'anomaly_event':event,'sensor_summary':summary,'readings':readings[:30],
            'readings_truncated':len(readings)>30,'machine_logs':logs[:200],
            'maintenance_history':maintenance[:20],'historical_incidents':incidents[:20],
            'investigation_cutoff':cutoff,'trigger_start':start,
            'scope_label':event.get('scope_label','First alert snapshot'),
            'note':'Background context is available here. The agent trace separately identifies evidence actually obtained by tools.'}


def public_status(data):
    keys = ('event_id','machine_id','investigation_status','investigation_stage','investigation_id',
            'investigation_reason','investigation_updated_at','investigation_finished_at',
            'dispatch_status','execution_trace','reassessment_history','cutoff_time','stop_reason')
    return {k:data[k] for k in keys if k in data}


@app.get('/api/events/{event_id}/investigation')
def status(event_id: str, uid=Depends(authorized)):
    event = get_event(event_id)
    snapshot = db.collection('nebius_events').document(event_id).get(timeout=20)
    if snapshot.exists:
        data = snapshot.to_dict()
        # Requests are never automatically repeated if an execution becomes unobservable.
        when = data.get('investigation_updated_at') or data.get('created_at')
        if data.get('investigation_status') in ('queued','investigating') and when and datetime.now(timezone.utc)-when > timedelta(minutes=35):
            data = {**data, 'investigation_status':'needs_review',
                    'investigation_reason':'No recent progress. Check the Cloud Run execution before retrying; the job may still be active.'}
        return public_status(data)
    rid, entry = demo_saved(event)
    if rid:
        return {'event_id':event_id,'machine_id':event['machine_id'],'investigation_id':rid,
                'investigation_status':'report_ready','investigation_stage':'completed',
                'cutoff_time':entry['package']['cutoff_time'],'execution_trace':entry['trace']['execution_trace'],
                'reassessment_history':entry['trace'].get('reassessment_history',[]),
                'stop_reason':entry['trace'].get('stop_reason')}
    return {'event_id':event_id,'investigation_status':'not_requested','investigation_stage':'not_started'}


@app.get('/api/events/{event_id}/reports')
def event_reports(event_id: str, uid=Depends(authorized)):
    current = status(event_id,uid)
    if current.get('investigation_id'):
        return {'reports':[{'investigation_id':current['investigation_id'],'status':'completed'}]}
    return {'reports':[]}


@app.get('/api/reports/{rid}')
def report(rid: str, uid=Depends(authorized)):
    entry = get_report_entry(rid)
    package, trace = entry['package'], entry['trace']
    # Markdown was saved alongside validated structured output.
    path = entry['report_path'][:-5] + '.md'
    markdown = gcs.bucket(BUCKET).blob(path).download_as_text(timeout=45)
    return {'investigation_id':rid,'machine_id':package['machine_id'],'status':'completed',
            'created_at':entry.get('created_at'),'report_markdown':markdown,
            'context_json':json.dumps(context_adapter(package,trace)),
            'structured_report':package,'agent_trace':trace}


class HistoricalStart(BaseModel):
    retry: bool = False


@firestore.transactional
def prepare(transaction, event, uid, retry):
    ref = db.collection('nebius_events').document(event['event_id'])
    current = ref.get(transaction=transaction).to_dict() or {}
    state = current.get('investigation_status')
    if state in ('queued','investigating','report_ready','needs_review'):
        return current, False
    if state == 'failed' and not retry:
        return current, False
    control = db.collection('nebius_controls').document('global')
    limits = control.get(transaction=transaction).to_dict() or {}
    now = datetime.now(timezone.utc)
    if limits.get('next_allowed_at',now) > now:
        raise HTTPException(429,'Please wait 30 seconds between new investigations.')
    day = now.date().isoformat()
    count = int(limits.get('count',0)) if limits.get('day') == day else 0
    if count >= int(os.getenv('NEBIUS_DAILY_LIMIT','20')):
        raise HTTPException(429,'The demo daily investigation limit has been reached. Saved reports remain available.')
    _, cutoff = investigation_scope(event)
    request_id = uuid.uuid4().hex
    data = {'event_id':event['event_id'],'machine_id':event['machine_id'],
            'cutoff_time':cutoff.isoformat(),'source_run_id':event.get('source_run_id'),
            'request_id':request_id,'requested_by':uid,'investigation_status':'queued',
            'investigation_stage':'queued','dispatch_status':'pending',
            'created_at':now,'investigation_updated_at':now,
            'execution_trace':[],'reassessment_history':[]}
    transaction.set(db.collection('nebius_requests').document(request_id),data)
    transaction.set(ref,data)
    transaction.set(control,{'day':day,'count':count+1,'next_allowed_at':now+timedelta(seconds=30)})
    return data, True


@app.post('/api/events/{event_id}/investigate',status_code=202)
def investigate(event_id: str, body: HistoricalStart, uid=Depends(authorized)):
    event = get_event(event_id)
    rid, entry = demo_saved(event)
    if rid:
        return status(event_id,uid)
    data, launch = prepare(db.transaction(),event,uid,body.retry)
    if not launch:
        return public_status(data)
    request_id = data['request_id']
    ref = db.collection('nebius_events').document(event_id)
    try:
        operation = jobs.run_job(request={
            'name':f'projects/{PROJECT}/locations/asia-south1/jobs/nebius-investigate-event',
            'overrides':{'container_overrides':[{'env':[{'name':'NEBIUS_REQUEST_ID','value':request_id}]}]},
        },retry=None,timeout=30)
        # Update only dispatch metadata; the worker may already be investigating.
        ref.update({'dispatch_status':'submitted','operation_name':operation.operation.name},timeout=20)
    except Exception:
        logging.exception('Event-job dispatch failed or outcome is unknown.')
        ref.update({'dispatch_status':'unknown','investigation_reason':
                    'Start outcome unknown. Check progress and the Cloud Run execution; do not launch duplicates.'},timeout=20)
    return public_status(ref.get(timeout=20).to_dict() or data)


class EngineerReview(BaseModel):
    status: str = Field(pattern=r'^(reviewed|needs_follow_up)$')
    note: str = Field(min_length=1,max_length=2000)


def review_ref(rid,uid):
    return db.collection('nebius_reviews').document(hashlib.sha256(f'{rid}|{uid}'.encode()).hexdigest())


def public_review(data,uid):
    owner = data.get('reviewer_uid')
    return {'reviewer_label':'Reviewer '+hashlib.sha256(str(owner).encode()).hexdigest()[:10],
            'is_yours':owner==uid,'status':data.get('status'),'note':data.get('note',''),
            'updated_at':data.get('updated_at')}


@app.get('/api/reports/{rid}/review')
def reviews(rid: str,uid=Depends(authorized)):
    get_report_entry(rid)
    from google.cloud.firestore_v1.base_query import FieldFilter
    own = review_ref(rid,uid).get(timeout=20)
    rows = list(db.collection('nebius_reviews').where(filter=FieldFilter('investigation_id','==',rid)).limit(101).stream(timeout=20))
    values = [public_review(r.to_dict(),uid) for r in rows[:100]]
    values.sort(key=lambda r:str(r.get('updated_at') or ''),reverse=True)
    return {'review':public_review(own.to_dict(),uid) if own.exists else None,
            'reviews':values,'truncated':len(rows)>100}


@app.post('/api/reports/{rid}/review')
def save_review(rid: str,body: EngineerReview,uid=Depends(authorized)):
    get_report_entry(rid)
    if not body.note.strip():
        raise HTTPException(400,'Add a review note.')
    ref = review_ref(rid,uid)
    ref.set({'investigation_id':rid,'reviewer_uid':uid,'status':body.status,
             'note':body.note.strip(),'updated_at':firestore.SERVER_TIMESTAMP},timeout=20)
    saved = ref.get(timeout=20)
    if not saved.exists:
        raise HTTPException(503,'Review could not be read back. Refresh before retrying.')
    return {'status':'saved','review':public_review(saved.to_dict(),uid)}
