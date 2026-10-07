import math
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from aelix_memory.embeddings import normalized
from aelix_memory.models import ConsentError, Draft, MemoryError


class FakeEmbedder:
    fingerprint = "test-model:version-1"

    def encode(self, texts):
        return [[1.0, 0.0] if "database" in t or "SQL" in t else [0.0, 1.0] for t in texts]


def test_optional_vector_recall_no_cross_scope_and_fingerprint_mismatch(enabled, scope, tmp_path):
    enabled.embedder = FakeEmbedder()
    memory = enabled.add(scope, Draft("SQL", "Prefer SQLite.", "user-command"))
    assert enabled.reindex(scope) == 1
    result = enabled.search(scope, "database")
    assert result.hits[0].memory.id == memory.id
    assert result.hits[0].channels == ("semantic",)
    enabled.embedder.fingerprint = "test-model:other"
    assert not enabled.search(scope, "database").hits
    assert enabled.search(scope, "SQLite").hits


def test_semantic_failure_falls_back_visibly_and_read_never_embeds_writes(enabled, scope):
    enabled.add(scope, Draft("SQL", "Use SQLite.", "user-command"))
    enabled.embedder = FakeEmbedder()
    enabled.reindex(scope)
    enabled.set_mode(scope, "read")

    class BrokenEmbedder(FakeEmbedder):
        def encode(self, texts):
            raise RuntimeError("private model error")

    enabled.embedder = BrokenEmbedder()
    before = enabled.path.read_bytes()
    result = enabled.search(scope, "SQLite")
    assert result.hits and result.warnings
    assert "private" not in result.warnings[0]
    with pytest.raises(ConsentError):
        enabled.reindex(scope)
    assert enabled.path.read_bytes() == before


@pytest.mark.parametrize("vector", [[], [0, 0], [math.nan, 1], [math.inf, 1], [1] * 4097])
def test_invalid_vectors_rejected(vector):
    with pytest.raises(MemoryError):
        normalized(vector)


def test_large_finite_vector_normalization():
    assert normalized([1e308, 1e308]) == pytest.approx([math.sqrt(0.5), math.sqrt(0.5)])


def test_slow_embedding_does_not_block_off_and_revocation_prevents_delivery(enabled, scope):
    started = threading.Event()
    release = threading.Event()

    class SlowEmbedder(FakeEmbedder):
        def encode(self, texts):
            if texts == ["database"]:
                started.set()
                release.wait(5)
            return super().encode(texts)

    enabled.embedder = SlowEmbedder()
    enabled.add(scope, Draft("SQL", "Use SQLite.", "user-command"))
    enabled.reindex(scope)
    with ThreadPoolExecutor(max_workers=2) as pool:
        query = pool.submit(enabled.search, scope, "database")
        assert started.wait(2)
        try:
            disable = pool.submit(enabled.set_mode, scope, "off")
            disable.result(timeout=1)
        finally:
            release.set()
        with pytest.raises(ConsentError):
            query.result(timeout=2)
