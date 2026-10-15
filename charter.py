#!/usr/bin/env python3
"""Charter launcher, for any platform and any directory.

    python charter.py serve [<agent-context-folder>]
    python charter.py check --context <agent-context-folder>

Running a script puts its own folder first on the import path, so this works
wherever it is started from.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
