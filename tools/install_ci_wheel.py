"""Install the single built memory wheel using paths rather than shell wildcards."""

import subprocess
import sys
from pathlib import Path

wheels = list(Path("dist").glob("aelix_memory-*.whl"))
if len(wheels) != 1:
    raise SystemExit("CI expects exactly one built Aelix Memory wheel.")
subprocess.run(
    [
        "uv",
        "pip",
        "install",
        "--python",
        sys.executable,
        "--reinstall",
        "--no-deps",
        str(wheels[0]),
    ],
    check=True,
)
