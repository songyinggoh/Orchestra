import platform

import pytest


def is_gvisor_detected():
    """
    Heuristic to detect if running inside gVisor.
    gVisor typically presents a generic CPU model or unique strings in /proc/cpuinfo.
    """
    if platform.system() != "Linux":
        return False

    try:
        with open("/proc/cpuinfo") as f:
            content = f.read().lower()
            # gVisor often uses "google" or a very generic model
            return "google" in content or "gvisor" in content
    except FileNotFoundError:
        return False


@pytest.mark.skipif(not is_gvisor_detected(), reason="gVisor not detected")
def test_gvisor_filesystem_interception():
    """
    Verify that gVisor intercepts and blocks access to sensitive host files.
    """
    # This should be blocked by the gVisor sandbox even if the container has
    # theoretically high privileges.
    with pytest.raises(PermissionError):
        open("/etc/shadow")  # noqa: SIM115


@pytest.mark.skipif(not is_gvisor_detected(), reason="gVisor not detected")
def test_gvisor_syscall_filtering():
    """
    Verify that 'dangerous' syscalls are filtered/intercepted by gVisor.
    """
    # Attempting to mount a new filesystem should definitely fail in a hard sandbox.
    # In Python, we can try os.mount (on Linux) if available.
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6")
        # mount(source, target, filesystemtype, mountflags, data)
        # 21 is MS_REMOUNT for testing
        res = libc.mount(b"none", b"/", b"none", 21, None)
        assert res == -1
    except (AttributeError, OSError):
        # If mount is not available or fails, we just want to ensure it's not allowed
        pass
