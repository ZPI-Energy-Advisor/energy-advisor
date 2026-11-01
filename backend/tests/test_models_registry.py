import subprocess
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]

CHECK_FOREIGN_KEYS = """
import main
from app.database import Base

for table in Base.metadata.tables.values():
    for foreign_key in table.foreign_keys:
        foreign_key.column
"""


def test_every_foreign_key_target_is_registered_by_the_app():
    result = subprocess.run(
        [sys.executable, "-c", CHECK_FOREIGN_KEYS], cwd=BACKEND_DIR, capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr
