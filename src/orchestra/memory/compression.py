"""State compression using msgpack and zstd."""

from __future__ import annotations

import zlib
from typing import Any, cast

try:
    import pyzstd

    HAS_PYZSTD = True
except ImportError:
    HAS_PYZSTD = False

from orchestra.memory.serialization import _default, _object_hook


class StateCompressor:
    """Compresses and decompresses arbitrary Python objects.

    Uses msgpack for serialization and pyzstd (or zlib fallback) for compression.
    """

    def __init__(self, level: int = 3) -> None:
        """
        Args:
            level: Compression level.
        """
        self.level = level

    def compress(self, value: Any) -> bytes:
        """Serialize and compress a value."""
        import msgpack

        packed = msgpack.packb(value, default=_default, use_bin_type=True)
        if HAS_PYZSTD:
            return cast(bytes, pyzstd.compress(packed, self.level))
        else:
            # map zstd level 3 to zlib (zlib range 0-9)
            z_level = min(9, max(0, self.level))
            return zlib.compress(packed, z_level)

    def decompress(self, data: bytes) -> Any:
        """Decompress and deserialize data."""
        if HAS_PYZSTD:
            try:
                decompressed = pyzstd.decompress(data)
            except Exception:
                # Fallback to zlib if data was compressed with it
                decompressed = zlib.decompress(data)
        else:
            decompressed = zlib.decompress(data)
        import msgpack

        return msgpack.unpackb(decompressed, object_hook=_object_hook, raw=False)
