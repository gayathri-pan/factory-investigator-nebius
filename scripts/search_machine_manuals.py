import hashlib
import json

from rag.local_artifact_store import LocalArtifactVectorStore
from rag.retriever import FactoryRetriever


def search_machine_manuals(machine_id, cutoff_time):
    # Validate the machine and historical cutoff.
    from datetime import datetime, timezone

    cutoff = datetime.fromisoformat(
        cutoff_time.replace("Z", "+00:00")
    )
    if cutoff.tzinfo is None:
        raise ValueError("Cutoff must include a timezone.")
    cutoff = cutoff.astimezone(timezone.utc).isoformat()

    if machine_id not in {
        "M-101", "M-102", "M-103", "M-104", "M-105"
    }:
        raise ValueError("Unknown machine.")

    query = (
        f"Documentation for {machine_id}: sensor location and subsystem "
        "mapping, sensor calibration, sensor units, "
        "operating limits, and interpretation limitations."
    )

    store = LocalArtifactVectorStore()
    try:
        retriever = FactoryRetriever(top_k=3, vector_store=store)
        candidates = retriever.retrieve(
            query=query,
            machine_id=machine_id,
            include_global=True,
        )

        passages = []
        for item in candidates:
            allowed = item["machine_match"] or (
                item["machine_id"] is None
                and item["machine_specific"] is False
            )
            if not allowed:
                raise ValueError("Out-of-scope manual passage.")

            # Stable passage IDs replace search-local E1/E2/E3.
            identity = json.dumps({
                "kb_version": store.knowledge_base_version,
                "source": item["source"],
                "text": item["text"],
                "machine_id": item["machine_id"],
                "machine_specific": item["machine_specific"],
            }, sort_keys=True).encode("utf-8")

            passages.append({
                **item,
                "evidence_id": (
                    "manual_" + hashlib.sha256(identity).hexdigest()[:16]
                ),
                "file_path": None,
            })

        package_identity = json.dumps({
            "machine_id": machine_id,
            "cutoff_time": cutoff,
            "query": query,
            "passage_ids": [p["evidence_id"] for p in passages],
        }, sort_keys=True).encode("utf-8")

        return {
            "evidence_id": (
                "manual_search_"
                + hashlib.sha256(package_identity).hexdigest()[:16]
            ),
            "source": "local_exported_manual_index",
            "synthetic": True,
            "machine_id": machine_id,
            "cutoff_time": cutoff,
            "knowledge_base_version": store.knowledge_base_version,
            "query": query,
            "records_returned": len(passages),
            "status": (
                "passages_found" if passages else "no_matching_passages"
            ),
            "passages": passages,
            "limitations": [
                "Demo manuals are not verified OEM instructions.",
                "Document availability at the historical cutoff is unknown.",
                "Retrieval relevance does not establish claim support.",
                "Documentation does not confirm the event's root cause.",
            ],
        }
    finally:
        store.close()
