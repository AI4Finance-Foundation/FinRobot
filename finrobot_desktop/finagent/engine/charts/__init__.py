"""Chart engine package — deterministic financial chart rendering via matplotlib.

The non-interactive ``Agg`` backend is selected at package import so individual
chart modules can simply ``import matplotlib.pyplot as plt`` without each
having to re-call ``matplotlib.use("Agg")``. Python loads parent ``__init__``
modules before any submodule body, so this runs before any chart module's
own pyplot import.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
