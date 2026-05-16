"""Remove build artifacts, caches, and generated files."""

import shutil
from pathlib import Path

ROOT = Path(".")

for name in ("dist", "build"):
    p = ROOT / name
    if p.exists():
        shutil.rmtree(p)
        print(f"removed {p}")

for egg in ROOT.glob("*.egg-info"):
    shutil.rmtree(egg)
    print(f"removed {egg}")

for egg in (ROOT / "src").glob("*.egg-info"):
    shutil.rmtree(egg)
    print(f"removed {egg}")

for pattern in ("__pycache__", ".pytest_cache", ".ruff_cache"):
    for p in ROOT.rglob(pattern):
        if p.is_dir():
            shutil.rmtree(p)
            print(f"removed {p}")
