"""Synchronous ONNX encoding helpers for local embeddings."""

from __future__ import annotations

from typing import Any


class LocalEmbeddingEncodingMixin:
    """Encode texts using the loaded tokenizer and ONNX session."""

    _MAX_ENCODE_BATCH = 64

    def _encode_sync(self, texts: list[str]) -> list[list[float]]:
        """Synchronous batch encode, expected to run in a thread pool."""
        if not texts:
            return []
        if len(texts) <= self._MAX_ENCODE_BATCH:
            return self._encode_sub_batch(texts)

        all_vectors: list[list[float]] = []
        for start in range(0, len(texts), self._MAX_ENCODE_BATCH):
            sub = texts[start : start + self._MAX_ENCODE_BATCH]
            all_vectors.extend(self._encode_sub_batch(sub))
        return all_vectors

    def _encode_sub_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode a single sub-batch of texts through ONNX."""
        import numpy as np

        session = self._session
        tokenizer = self._tokenizer
        if session is None or tokenizer is None:
            return []

        if self._pooling == "last_token":
            tokenizer.enable_padding(direction="left")
        else:
            tokenizer.enable_padding(direction="right")
        tokenizer.enable_truncation(
            max_length=self._model_config.get("max_position_embeddings", 512)
        )
        encodings = tokenizer.encode_batch(texts)

        input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
        attention_mask = np.array(
            [e.attention_mask for e in encodings], dtype=np.int64
        )

        input_names = {inp.name for inp in session.get_inputs()}
        feeds: dict[str, Any] = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
        }
        if "token_type_ids" in input_names:
            feeds["token_type_ids"] = np.zeros_like(input_ids)
        if "position_ids" in input_names:
            batch_size, seq_len = input_ids.shape
            feeds["position_ids"] = np.broadcast_to(
                np.arange(seq_len, dtype=np.int64)[np.newaxis, :],
                (batch_size, seq_len),
            ).copy()

        kv_inputs = sorted(n for n in input_names if n.startswith("past_key_values."))
        if kv_inputs:
            batch_size = input_ids.shape[0]
            num_kv_heads = int(self._model_config.get("num_key_value_heads", 8))
            head_dim = int(self._model_config.get("head_dim", 128))
            empty_kv = np.zeros(
                (batch_size, num_kv_heads, 0, head_dim), dtype=np.float32
            )
            for kv_name in kv_inputs:
                feeds[kv_name] = empty_kv

        output_names = [session.get_outputs()[0].name]
        outputs = session.run(output_names, feeds)
        hidden_states = outputs[0]

        if self._pooling == "cls":
            embeddings = hidden_states[:, 0, :]
        elif self._pooling == "last_token":
            seq_lengths = attention_mask.sum(axis=1).astype(int) - 1
            embeddings = hidden_states[
                np.arange(hidden_states.shape[0]), seq_lengths, :
            ]
        else:
            mask = attention_mask[:, :, np.newaxis].astype(np.float32)
            sum_hidden = (hidden_states * mask).sum(axis=1)
            sum_mask = mask.sum(axis=1)
            sum_mask = np.maximum(sum_mask, 1e-9)
            embeddings = sum_hidden / sum_mask

        if self._normalize:
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            norms = np.maximum(norms, 1e-12)
            embeddings = embeddings / norms

        return embeddings.tolist()


__all__ = ["LocalEmbeddingEncodingMixin"]
