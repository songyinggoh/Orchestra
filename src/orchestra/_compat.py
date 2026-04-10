"""_compat.py — optional-dependency sentinels."""
try:
    import numpy as np  # noqa: F401
    HAS_NUMPY = True
except ImportError:
    np = None  # type: ignore[assignment]
    HAS_NUMPY = False

try:
    import joserfc  # noqa: F401
    HAS_JOSERFC = True
except ImportError:
    HAS_JOSERFC = False

try:
    import watchfiles  # noqa: F401
    HAS_WATCHFILES = True
except ImportError:
    HAS_WATCHFILES = False

try:
    import rebuff  # noqa: F401
    HAS_REBUFF = True
except ImportError:
    HAS_REBUFF = False
