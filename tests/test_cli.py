import json
import os
import subprocess
import sys

from aelix_memory.cli import main


def test_cli_model_free_choice_save_restart_update_export_forget(tmp_path, monkeypatch, capsys):
    project = tmp_path / "프로젝트"
    project.mkdir()
    home = tmp_path / "memory"
    monkeypatch.setenv("AELIX_MEMORY_HOME", str(home))
    prefix = ["--project", str(project)]
    assert main(prefix + ["status"]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "off"
    assert not home.exists()
    assert main(prefix + ["on"]) == 0
    capsys.readouterr()
    assert main(prefix + ["remember", "--key", "runner", "--title", "Runner", "Use pytest."]) == 0
    memory = json.loads(capsys.readouterr().out)
    assert main(prefix + ["update", memory["id"], "Use uv run pytest."]) == 0
    capsys.readouterr()
    output = tmp_path / "export.json"
    assert main(prefix + ["export", "--output", str(output)]) == 0
    capsys.readouterr()
    assert len(json.loads(output.read_text())["memories"]) == 2
    if os.name == "posix":
        assert os.stat(output).st_mode & 0o077 == 0
    original = output.read_bytes()
    assert main(prefix + ["export", "--output", str(output)]) == 2
    capsys.readouterr()
    assert output.read_bytes() == original
    assert main(prefix + ["forget", memory["id"]]) == 0
    capsys.readouterr()
    assert main(prefix + ["list"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_package_import_is_side_effect_free_without_host(tmp_path):
    home = tmp_path / "never-created"
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, aelix_memory; assert not any(n.startswith('aelix_coding_agent') for n in sys.modules)",
        ],
        env={**os.environ, "AELIX_MEMORY_HOME": str(home)},
        check=True,
    )
    assert not home.exists()
