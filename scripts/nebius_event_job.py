"""One selected-event investigation, independent from the verified five-case batch job."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

from google.cloud import firestore, storage
from nebius_common import BUCKET, MACHINES, PROJECT, report_id, validate_package
from nebius_progress import publish_progress

ROOT = Path(__file__).resolve().parents[1]
INPUTS = [
    'data/yearly_experiment_v3/raw/sensors.csv',
    'data/yearly_experiment_v3/raw/maintenance_history.csv',
    'data/yearly_experiment_v3/raw/machine_logs.csv',
    'artifacts/rag/v1/manifest.json',
    'artifacts/rag/v1/manual_points.jsonl.gz',
    'artifacts/rag/v1/embedding_model.tar.gz',
]


def main():
    if os.getenv('GOOGLE_CLOUD_PROJECT') != PROJECT:
        raise RuntimeError('Wrong project configuration.')
    request_id = os.environ['NEBIUS_REQUEST_ID']
    if not re.fullmatch(r'[0-9a-f]{32}',request_id):
        raise ValueError('Invalid event request.')
    owner = uuid.uuid4().hex
    os.environ['NEBIUS_OWNER_TOKEN'] = owner
    db = firestore.Client(project=PROJECT)
    request = db.collection('nebius_requests').document(request_id)

    @firestore.transactional
    def claim(transaction):
        data = request.get(transaction=transaction).to_dict() or {}
        if data.get('investigation_status') != 'queued':
            return None
        ref = db.collection('nebius_events').document(data['event_id'])
        current = ref.get(transaction=transaction).to_dict() or {}
        if current.get('request_id') != request_id:
            return None
        patch = {'owner_token':owner,'investigation_status':'investigating',
                 'investigation_stage':'loading_inputs','investigation_updated_at':datetime.now(timezone.utc)}
        transaction.set(request,patch,merge=True)
        transaction.set(ref,patch,merge=True)
        return {**data,**patch}

    data = claim(db.transaction())
    if data is None:
        print('Request already claimed/completed; no model calls made.')
        db.close()
        return
    output = ROOT / 'artifacts/nebius/event_runs' / request_id
    output.mkdir(parents=True,exist_ok=True)
    prefix = 'event_outputs/' + request_id
    try:
        if data['machine_id'] not in MACHINES:
            raise ValueError('Unknown machine.')
        with storage.Client(project=PROJECT) as client:
            bucket = client.bucket(BUCKET)
            for name in INPUTS:
                path = ROOT / name
                path.parent.mkdir(parents=True,exist_ok=True)
                bucket.blob('inputs/'+name).download_to_filename(str(path))
            command = [sys.executable,str(ROOT/'scripts/test_sensor_tool.py'),
                       '--machine-id',data['machine_id'],'--cutoff',data['cutoff_time'],
                       '--output-dir',str(output)]
            (output/'request.json').write_text(json.dumps({k:data[k] for k in
                ('event_id','machine_id','cutoff_time','source_run_id','request_id')},indent=2),encoding='utf-8')
            try:
                with (output/'execution.log').open('w',encoding='utf-8') as log:
                    process = subprocess.Popen(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                               text=True,encoding='utf-8',env={**os.environ,'PYTHONUNBUFFERED':'1','PYTHONIOENCODING':'utf-8'})
                    for line in process.stdout:
                        log.write(line);log.flush();print(line,end='',flush=True)
                    code = process.wait()
                if code:
                    raise RuntimeError('Investigator process failed; inspect execution.log.')
            finally:
                for file in output.iterdir():
                    if file.is_file():
                        bucket.blob(prefix+'/'+file.name).upload_from_filename(str(file))
            report_files = list(output.glob('*_report.json'))
            if len(report_files) != 1:
                raise ValueError('Expected exactly one report.')
            report_file = report_files[0]
            package = json.loads(report_file.read_text(encoding='utf-8'))
            trace_file = output / Path(package['source_trace']).name
            trace = json.loads(trace_file.read_text(encoding='utf-8'))
            validate_package(package,trace,data['machine_id'],data['cutoff_time'])
            rid = report_id(prefix+'/'+report_file.name)
            db.collection('nebius_reports').document(rid).set({
                'event_id':data['event_id'],'machine_id':data['machine_id'],'cutoff_time':data['cutoff_time'],
                'report_path':prefix+'/'+report_file.name,'trace_path':prefix+'/'+trace_file.name,
                'created_at':datetime.now(timezone.utc),'status':'completed',
            })
            publish_progress('completed',strict=True,investigation_status='report_ready',
                             investigation_id=rid,investigation_finished_at=datetime.now(timezone.utc),
                             execution_trace=trace['execution_trace'],
                             reassessment_history=trace.get('reassessment_history',[]),
                             stop_reason=trace.get('stop_reason'))
            print('Report ready:',rid)
    except Exception as error:
        publish_progress('failed',strict=True,investigation_status='failed',
                         investigation_reason=f'{type(error).__name__}: investigation did not complete; inspect job logs.',
                         investigation_finished_at=datetime.now(timezone.utc))
        raise
    finally:
        db.close()


if __name__ == '__main__':
    main()
