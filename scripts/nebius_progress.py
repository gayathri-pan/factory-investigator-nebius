"""Optional Firestore progress for selected-event jobs; no effect on local/batch tests."""
import logging
import os
from datetime import datetime, timezone


def publish_progress(stage, strict=False, **changes):
    request_id = os.getenv('NEBIUS_REQUEST_ID')
    if not request_id:
        return
    try:
        from google.cloud import firestore
        from nebius_common import PROJECT
        client = firestore.Client(project=PROJECT)
        try:
            request = client.collection('nebius_requests').document(request_id)
            @firestore.transactional
            def update(transaction):
                data = request.get(transaction=transaction).to_dict() or {}
                if data.get('owner_token') != os.getenv('NEBIUS_OWNER_TOKEN'):
                    raise RuntimeError('Another worker owns the request.')
                ref = client.collection('nebius_events').document(data['event_id'])
                current = ref.get(transaction=transaction).to_dict() or {}
                if current.get('request_id') != request_id:
                    raise RuntimeError('Event belongs to another request.')
                patch = {'investigation_stage':stage,'investigation_updated_at':datetime.now(timezone.utc),**changes}
                transaction.set(request,patch,merge=True)
                transaction.set(ref,patch,merge=True)
            update(client.transaction())
        finally:
            client.close()
    except Exception:
        if strict:
            raise
        logging.exception('Progress update unavailable; investigation may still be running.')
