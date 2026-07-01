"""Launcher shim: allow running the web UI from simulator/ via `py -3 app.py`."""

from pathlib import Path
import runpy
import sys

ROOT_APP = Path(__file__).resolve().parent.parent / "app.py"

if not ROOT_APP.exists():
    raise FileNotFoundError(f"Root app.py not found at: {ROOT_APP}")

# Ensure imports resolve as if launched from repo root.
sys.path.insert(0, str(ROOT_APP.parent))
runpy.run_path(str(ROOT_APP), run_name="__main__")
