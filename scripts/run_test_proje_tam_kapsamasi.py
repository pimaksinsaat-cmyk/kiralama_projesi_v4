"""`tests/test_proje_tam_kapsamasi.py` dosyasini tek komutla calistirir."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_FILE = ROOT / "tests" / "test_proje_tam_kapsamasi.py"


def main() -> int:
    if not TEST_FILE.exists():
        print(f"[HATA] Test dosyasi bulunamadi: {TEST_FILE}")
        return 1

    cmd = [sys.executable, "-m", "pytest", str(TEST_FILE), "-q"]
    print(f"[INFO] Calistiriliyor: {' '.join(cmd)}")
    completed = subprocess.run(cmd, cwd=ROOT)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
