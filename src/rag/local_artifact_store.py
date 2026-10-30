import gzip
import hashlib
import json
import tarfile
import tempfile
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

from rag.vector_store import FactoryVectorStore


class LocalArtifactVectorStore(FactoryVectorStore):
    """Restore verified local artifacts; reuse machine-aware search."""

    def __init__(self):
        root = Path(__file__).resolve().parents[2]
        assets = root / "artifacts" / "rag" / "v1"
        self.client = None
        self._temporary = tempfile.TemporaryDirectory(
            prefix="factory-local-rag-"
        )

        try:
            manifest = json.loads(
                (assets / "manifest.json").read_text(encoding="utf-8")
            )

            if (
                manifest["embedding_model_status"] != "exported_and_verified"
                or manifest["vector_size"] != 384
                or manifest["distance"] != "Cosine"
                or manifest["normalize_embeddings"] is not True
            ):
                raise ValueError("Unexpected artifact configuration.")

            if (
                manifest["points_file"] != "manual_points.jsonl.gz"
                or manifest["embedding_model_archive"]
                != "embedding_model.tar.gz"
            ):
                raise ValueError("Unexpected artifact filenames.")

            for filename, checksum_field in (
                ("manual_points.jsonl.gz", "points_sha256"),
                ("embedding_model.tar.gz", "embedding_model_sha256"),
            ):
                digest = hashlib.sha256()
                with (assets / filename).open("rb") as handle:
                    for block in iter(
                        lambda: handle.read(1024 * 1024), b""
                    ):
                        digest.update(block)
                if digest.hexdigest() != manifest[checksum_field]:
                    raise ValueError(f"Checksum mismatch: {filename}")

            extracted = Path(self._temporary.name)
            with tarfile.open(
                assets / "embedding_model.tar.gz", "r:gz"
            ) as archive:
                archive.extractall(extracted, filter="data")

            self.embedding_model = SentenceTransformer(
                str(extracted / "embedding_model"),
                device="cpu",
                local_files_only=True,
            )
            self.vector_size = (
                self.embedding_model.get_embedding_dimension()
            )
            if self.vector_size != manifest["vector_size"]:
                raise ValueError("Embedding dimension mismatch.")

            self.collection_name = manifest["collection_name"]
            self.knowledge_base_version = manifest["knowledge_base_version"]

            self.client = QdrantClient(":memory:")
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=self.vector_size,
                    distance=Distance.COSINE,
                ),
            )

            with gzip.open(
                assets / "manual_points.jsonl.gz", "rt", encoding="utf-8"
            ) as handle:
                points = [
                    PointStruct(**json.loads(line))
                    for line in handle
                    if line.strip()
                ]

            if len(points) != manifest["point_count"]:
                raise ValueError("Artifact point count mismatch.")

            self.client.upsert(
                collection_name=self.collection_name,
                points=points,
                wait=True,
            )

            count = self.client.count(
                collection_name=self.collection_name,
                exact=True,
            ).count
            if count != manifest["point_count"]:
                raise ValueError("Restored point count mismatch.")

            print(f"Local RAG ready: {count} points")
            print(f"Knowledge-base version: {self.knowledge_base_version}")

        except Exception:
            self.close()
            raise

    def close(self):
        try:
            if self.client is not None:
                self.client.close()
                self.client = None
        finally:
            self._temporary.cleanup()