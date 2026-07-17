import sqlite3
import json
import uuid
import ollama
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

class ArchiveVectorStore:
    def __init__(self, config_path="config.json"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)
            
        self.db_path = self.config["db_path"]
        self.qdrant_db_path = self.config["qdrant_db_path"]
        self.ollama_url = self.config["ollama_url"]
        self.model_embedding = self.config["model_embedding"]
        self.chunk_size = self.config.get("chunk_size", 800)
        self.chunk_overlap = self.config.get("chunk_overlap", 150)
        self.collection_name = "elektor_articles"
        
        # Connect to Ollama
        self.ollama_client = ollama.Client(host=self.ollama_url)
        
        # Connect to local Qdrant Vector DB on disk
        self.qdrant_client = QdrantClient(path=self.qdrant_db_path)
        
        # Determine embedding dimension
        self.embedding_dim = self.get_embedding_dimension()
        
        # Ensure collection exists
        self.ensure_collection()

    def get_embedding_dimension(self):
        """Get embedding dimension by running a test vector"""
        try:
            res = self.ollama_client.embeddings(model=self.model_embedding, prompt="test")
            return len(res["embedding"])
        except Exception as e:
            print(f"Error testing embedding model dimension: {e}. Defaulting to 768.")
            return 768 # nomic-embed-text standard dimension

    def ensure_collection(self):
        """Creates the Qdrant collection if it does not already exist"""
        collections = [col.name for col in self.qdrant_client.get_collections().collections]
        if self.collection_name not in collections:
            print(f"Creating Qdrant collection: {self.collection_name} (dim={self.embedding_dim})")
            self.qdrant_client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=self.embedding_dim, distance=Distance.COSINE),
            )

    def chunk_text(self, text):
        """Splits text into chunks respecting word boundaries"""
        words = text.split()
        chunks = []
        if not words:
            return chunks
            
        current_chunk = []
        current_len = 0
        
        for word in words:
            word_len = len(word) + 1
            if current_len + word_len > self.chunk_size and current_chunk:
                chunks.append(" ".join(current_chunk))
                # Retain some words for overlap
                overlap_words = []
                overlap_len = 0
                for w in reversed(current_chunk):
                    if overlap_len + len(w) + 1 > self.chunk_overlap:
                        break
                    overlap_words.insert(0, w)
                    overlap_len += len(w) + 1
                current_chunk = overlap_words
                current_len = overlap_len
                
            current_chunk.append(word)
            current_len += word_len
            
        if current_chunk:
            chunks.append(" ".join(current_chunk))
            
        return chunks

    def load_to_vector_db(self, limit=None):
        """Reads articles from SQLite, chunks them, gets embeddings, and saves to Qdrant"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Parse range limit if range format
        start, end = 0, None
        if isinstance(limit, tuple):
            start, end = limit
        elif isinstance(limit, int):
            start, end = 0, limit
            
        # Get articles that have text and are not yet embedded
        cursor.execute("SELECT id, title, year, filename, extracted_text FROM articles WHERE extracted_text IS NOT NULL AND extracted_text != '' AND is_embedded = 0")
        rows = cursor.fetchall()
        
        if not rows:
            print("No new articles to embed.")
            conn.close()
            return
            
        sliced_rows = rows[start:end] if end is not None else rows[start:]
        print(f"Loading {len(rows)} non-embedded articles. Processing range [{start}:{end if end is not None else len(rows)}] ({len(sliced_rows)} articles) into Vector DB...")
        
        count = 0
        points_to_upload = []
        embedded_article_ids = []
        
        for row in sliced_rows:
            article_id, title, year, filename, text = row
            print(f"Embedding article [{article_id}]: {title}...")
            
            chunks = self.chunk_text(text)
            article_success = True
            for chunk_idx, chunk in enumerate(chunks):
                try:
                    # Get embedding vector
                    res = self.ollama_client.embeddings(model=self.model_embedding, prompt=chunk)
                    vector = res["embedding"]
                    
                    point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{filename}_chunk_{chunk_idx}"))
                    
                    payload = {
                        "article_id": article_id,
                        "title": title,
                        "year": year,
                        "filename": filename,
                        "chunk_index": chunk_idx,
                        "text": chunk
                    }
                    
                    points_to_upload.append(PointStruct(
                        id=point_id,
                        vector=vector,
                        payload=payload
                    ))
                except Exception as e:
                    print(f"  Failed to embed chunk {chunk_idx} of article {article_id}: {e}")
                    article_success = False
            
            if article_success:
                embedded_article_ids.append(article_id)
            count += 1
            
        # Upload all points to Qdrant
        if points_to_upload:
            print(f"Uploading {len(points_to_upload)} vectors to Qdrant...")
            self.qdrant_client.upsert(
                collection_name=self.collection_name,
                points=points_to_upload
            )
            print("Upload completed.")
            
            # Mark successfully uploaded articles as embedded in SQLite
            for art_id in embedded_article_ids:
                cursor.execute("UPDATE articles SET is_embedded = 1 WHERE id = ?", (art_id,))
            conn.commit()
            
        conn.close()

    def search(self, query, top_k=5):
        """Performs semantic search over the vectorized articles"""
        try:
            res = self.ollama_client.embeddings(model=self.model_embedding, prompt=query)
            query_vector = res["embedding"]
            
            search_results = self.qdrant_client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=top_k
            )
            
            results = []
            for hit in search_results:
                results.append({
                    "score": hit.score,
                    "title": hit.payload["title"],
                    "year": hit.payload["year"],
                    "filename": hit.payload["filename"],
                    "text": hit.payload["text"]
                })
            return results
        except Exception as e:
            print(f"Search failed: {e}")
            return []

if __name__ == "__main__":
    store = ArchiveVectorStore()
    store.load_to_vector_db(limit=2)
    print("\nTest Search:")
    for match in store.search("microcontroller project", top_k=2):
        print(f"Score: {match['score']:.4f} | {match['title']} ({match['year']})")
        print(f"Snippet: {match['text'][:200]}...\n")
