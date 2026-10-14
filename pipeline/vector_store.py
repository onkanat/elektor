"""
pipeline/vector_store.py - Hardened Qdrant Vector Storage & Semantic Retrieval

Integrates SmartTextChunker for layout-preserving, word-boundary chunking.
Supports dual storage modes (remote server & local embedded), prevents silent :memory:
lock collisions, implements batched embeddings, score-threshold filtering, and
complete payload metadata return.
"""

import sqlite3
import json
import uuid
import time
import logging
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, PayloadSchemaType
from pipeline.llm_client import get_embedding_client
from pipeline.chunking import SmartTextChunker, TextChunk

logger = logging.getLogger(__name__)


class QdrantLockError(RuntimeError):
    """Raised when the local Qdrant database directory cannot be locked due to concurrent access."""
    pass


class ArchiveVectorStore:
    """
    Manages vector storage and semantic retrieval for the Elektor archive.
    Supports local embedded storage, in-memory execution, and remote Qdrant server connections.
    """

    _dimension_cache: dict[str, int] = {}

    def __init__(self, config: dict | str | Path | None = None, config_path: str | Path | None = None):
        if isinstance(config, (str, Path)):
            config_path = config
            config = None

        if config is not None:
            self.config = dict(config)
        else:
            path_to_open = config_path or "config.json"
            if Path(path_to_open).exists():
                with open(path_to_open, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
            else:
                self.config = {}

        self.db_path = self.config.get("db_path", "database/rp01.db")
        db_path_obj = Path(self.db_path)
        if len(db_path_obj.parts) == 1:
            self.db_path = str(Path("database") / self.db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self.qdrant_url = self.config.get("qdrant_url")
        self.qdrant_api_key = self.config.get("qdrant_api_key")
        self.qdrant_db_path = self.config.get("qdrant_db_path", "qdrant_rp01")
        self.ollama_url = self.config.get("ollama_url", "http://localhost:11434")
        self.model_embedding = self.config.get("model_embedding", "nomic-embed-text:latest")
        self.chunk_size = int(self.config.get("chunk_size", 800))
        self.chunk_overlap = int(self.config.get("chunk_overlap", 150))
        self.max_chunks_per_doc = int(self.config.get("max_chunks_per_doc", 500))
        self.collection_name = self.config.get("qdrant_collection_name", "elektor_articles")

        self.chunker = SmartTextChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            max_chunks_per_doc=self.max_chunks_per_doc,
        )

        # Initialize Qdrant Client based on configuration mode
        self.qdrant_client: QdrantClient | None = None
        if self.qdrant_url:
            # Remote Qdrant server mode
            self.qdrant_client = QdrantClient(url=self.qdrant_url, api_key=self.qdrant_api_key)
        elif self.config.get("location") == ":memory:" or self.qdrant_db_path == ":memory:":
            # Hermetic in-memory mode for unit tests and ephemeral runs
            self.qdrant_client = QdrantClient(location=":memory:")
        else:
            # Local embedded on-disk mode (with lock retry & descriptive exception)
            for attempt in range(5):
                try:
                    self.qdrant_client = QdrantClient(path=self.qdrant_db_path)
                    break
                except Exception as e:
                    err_msg = str(e).lower()
                    if "lock" in err_msg or "already accessed" in err_msg:
                        if attempt < 4:
                            time.sleep(1.0)
                        else:
                            raise QdrantLockError(
                                f"Storage folder '{self.qdrant_db_path}' is locked by another process: {e}. "
                                "Close conflicting processes or configure 'qdrant_url' for multi-process server mode."
                            ) from e
                    else:
                        raise

        # Determine embedding dimension with caching
        self.embedding_dim = self.get_embedding_dimension()

        # Ensure collection and payload indices exist
        self.ensure_collection()

    def get_embedding_dimension(self) -> int:
        """Determines embedding dimension using configuration or cache, probing model only once."""
        if "embedding_dim" in self.config:
            dim = int(self.config["embedding_dim"])
            ArchiveVectorStore._dimension_cache[self.model_embedding] = dim
            return dim
        if self.model_embedding in ArchiveVectorStore._dimension_cache:
            return ArchiveVectorStore._dimension_cache[self.model_embedding]

        try:
            client = get_embedding_client(self.config)
            res = client.embeddings.create(model=self.model_embedding, input=["test"])
            dim = len(res.data[0].embedding)
            ArchiveVectorStore._dimension_cache[self.model_embedding] = dim
            return dim
        except Exception as e:
            logger.warning(f"Error testing embedding model dimension: {e}. Defaulting to 768.")
            dim = 768  # nomic-embed-text standard dimension
            ArchiveVectorStore._dimension_cache[self.model_embedding] = dim
            return dim

    def ensure_collection(self) -> None:
        """Creates the Qdrant collection and article_id payload index if they do not already exist."""
        if self.qdrant_client is None:
            return

        collections = [col.name for col in self.qdrant_client.get_collections().collections]
        if self.collection_name not in collections:
            logger.info(f"Creating Qdrant collection: {self.collection_name} (dim={self.embedding_dim})")
            self.qdrant_client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=self.embedding_dim, distance=Distance.COSINE),
            )

        # Create payload index on article_id for fast linked queries
        try:
            self.qdrant_client.create_payload_index(
                collection_name=self.collection_name,
                field_name="article_id",
                field_schema=PayloadSchemaType.INTEGER,
            )
        except Exception as e:
            logger.debug(f"Payload index creation note: {e}")

    def chunk_text(self, text: str, max_chunks: int | None = None) -> list[str]:
        """Splits text into chunks preserving Markdown formatting, indentation, and sentence boundaries."""
        chunks = self.chunker.chunk_text(text, max_chunks=max_chunks)
        return [c.text for c in chunks]

    def chunk_text_objects(self, text: str, max_chunks: int | None = None) -> list[TextChunk]:
        """Splits text into TextChunk dataclass instances with complete character offsets and token estimates."""
        return self.chunker.chunk_text(text, max_chunks=max_chunks)

    def load_to_vector_db(self, limit: int | tuple | None = None, batch_size: int = 32) -> int:
        """
        Reads articles from SQLite, chunks them with SmartTextChunker,
        generates embeddings in batches of batch_size, and upserts into Qdrant.
        Returns total number of successfully embedded articles.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Parse range limit if range format
        start, end = 0, None
        if isinstance(limit, tuple):
            start, end = limit
        elif isinstance(limit, int):
            start, end = 0, limit

        cursor.execute(
            "SELECT id, title, year, filename, extracted_text FROM articles "
            "WHERE extracted_text IS NOT NULL AND extracted_text != '' AND is_embedded = 0"
        )
        rows = cursor.fetchall()

        if not rows:
            logger.info("No new articles to embed.")
            conn.close()
            return 0

        sliced_rows = rows[start:end] if end is not None else rows[start:]
        logger.info(
            f"Loading {len(rows)} non-embedded articles. Processing range [{start}:{end if end is not None else len(rows)}] "
            f"({len(sliced_rows)} articles) into Vector DB..."
        )

        client = get_embedding_client(self.config)
        embedded_count = 0
        points_to_upload: list[PointStruct] = []

        for row in sliced_rows:
            article_id, title, year, filename, text = row
            logger.info(f"Embedding article [{article_id}]: {title}...")

            chunks = self.chunker.chunk_text(text, max_chunks=self.max_chunks_per_doc)
            if not chunks:
                continue

            article_success = True
            for i in range(0, len(chunks), batch_size):
                batch_chunks = chunks[i : i + batch_size]
                texts_to_embed = [c.text for c in batch_chunks]

                try:
                    res = client.embeddings.create(model=self.model_embedding, input=texts_to_embed)
                    vectors = [item.embedding for item in res.data]

                    for chunk_obj, vector in zip(batch_chunks, vectors):
                        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{filename}_chunk_{chunk_obj.chunk_index}"))
                        payload = {
                            "article_id": article_id,
                            "title": title,
                            "year": year,
                            "filename": filename,
                            "chunk_index": chunk_obj.chunk_index,
                            "text": chunk_obj.text,
                        }
                        points_to_upload.append(PointStruct(id=point_id, vector=vector, payload=payload))

                    if len(points_to_upload) >= batch_size:
                        self.qdrant_client.upsert(collection_name=self.collection_name, points=points_to_upload)
                        points_to_upload = []
                except Exception as e:
                    logger.error(f"Failed to embed chunk batch for article {article_id}: {e}")
                    article_success = False
                    break

            if points_to_upload:
                self.qdrant_client.upsert(collection_name=self.collection_name, points=points_to_upload)
                points_to_upload = []

            if article_success:
                cursor.execute("UPDATE articles SET is_embedded = 1 WHERE id = ?", (article_id,))
                conn.commit()
                embedded_count += 1

        conn.close()
        return embedded_count

    def search(self, query: str, top_k: int = 5, score_threshold: float = 0.40) -> list[dict]:
        """
        Performs semantic search over the vectorized articles with score-based filtering.
        Returns list of dicts:
        {
            "score": float,
            "article_id": int | None,
            "chunk_index": int,
            "point_id": str,
            "title": str,
            "year": str | int,
            "filename": str,
            "text": str
        }
        """
        if not query or not query.strip():
            return []

        try:
            client = get_embedding_client(self.config)
            res = client.embeddings.create(model=self.model_embedding, input=[query])
            query_vector = res.data[0].embedding

            if hasattr(self.qdrant_client, "query_points"):
                kwargs = {
                    "collection_name": self.collection_name,
                    "query": query_vector,
                    "limit": top_k,
                }
                if score_threshold is not None:
                    kwargs["score_threshold"] = score_threshold
                q_res = self.qdrant_client.query_points(**kwargs)
                search_results = getattr(q_res, "points", q_res)
            elif hasattr(self.qdrant_client, "search"):
                kwargs = {
                    "collection_name": self.collection_name,
                    "query_vector": query_vector,
                    "limit": top_k,
                }
                if score_threshold is not None:
                    kwargs["score_threshold"] = score_threshold
                search_results = self.qdrant_client.search(**kwargs)
            else:
                raise AttributeError("QdrantClient has neither 'query_points' nor 'search' method.")

            results = []
            for hit in search_results:
                payload = getattr(hit, "payload", {}) or {}
                results.append({
                    "score": float(getattr(hit, "score", 0.0)),
                    "article_id": payload.get("article_id"),
                    "chunk_index": payload.get("chunk_index", 0),
                    "point_id": str(getattr(hit, "id", "")),
                    "title": payload.get("title", ""),
                    "year": payload.get("year", ""),
                    "filename": payload.get("filename", ""),
                    "text": payload.get("text", ""),
                })
            return results
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    def close(self) -> None:
        """Closes the Qdrant client connection releasing local file locks."""
        if hasattr(self, "qdrant_client") and self.qdrant_client is not None:
            try:
                self.qdrant_client.close()
            except Exception as e:
                logger.debug(f"Error during QdrantClient close: {e}")
            finally:
                self.qdrant_client = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


if __name__ == "__main__":
    store = ArchiveVectorStore()
    store.load_to_vector_db(limit=2)
    print("\nTest Search:")
    for match in store.search("microcontroller project", top_k=2):
        print(f"Score: {match['score']:.4f} | {match['title']} ({match['year']})")
        print(f"Snippet: {match['text'][:200]}...\n")
    store.close()
