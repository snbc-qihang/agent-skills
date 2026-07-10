#!/usr/bin/env python3
"""仓库内本地发布入口。"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.local_publish import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
