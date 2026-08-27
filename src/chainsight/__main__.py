"""`python -m chainsight`, which is the same entry point as the `chainsight` script.

Both exist because they fail differently. The console script is absent until the package is
installed, and `python -m` works from a checkout with `src` on the path — so somebody who
has cloned the repository and not yet run `pip install -e .` still has a way in.
"""

from __future__ import annotations

import sys

from chainsight.cli import main

if __name__ == "__main__":
    sys.exit(main())
