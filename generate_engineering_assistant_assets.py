#!/usr/bin/env python3
"""Compatibility entrypoint for generating engineering-assistant assets.

The generator implementation lives under `generator/` so the repo no longer
depends on a single 8k-line source file. Keep this file stable because existing
automation calls `python3 generate_engineering_assistant_assets.py`.
"""

from __future__ import annotations

from generator.legacy_generator import main


if __name__ == "__main__":
    main()
