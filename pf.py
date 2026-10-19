#!/usr/bin/env python3
"""product-finder entry point.

Run me like this:

    python pf.py check
    python pf.py demo
    python pf.py search "wax seal kit"
    python pf.py compare "wax seal kit" "resin mold"

Needs Python 3.10 or newer and no installed packages at all.
"""

import sys
from pathlib import Path

# Make sure Python can find the product_finder package when you run this file
# directly from any folder.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from product_finder.cli import main  # noqa: E402

if __name__ == "__main__":
    if sys.version_info < (3, 10):
        print(
            f"product-finder needs Python 3.10 or newer; you have "
            f"{sys.version_info.major}.{sys.version_info.minor}."
        )
        raise SystemExit(2)
    raise SystemExit(main())
