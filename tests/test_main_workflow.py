"""Exercise job routing and SQLite failure fallbacks used by run.yml."""

import os
from pathlib import Path
import re
import subprocess
import textwrap
from types import SimpleNamespace

import pytest

from core.database import Database


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/run.yml"


def job(name):
    source = WORKFLOW.read_text(encoding="utf-8")
    return re.search(
        rf"^  {name}:\n(.*?)(?=^  \w+:\n|\Z)", source, re.M | re.S
    ).group(1)


@pytest.mark.parametrize("event", ["workflow_dispatch", "schedule", "push", "pull_request"])
@pytest.mark.parametrize("mode", ["tests", "public-probe", "all"])
def test_manual_tests_and_scheduled_probe_route_to_separate_jobs(event, mode):
    active = []
    for name in ("test", "public_probe"):
        expression = job(name).split("if: >-\n", 1)[1].split("runs-on:", 1)[0]
        expression = " ".join(expression.split()).replace("||", "or").replace("&&", "and")
        context = {
            "github": SimpleNamespace(event_name=event),
            "inputs": SimpleNamespace(mode=mode),
        }
        if eval(expression, {"__builtins__": {}}, context):
            active.append(name)
    if event == "schedule":
        assert active == ["public_probe"]
    elif event in {"push", "pull_request"}:
        assert active == ["test"]
    else:
        assert active == {
            "tests": ["test"],
            "public-probe": ["public_probe"],
            "all": ["test", "public_probe"],
        }[mode]


@pytest.mark.parametrize(
    ("name", "step", "expected_category"),
    [
        ("test", "Record failed test job", "test_job_failed"),
        ("public_probe", "Record failed public probe job", "public_probe_job_failed"),
    ],
)
def test_failure_fallback_writes_database_and_preserves_existing_details(
    name, step, expected_category, tmp_path
):
    block = job(name).split(f"- name: {step}\n", 1)[1].split("\n      - ", 1)[0]
    assert "if: failure()" in block
    command = textwrap.dedent(block.split("run: |\n", 1)[1])
    database_path = tmp_path / "workflow-errors.db"
    environment = dict(os.environ, DB_PATH=str(database_path), PYTHONPATH=str(ROOT))
    for _ in range(2):
        result = subprocess.run(
            ["bash", "-e", "-c", command],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
    rows = Database(str(database_path)).get_recent_logs()
    assert len(rows) == 2
    assert all(row.error_message == expected_category for row in rows)

    # Previous rows must never suppress the current job failure.
    detailed_path = tmp_path / "detailed.db"
    Database(str(detailed_path)).log_error("aldi_talk", "public_probe", "public_probe_failed")
    environment["DB_PATH"] = str(detailed_path)
    result = subprocess.run(
        ["bash", "-e", "-c", command], cwd=tmp_path, env=environment, capture_output=True
    )
    assert result.returncode == 0
    assert {row.error_message for row in Database(str(detailed_path)).get_recent_logs()} == {
        "public_probe_failed", expected_category
    }
