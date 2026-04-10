"""
_compat.py — optional-dependency sentinels.

Import this module instead of importing optional libs directly at module level.
Each HAS_* flag is False when the package is absent; features that need the
package raise ImportError with an install hint when actually called.
"""
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
