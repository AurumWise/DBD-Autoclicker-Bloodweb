from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main() -> None:
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    raise SystemExit(subprocess.call([npm, "run", "start:electron"], cwd=ROOT))


if __name__ == "__main__":
    main()
