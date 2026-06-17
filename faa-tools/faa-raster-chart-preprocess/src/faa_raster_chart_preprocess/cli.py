from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_process_sectionals_module():
    project_root = Path(__file__).resolve().parents[2]
    module_path = project_root / "process_sectionals.py"
    spec = importlib.util.spec_from_file_location("process_sectionals", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    module = _load_process_sectionals_module()
    return module.main()
