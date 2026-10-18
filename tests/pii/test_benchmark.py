import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_benchmark_check_passes() -> None:
    r = subprocess.run([sys.executable, str(ROOT / "scripts/pii_benchmark.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
