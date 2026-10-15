"""Run the command line with isolated private state. NOT SHIPPED.

    python tests/_launch.py <state-root> <charter arguments...>

For tests that start Charter as a separate process, as an agent
host or a shell would. Its private state moves under `<state-root>`. It lives
only in the verification bundle; nothing shipped refers to it.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import private_store  # noqa: E402
from app.__main__ import main  # noqa: E402

if __name__ == "__main__":
    state_root = os.path.join(sys.argv[1], "state")
    private_store._default_root = lambda: state_root  # type: ignore[assignment]
    raise SystemExit(main(sys.argv[2:]))
