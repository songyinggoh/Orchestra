import asyncio

import pytest

from orchestra.memory.singleflight import SingleFlight


@pytest.mark.asyncio
async def test_singleflight_coalesce():
    sf = SingleFlight[int]()
    call_count = 0

    async def slow_fetch():
        nonlocal call_count
        await asyncio.sleep(0.1)
        call_count += 1
        return 42

    # Fire 3 concurrent requests
    results = await asyncio.gather(
        sf.do("key1", slow_fetch), sf.do("key1", slow_fetch), sf.do("key1", slow_fetch)
    )

    assert results == [42, 42, 42]
    assert call_count == 1


@pytest.mark.asyncio
async def test_singleflight_exception_propagation():
    sf = SingleFlight[int]()

    async def failing_fetch():
        await asyncio.sleep(0.05)
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await asyncio.gather(sf.do("k1", failing_fetch), sf.do("k1", failing_fetch))


@pytest.mark.asyncio
async def test_singleflight_sequential_is_separate():
    sf = SingleFlight[int]()
    call_count = 0

    async def fetch():
        nonlocal call_count
        call_count += 1
        return call_count

    res1 = await sf.do("k1", fetch)
    res2 = await sf.do("k1", fetch)

    assert res1 == 1
    assert res2 == 2
    assert call_count == 2
