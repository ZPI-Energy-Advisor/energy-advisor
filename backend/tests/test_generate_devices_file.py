import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
GENERATOR = SCRIPTS / "generate_devices_file.py"
VALIDATOR = SCRIPTS / "validate_devices_file.py"
DEMO_FILE = Path(__file__).parent / "fixtures" / "devices_demo_30d.json"
SAMPLE_FILE = Path(__file__).resolve().parents[2] / "frontend" / "public" / "samples" / "devices-example.json"
DEMO_ARGS = ["--start", "2026-10-01", "--days", "30", "--seed", "42", "--devices", "full", "--with-pv"]


def run_script(script: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *map(str, args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def generate(path: Path, *args) -> bytes:
    result = run_script(GENERATOR, *args, "--out", path)
    assert result.returncode == 0, result.stderr
    return path.read_bytes()


@pytest.mark.parametrize("seed", [1, 7, 42])
@pytest.mark.parametrize("options", [["--devices", "standard"], ["--devices", "full", "--with-pv"]])
def test_generated_file_passes_validation(tmp_path, seed, options):
    path = tmp_path / "devices.json"
    generate(path, "--seed", seed, "--days", 14, *options)

    result = run_script(VALIDATOR, path)

    assert result.returncode == 0, result.stdout


def test_generator_respects_grid_limit(tmp_path):
    path = tmp_path / "devices.json"
    generate(path, "--devices", "full", "--with-pv", "--max-grid-kw", 6)

    result = run_script(VALIDATOR, path, "--max-grid-kw", 6)

    assert result.returncode == 0, result.stdout


def test_same_seed_gives_identical_file(tmp_path):
    first = generate(tmp_path / "a.json", "--seed", 5, "--with-pv")
    second = generate(tmp_path / "b.json", "--seed", 5, "--with-pv")
    other_seed = generate(tmp_path / "c.json", "--seed", 6, "--with-pv")

    assert first == second
    assert first != other_seed


def test_demo_file_matches_generator(tmp_path):
    assert generate(tmp_path / "demo.json", *DEMO_ARGS) == DEMO_FILE.read_bytes()


def test_demo_file_covers_dst_change():
    document = json.loads(DEMO_FILE.read_text(encoding="utf-8"))
    fridge_on_dst_day = next(
        action for action in document["energy_usage"]
        if action["device_id"] == "dev_fr_01" and action["action_start"].startswith("2026-10-25")
    )

    start = datetime.fromisoformat(fridge_on_dst_day["action_start"])
    end = datetime.fromisoformat(fridge_on_dst_day["action_end"])

    assert document["period"]["start"].endswith("+02:00")
    assert document["period"]["end"].endswith("+01:00")
    assert (start.isoformat()[-6:], end.isoformat()[-6:]) == ("+02:00", "+01:00")
    assert end - start == timedelta(hours=25)


def test_generator_uses_sample_file_device_catalog():
    sample = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))
    demo = json.loads(DEMO_FILE.read_text(encoding="utf-8"))

    assert demo["devices"] == sample["devices"]
