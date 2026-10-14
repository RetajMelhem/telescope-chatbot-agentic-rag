"""Pinned, offline upstream Qwen counts. Hosted compatibility is a separate gate."""

import hashlib
from collections.abc import Mapping
from importlib.metadata import version
from pathlib import Path
from typing import Any

from tokenizers import Tokenizer

from telescope_rag.providers.contracts import EmbeddingFormat, OperationKind, TokenCount
from telescope_rag.providers.errors import ProviderError

QWEN_MODEL = "qwen/qwen3-embedding-8b"
TOKENIZER_REPOSITORY = "Qwen/Qwen3-Embedding-8B"
TOKENIZER_REVISION = "1d8ad4ca9b3dd8059ad90a75d4983776a23d44af"
TOKENIZER_SHA256 = "83cdf8c3a34f68862319cb1810ee7b1e2c0a44e0864ae930194ddb76bb7feb8d"
TOKENIZERS_VERSION = "0.22.2"
COUNT_PROFILE = "qwen3-8b:1d8ad4c:83cdf8c3:tokenizers-0.22.2:special-v1"
QUERY_PREFIX = (
    "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:"
)


def candidate_qwen_format() -> EmbeddingFormat:
    """Upstream convention only; deliberately cannot dispatch hosted embeddings."""
    return EmbeddingFormat(
        version="qwen3-8b-upstream-manual-v1",
        verified=False,
        query_prefix=QUERY_PREFIX,
        document_prefix="",
    )


def hosted_qwen_format() -> EmbeddingFormat:
    """Explicit DeepInfra convention; verified by the dated compatibility screen.

    The backend's exact HF identifier is documented and preserved in receipts.
    No other identifier/provider is treated as equivalent. This verifies wire
    compatibility, not retrieval quality or an undisclosed server weight revision.
    """
    return EmbeddingFormat(
        version="qwen3-8b-openrouter-deepinfra-v1",
        verified=True,
        query_prefix=QUERY_PREFIX,
        document_prefix="",
        provider_slug="deepinfra/us",
        reported_model="Qwen/Qwen3-Embedding-8B",
    )


class QwenPreparationCounter:
    """Count literal, fully formatted text including the tokenizer's post-processing.

    `verified` establishes compatibility with the pinned upstream tokenizer, not
    any hosted backend. No model weights, Hub lookup, padding or truncation occur.
    Hosted format verification and exact bundle approval remain separate gates.
    """

    model = QWEN_MODEL
    version = COUNT_PROFILE
    verified = True

    def __init__(self, tokenizer_path: Path) -> None:
        if version("tokenizers") != TOKENIZERS_VERSION:
            raise ValueError("qwen_tokenizer_library_mismatch")
        if not tokenizer_path.is_file() or tokenizer_path.stat().st_size > 16_000_000:
            raise ValueError("qwen_tokenizer_missing_or_oversized")
        raw = tokenizer_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != TOKENIZER_SHA256:
            raise ValueError("qwen_tokenizer_hash_mismatch")
        try:
            tokenizer = Tokenizer.from_str(raw.decode("utf-8"))
        except Exception:
            raise ValueError("qwen_tokenizer_invalid") from None
        if tokenizer.padding is not None or tokenizer.truncation is not None:
            raise ValueError("qwen_tokenizer_padding_or_truncation")
        self._tokenizer = tokenizer

    def count(self, text: str) -> int:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("qwen_count_input_invalid")
        try:
            if len(text.encode("utf-8")) > 1_000_000:
                raise ValueError
            # No prefix is injected here: preparation counts document_prefix +
            # retrieval_text. Future query dispatch must count its formatted input.
            count = len(self._tokenizer.encode(text, add_special_tokens=True).ids)
        except Exception:
            raise ValueError("qwen_count_failed") from None
        if count < 1:
            raise ValueError("qwen_count_failed")
        return count

    def receipt(self) -> dict:
        return {
            "model": self.model,
            "repository": TOKENIZER_REPOSITORY,
            "revision": TOKENIZER_REVISION,
            "tokenizer_sha256": TOKENIZER_SHA256,
            "library": "tokenizers",
            "library_version": TOKENIZERS_VERSION,
            "count_profile": self.version,
            "basis": "exact_upstream_tokenizer",
            "add_special_tokens": True,
            "padding": False,
            "truncation": False,
            "hosted_compatibility_verified": False,
            "weights_required": False,
        }


class QwenEmbeddingCounter:
    """Complete-input counts for this exact hosted profile; chat remains unavailable."""

    def __init__(self, tokenizer_path: Path):
        self._counter = QwenPreparationCounter(tokenizer_path)

    def count(self, kind: OperationKind, payload: Mapping[str, Any]) -> TokenCount:
        if kind != "embedding":
            raise ProviderError("token_count_unavailable")
        if (
            payload.get("model") != QWEN_MODEL
            or payload.get("dimensions") != 4096
            or type(payload.get("dimensions")) is not int
            or payload.get("encoding_format") != "float"
            or payload.get("provider")
            != {"only": ["deepinfra/us"], "require_parameters": True, "allow_fallbacks": False}
            or any(
                type(payload["provider"].get(flag)) is not bool
                for flag in ("require_parameters", "allow_fallbacks")
            )
            or set(payload) != {"model", "input", "dimensions", "encoding_format", "provider"}
        ):
            raise ProviderError("incompatible_token_count")
        texts = payload.get("input")
        if not isinstance(texts, list) or not 0 < len(texts) <= 32:
            raise ProviderError("invalid_embedding_input")
        try:
            count = sum(self._counter.count(text) for text in texts)
        except ValueError:
            raise ProviderError("invalid_embedding_input") from None
        return TokenCount(
            units=count,
            model=QWEN_MODEL,
            profile=COUNT_PROFILE + ":deepinfra-us-v1",
            basis="exact",
        )
