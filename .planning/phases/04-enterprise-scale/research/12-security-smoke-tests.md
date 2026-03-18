# Phase 4 Research: Automated Security Smoke Tests

**Researched:** 2026-03-11
**Domain:** Security Validation, CI/CD, Sandboxing, E2EE
**Status:** DRAFT

---

## 1. Hard Sandboxing: gVisor Interception

### Goal
Verify that agent workers are executing within a gVisor (`runsc`) sandbox and that syscall interception is active.

### Verification Strategy
1.  **Syscall Filtering:** Attempt a "forbidden" syscall that gVisor intercepts or blocks (e.g., `mount`, `pivot_root`, or accessing `/etc/shadow`).
2.  **Runtime Detection:** Use `dmesg` or check for specific gVisor artifacts in `/proc` (e.g., gVisor typically hides certain hardware info).
3.  **CI/CD Implementation:**
    *   Install `runsc` in the CI runner (Ubuntu-latest).
    *   Configure a Docker-in-Docker (DinD) environment to use the `runsc` runtime.
    *   Run a test container: `docker run --runtime=runsc orchestra-security-test`.

### Smoke Test (Python)
```python
def test_gvisor_active():
    # gVisor often reports a specific string in dmesg or has unique /proc entries
    try:
        with open("/proc/cpuinfo", "r") as f:
            content = f.read()
            # gVisor often presents a generic CPU model or specific flags
            assert "gvisor" in content.lower() or "google" in content.lower()
    except FileNotFoundError:
        pass

def test_syscall_blocked():
    import os
    import pytest
    with pytest.raises(PermissionError):
        # Attempting to open a host-level sensitive file should be blocked by the sandbox
        open("/etc/shadow", "r")
```

---

## 2. Hard Sandboxing: Wasmtime Isolation

### Goal
Verify that tools executed via Wasmtime are strictly isolated from the host filesystem and network.

### Verification Strategy
1.  **Negative Testing:** Create a `.wasm` module that attempts to `open()` a file outside its pre-opened directory or `connect()` to a network socket.
2.  **Assertion:** The Wasmtime runtime must trap these calls and return a `Linker` or `Trap` error.

### Smoke Test (Python)
```python
from wasmtime import Store, Module, Instance, Linker, Config, Engine

def test_wasm_filesystem_isolation():
    config = Config()
    # Ensure WASI is NOT pre-opened with host access
    engine = Engine(config)
    store = Store(engine)
    # Load a wasm module that tries to write to /tmp/exploit
    module = Module.from_file(engine, "tests/fixtures/fs_exploit.wasm")
    linker = Linker(engine)
    instance = linker.instantiate(store, module)
    
    # Execution should fail or return an error code if it tries to touch host FS
    with pytest.raises(Exception) as excinfo:
        instance.exports(store)["run"]()
    assert "filesystem error" in str(excinfo.value).lower()
```

---

## 3. NATS E2EE: Payload Opacity

### Goal
Verify that messages published to NATS are encrypted with DIDComm/JWE and cannot be read as plaintext by the NATS server or an unauthorized observer.

### Verification Strategy
1.  **Plaintext Detection:** Start a local `nats-server`.
2.  **Intercept & Inspect:** Use a "spy" client to subscribe to the subject and inspect the raw `data` field.
3.  **Assertion:** The `data` field must be a valid JWE (base64 encoded JSON) and MUST NOT contain the original plaintext string.

### Smoke Test (Python)
```python
async def test_nats_payload_is_encrypted():
    nc = await nats.connect("nats://localhost:4222")
    js = nc.jetstream()
    
    # 1. Publish using SecureNatsProvider (to be implemented in Phase 4)
    provider = SecureNatsProvider(nc, my_did_key)
    await provider.publish("agent.secret.task", {"pii": "credit-card-number"})
    
    # 2. Subscribe with a RAW (non-secure) client to see what NATS sees
    sub = await nc.subscribe("agent.secret.task")
    msg = await sub.next_msg()
    
    # 3. Assertions
    raw_payload = msg.data.decode()
    assert "credit-card-number" not in raw_payload
    assert raw_payload.startswith("ey") # JWE/JWT header start
```

---

## 4. CI/CD Integration Plan

### New Pipeline Stage: `smoke-test`
This stage runs after `test` but before `deploy`. It requires a specialized runner with:
*   Docker + gVisor (`runsc`)
*   `wasmtime-py`
*   A sidecar `nats-server`

### GitLab CI Snippet
```yaml
smoke-test:
  stage: test
  image: docker:24.0.5-dind
  services:
    - name: nats:latest
      alias: nats
  script:
    - apk add --no-cache python3 py3-pip
    - pip install orchestra[security,nats]
    - # Install runsc logic here
    - pytest tests/security/
```
