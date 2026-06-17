"""Backward-compatible facade re-exporting all public symbols from the process_sectionals package."""
from __future__ import annotations

from _process_sectionals.constants import *  # noqa: F401, F403
from _process_sectionals.models import *  # noqa: F401, F403
from _process_sectionals.naming import *  # noqa: F401, F403
from _process_sectionals.discovery import *  # noqa: F401, F403
from _process_sectionals.coverage import *  # noqa: F401, F403
from _process_sectionals.pipeline import *  # noqa: F401, F403
from _process_sectionals.mosaic import *  # noqa: F401, F403
from _process_sectionals.cli import *  # noqa: F401, F403

if __name__ == "__main__":
    raise SystemExit(main())  # noqa: F405
