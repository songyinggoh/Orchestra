import sys

import pytest

from orchestra.providers._cli_common import managed_proc


@pytest.mark.asyncio
async def test_managed_proc_kills_on_exception():
    cmd = [sys.executable, "-c", "import time; time.sleep(60)"]
    proc_ref = None
    with pytest.raises(RuntimeError):
        async with managed_proc(*cmd) as proc:
            proc_ref = proc
            raise RuntimeError("simulated")
    assert proc_ref.returncode is not None


@pytest.mark.asyncio
async def test_managed_proc_normal_exit():
    cmd = [sys.executable, "-c", "print('hello')"]
    async with managed_proc(*cmd, stdin=None) as proc:
        await proc.wait()
    assert proc.returncode == 0
