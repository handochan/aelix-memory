from pathlib import Path

import pytest

from aelix_memory.scope import Scope
from aelix_memory.store import Store


@pytest.fixture
def scope(tmp_path: Path) -> Scope:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return Scope.for_project(project)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "private-memory")


@pytest.fixture
def enabled(store: Store, scope: Scope) -> Store:
    store.set_mode(scope, "on")
    return store
