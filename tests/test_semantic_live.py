"""Run only with an explicitly provisioned local model; never downloads one."""

import os
import socket

import pytest

from aelix_memory.embeddings import LocalSentenceEmbedder
from aelix_memory.models import Draft

pytestmark = pytest.mark.semantic
MODEL = os.environ.get("AELIX_MEMORY_TEST_MODEL_LOCAL")


@pytest.mark.skipif(
    not MODEL, reason="Provision a local model and set AELIX_MEMORY_TEST_MODEL_LOCAL"
)
def test_real_multilingual_semantic_recall_is_offline_and_erased(enabled, scope, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")

    def no_network(*args, **kwargs):
        raise AssertionError("Semantic memory must not open a network connection.")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    memory = enabled.add(
        scope,
        Draft(
            "Local database", "Use SQLite to store durable project facts.", "fixture:local-semantic"
        ),
    )
    query = "프로젝트의 지식을 로컬 데이터베이스에 보관합니다."
    assert not enabled.search(scope, query).hits
    enabled.embedder = LocalSentenceEmbedder(MODEL)
    assert enabled.reindex(scope) == 1
    enabled.set_mode(scope, "read")
    before = enabled.path.read_bytes()
    result = enabled.search(scope, query)
    assert not result.warnings
    assert result.hits[0].memory.id == memory.id
    assert result.hits[0].channels == ("semantic",)
    assert enabled.path.read_bytes() == before
    enabled.forget(scope, memory.id)
    assert not enabled.search(scope, query).hits
