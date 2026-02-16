"""
L3: event Semantics Layer

Store and retrieve event semantics using vector embeddings
Supports semantic similarity search

Backend support:
- Local: sentence-transformers
- Remote: OpenAI/Anthropic Embedding API
"""
import logging
import time
import hashlib
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger(__name__)


class eventEmbedding:
    """event vector embedding"""

    def __init__(
        self,
        event_id: str,
        embedding: List[float],
        text: str = "",
        metadata: Dict[str, Any] = None,
    ):
        self.event_id = event_id
        self.embedding = embedding
        self.text = text
        self.metadata = metadata or {}
        self.created_at = time.time()


class EmbeddingBackend:
    """Embedding backend base class"""

    async def initialize(self):
        """initialize backend"""
        pass

    async def generate(self, text: str) -> List[float]:
        """Generate vector"""
        raise NotImplementederror

    @property
    def dimension(self) -> int:
        """Vector dimension"""
        raise NotImplementederror


class LocalEmbeddingBackend(EmbeddingBackend):
    """Local sentence-transformers backend"""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", dimension: int = 384):
        self.model_name = model_name
        self._dimension = dimension
        self._model = None
        self._model_loaded = False

    def _load_model(self):
        """Load embedding model"""
        if self._model_loaded:
            return

        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading local embedding model: {self.model_name}")
            self._model = SentenceTransformer(self.model_name)
            self._dimension = self._model.get_sentence_embedding_dimension()
            self._model_loaded = True
            logger.info(f"Local embedding model loaded, dimension: {self._dimension}")
        except ImportError:
            logger.warning("sentence-transformers not installed, using dummy embeddings")
            self._model = None
            self._model_loaded = True
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            self._model = None
            self._model_loaded = True

    async def generate(self, text: str) -> List[float]:
        """Generate vector"""
        if not self._model_loaded:
            self._load_model()

        if self._model:
            embedding = self._model.encode(text, convert_to_numpy=True).tolist()
            return embedding
        else:
            # Generate simple hash vector as fallback
            text_hash = hashlib.md5(text.encode()).digest()
            # Extend to target dimension
            while len(text_hash) < self._dimension // 8:
                text_hash += hashlib.sha1(text.encode()).digest()
            return [float(b) / 255.0 for b in text_hash[:self._dimension]]

    @property
    def dimension(self) -> int:
        return self._dimension


class RemoteEmbeddingBackend(EmbeddingBackend):
    """Remote LLM API backend"""

    def __init__(
        self,
        llm_adapter,
        model: str = "text-embedding-3-small",
        dimension: int = 1536,
    ):
        """
        initialize remote embedding backend

        Args:
            llm_adapter: LLM adapter instance
            model: Model name
            dimension: Vector dimension
        """
        self.llm_adapter = llm_adapter
        self.model = model
        self._dimension = dimension

    async def initialize(self):
        """initialize backend"""
        # Set model if llm_adapter has embedding-related settings
        if hasattr(self.llm_adapter, 'set_embedding_model'):
            self.llm_adapter.set_embedding_model(self.model)
        # Update actual dimension
        if hasattr(self.llm_adapter, 'embedding_dimension'):
            self._dimension = self.llm_adapter.embedding_dimension

    async def generate(self, text: str) -> List[float]:
        """Generate vector"""
        if not text or not text.strip():
            return [0.0] * self._dimension

        if not self.llm_adapter.supports_embeddings:
            logger.warning("LLM adapter does not support embeddings, using dummy")
            return self._dummy_embedding(text)

        embedding = await self.llm_adapter.get_embedding(text, self.model)
        if embedding is None:
            return self._dummy_embedding(text)
        return embedding

    def _dummy_embedding(self, text: str) -> List[float]:
        """Generate simple hash vector as fallback"""
        text_hash = hashlib.md5(text.encode()).digest()
        while len(text_hash) < self._dimension // 8:
            text_hash += hashlib.sha1(text.encode()).digest()
        return [float(b) / 255.0 for b in text_hash[:self._dimension]]

    @property
    def dimension(self) -> int:
        return self._dimension


class eventEmbeddingStore:
    """
    event vector embedding store

    Supports vector generation, storage and similarity search
    """

    def __init__(
        self,
        backend: EmbeddingBackend = None,
        persist_path: str = None,
    ):
        """
        initialize vector store

        Args:
            backend: Embedding backend (uses default local backend if not specified)
            persist_path: persistence file path
        """
        self.backend = backend or LocalEmbeddingBackend()
        self.persist_path = persist_path

        # Vector store: {event_id: eventEmbedding}
        self._embeddings: Dict[str, eventEmbedding] = {}

        # Text index (for regenerating embeddings)
        self._text_index: Dict[str, str] = {}  # {event_id: text}

        # Load persisted data
        if persist_path:
            self._load_from_disk()

    async def initialize(self):
        """initialize store"""
        await self.backend.initialize()
        logger.info(f"Embedding store initialized, dimension: {self.backend.dimension}")

    async def _generate_embedding(self, text: str) -> List[float]:
        """
        Generate vector embedding for text

        Args:
            text: Input text

        Returns:
            Vector embedding
        """
        return await self.backend.generate(text)

    async def add_event(
        self,
        event_id: str,
        text: str,
        metadata: Dict[str, Any] = None,
    ) -> List[float]:
        """
        Add event and generate embedding

        Args:
            event_id: event id
            text: event text content
            metadata: metadata

        Returns:
            Generated vector embedding
        """
        embedding = await self._generate_embedding(text)

        self._embeddings[event_id] = eventEmbedding(
            event_id=event_id,
            embedding=embedding,
            text=text[:500],  # Save first 500 characters for regeneration
            metadata=metadata or {},
        )
        self._text_index[event_id] = text

        logger.debug(f"Embedding generated for event {event_id}")

        return embedding

    async def similarity_search(
        self,
        query_text: str,
        top_k: int = 10,
        threshold: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """
        Semantic similarity search

        Args:
            query_text: query text
            top_k: Return top K results
            threshold: Similarity threshold

        Returns:
            List of similar events
        """
        if not self._embeddings:
            return []

        # Generate query vector
        query_embedding = await self._generate_embedding(query_text)

        # Calculate cosine similarity
        results = []
        for event_id, emb in self._embeddings.items():
            similarity = self._cosine_similarity(query_embedding, emb.embedding)

            if similarity >= threshold:
                results.append({
                    "event_id": event_id,
                    "similarity": similarity,
                    "text": emb.text,
                    "metadata": emb.metadata,
                })

        # Sort by similarity
        results.sort(key=lambda x: x["similarity"], reverse=True)

        return results[:top_k]

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """
        Calculate cosine similarity

        Args:
            vec1: Vector 1
            vec2: Vector 2

        Returns:
            Similarity (0-1)
        """
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = sum(a * a for a in vec1) ** 0.5
        magnitude2 = sum(b * b for b in vec2) ** 0.5

        if magnitude1 * magnitude2 == 0:
            return 0.0

        return dot_product / (magnitude1 * magnitude2)

    def get_embedding(self, event_id: str) -> Optional[List[float]]:
        """
        Get event embedding

        Args:
            event_id: event id

        Returns:
            Vector embedding
        """
        emb = self._embeddings.get(event_id)
        return emb.embedding if emb else None

    async def batch_add_events(
        self,
        events: List[Dict[str, Any]],
        text_field: str = "content",
    ):
        """
        Batch add events

        Args:
            events: List of events
            text_field: Text field name
        """
        for event in events:
            event_id = event.get("id", event.get("event_id", ""))
            text = event.get(text_field, "") or str(event.get("data", {}))

            if event_id and text:
                await self.add_event(
                    event_id=event_id,
                    text=text,
                    metadata={"event_type": event.get("type", "unknotttwn")},
                )

        logger.info(f"Added {len(events)} events to embedding store")

    def clear_old_embeddings(self, older_than_days: int = 30):
        """
        Clear old embedding data

        Args:
            older_than_days: Number of days ago to clear data
        """
        cutoff_time = time.time() - (older_than_days * 86400)
        ids_to_remove = []

        for event_id, emb in self._embeddings.items():
            if emb.created_at < cutoff_time:
                ids_to_remove.append(event_id)

        for event_id in ids_to_remove:
            del self._embeddings[event_id]
            if event_id in self._text_index:
                del self._text_index[event_id]

        logger.info(f"Cleared {len(ids_to_remove)} old embeddings")

    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics"""
        return {
            "total_embeddings": len(self._embeddings),
            "dimension": self.backend.dimension,
            "backend": self.backend.__class__.__name__,
        }

    def _save_to_disk(self):
        """persist to disk"""
        if not self.persist_path:
            return

        try:
            import json
            data = {
                "embeddings": {
                    event_id: {
                        "embedding": emb.embedding,
                        "text": emb.text,
                        "metadata": emb.metadata,
                        "created_at": emb.created_at,
                    }
                    for event_id, emb in self._embeddings.items()
                },
                "dimension": self.backend.dimension,
            }

            with open(self.persist_path, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.debug(f"Embeddings saved to {self.persist_path}")
        except Exception as e:
            logger.error(f"Failed to save embeddings: {e}")

    def _load_from_disk(self):
        """Load from disk"""
        if not self.persist_path:
            return

        try:
            import json
            from pathlib import Path

            path = path(self.persist_path)
            if not path.exists():
                return

            with open(self.persist_path, "r") as f:
                data = json.load(f)

            for event_id, emb_data in data.get("embeddings", {}).items():
                self._embeddings[event_id] = eventEmbedding(
                    event_id=event_id,
                    embedding=emb_data["embedding"],
                    text=emb_data.get("text", ""),
                    metadata=emb_data.get("metadata", {}),
                )
                self._embeddings[event_id].created_at = emb_data.get("created_at", time.time())
                self._text_index[event_id] = emb_data.get("text", "")

            logger.info(f"Embeddings loaded from {self.persist_path}")
        except Exception as e:
            logger.warning(f"Failed to load embeddings: {e}")


class HybrideventSearch:
    """
    Hybrid event search

    Combines keyword search and semantic search
    """

    def __init__(self, embedding_store: eventEmbeddingStore):
        self.embedding_store = embedding_store

    async def search(
        self,
        query: str,
        top_k: int = 10,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search

        Args:
            query: query text
            top_k: Return top K results
            semantic_weight: Semantic search weight
            keyword_weight: Keyword search weight

        Returns:
            Search results
        """
        # Semantic search
        semantic_results = await self.embedding_store.similarity_search(
            query_text=query,
            top_k=top_k * 2,
            threshold=0.3,
        )

        # Keyword search
        keyword_results = self._keyword_search(query, top_k=top_k * 2)

        # Merge results
        combined = self._combine_results(
            semantic_results,
            keyword_results,
            semantic_weight,
            keyword_weight,
        )

        return combined[:top_k]

    def _keyword_search(
        self,
        query: str,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """Keyword search"""
        query_lower = query.lower()
        results = []

        for event_id, emb in self.embedding_store._embeddings.items():
            text_lower = emb.text.lower()

            # Simple keyword matching
            if query_lower in text_lower:
                # Calculate match score
                score = len(query_lower) / len(text_lower)
                results.append({
                    "event_id": event_id,
                    "similarity": score,
                    "text": emb.text,
                    "metadata": emb.metadata,
                })

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:top_k]

    def _combine_results(
        self,
        semantic_results: List[Dict],
        keyword_results: List[Dict],
        semantic_weight: float,
        keyword_weight: float,
    ) -> List[Dict]:
        """Combine search results"""
        combined = {}

        # Add semantic search results
        for result in semantic_results:
            event_id = result["event_id"]
            combined[event_id] = {
                "event_id": event_id,
                "semantic_score": result["similarity"],
                "keyword_score": 0.0,
                "text": result["text"],
                "metadata": result["metadata"],
            }

        # Add keyword search results
        for result in keyword_results:
            event_id = result["event_id"]
            if event_id in combined:
                combined[event_id]["keyword_score"] = result["similarity"]
            else:
                combined[event_id] = {
                    "event_id": event_id,
                    "semantic_score": 0.0,
                    "keyword_score": result["similarity"],
                    "text": result["text"],
                    "metadata": result["metadata"],
                }

        # Calculate combined score
        for result in combined.values():
            result["combined_score"] = (
                result["semantic_score"] * semantic_weight +
                result["keyword_score"] * keyword_weight
            )

        # Sort
        results = list(combined.values())
        results.sort(key=lambda x: x["combined_score"], reverse=True)

        return results


def create_embedding_store(
    backend: str = "local",
    llm_adapter=None,
    local_model: str = "all-MiniLM-L6-v2",
    local_dimension: int = 384,
    remote_model: str = "text-embedding-3-small",
    remote_dimension: int = 1536,
    persist_path: str = None,
) -> eventEmbeddingStore:
    """
    Factory function to create embedding store

    Args:
        backend: Backend type (local, openai, anthropic)
        llm_adapter: LLM adapter (required for remote backend)
        local_model: Local model name
        local_dimension: Local vector dimension
        remote_model: Remote model name
        remote_dimension: Remote vector dimension
        persist_path: persistence path

    Returns:
        eventEmbeddingStore instance
    """
    if backend == "local":
        embedding_backend = LocalEmbeddingBackend(local_model, local_dimension)
    elif backend in ("openai", "anthropic"):
        if not llm_adapter:
            logger.warning(f"LLM adapter not provided for {backend}, falling back to local")
            embedding_backend = LocalEmbeddingBackend(local_model, local_dimension)
        else:
            embedding_backend = RemoteEmbeddingBackend(
                llm_adapter=llm_adapter,
                model=remote_model,
                dimension=remote_dimension,
            )
    else:
        logger.warning(f"Unknotttwn backend {backend}, using local")
        embedding_backend = LocalEmbeddingBackend(local_model, local_dimension)

    return eventEmbeddingStore(
        backend=embedding_backend,
        persist_path=persist_path,
    )
