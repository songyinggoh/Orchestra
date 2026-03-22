from orchestra.memory.compression import StateCompressor


def test_compression_roundtrip():
    compressor = StateCompressor()
    data = {"name": "test", "tags": ["a", "b", "c"], "nested": {"val": 42}}

    compressed = compressor.compress(data)
    assert isinstance(compressed, bytes)

    decompressed = compressor.decompress(compressed)
    assert decompressed == data


def test_compression_size_reduction():
    compressor = StateCompressor()
    # Large repetitive data
    large_data = "hello world " * 1000

    compressed = compressor.compress(large_data)
    # Raw msgpack would be slightly larger than string length
    # zstd should smash this
    assert len(compressed) < len(large_data) / 10


def test_compression_level():
    c1 = StateCompressor(level=1)
    c2 = StateCompressor(level=10)
    data = {"large": "data" * 1000}

    comp1 = c1.compress(data)
    comp2 = c2.compress(data)

    # Level 10 should be smaller than or equal to level 1
    assert len(comp2) <= len(comp1)


def test_compression_none():
    compressor = StateCompressor()
    compressed = compressor.compress(None)
    assert compressor.decompress(compressed) is None
