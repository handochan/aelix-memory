"""An optional offline provider. No model downloads, provider calls, or host imports."""

from __future__ import annotations

import hashlib
import math
import threading
from collections.abc import Sequence
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from typing import Protocol

from .models import MemoryError


class Embedder(Protocol):
    @property
    def fingerprint(self) -> str: ...

    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


def normalized(vector: Sequence[float]) -> list[float]:
    if not 1 <= len(vector) <= 4096:
        raise MemoryError("Embedding dimension must be between 1 and 4096.")
    try:
        numbers = [float(v) for v in vector]
    except (ValueError, TypeError, OverflowError) as exc:
        raise MemoryError("Invalid embedding vector.") from exc
    if not all(math.isfinite(v) for v in numbers):
        raise MemoryError("Embedding must contain finite numbers.")
    scale = max(abs(v) for v in numbers)
    if scale == 0:
        raise MemoryError("Embedding must have a non-zero norm.")
    scaled = [v / scale for v in numbers]
    norm = math.sqrt(math.fsum(v * v for v in scaled))
    return [v / norm for v in scaled]


class LocalSentenceEmbedder:
    """Load only already-provisioned model files; identity includes their content."""

    def __init__(self, model_dir: str | Path) -> None:
        # Configuration alone (especially while OFF) must not touch model files.
        self.path = Path(model_dir).expanduser().absolute()
        self._fingerprint: str | None = None
        self._model = None
        self._lock = threading.RLock()

    @property
    def fingerprint(self) -> str:
        with self._lock:
            return self._identity()

    def _identity(self) -> str:
        if self._fingerprint is None:
            if not self.path.is_dir():
                raise MemoryError("Embedding model must be a provisioned local directory.")
            digest = hashlib.sha256()
            for package in ("sentence-transformers", "transformers", "torch"):
                digest.update(f"{package}@{version(package)}\0".encode())
            files = sorted(p for p in self.path.rglob("*") if p.is_file())
            if not files:
                raise MemoryError("Embedding model directory is empty.")
            for path in files:
                digest.update(path.relative_to(self.path).as_posix().encode())
                digest.update(b"\0")
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
            self._fingerprint = "sentence-transformers:" + digest.hexdigest()
        return self._fingerprint

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        with self._lock:
            return self._encode(texts)

    def _encode(self, texts: Sequence[str]) -> list[list[float]]:
        if self._model is None:
            try:
                SentenceTransformer = import_module("sentence_transformers").SentenceTransformer
            except ImportError as exc:
                raise MemoryError(
                    "Install aelix-memory[semantic] to use local embeddings."
                ) from exc
            self._model = SentenceTransformer(
                str(self.path), local_files_only=True, trust_remote_code=False, device="cpu"
            )
        vectors = self._model.encode(
            list(texts), normalize_embeddings=True, show_progress_bar=False
        )
        return [normalized(vector) for vector in vectors]
