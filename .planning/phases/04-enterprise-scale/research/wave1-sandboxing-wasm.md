# Wave 1 Research: Sandboxing — gVisor, Kata Containers & Wasm

**Task:** T-4.2 (gVisor/Kata), T-4.3 (Wasm Tool Sandbox)
**Sources:** gVisor docs (gvisor.dev), Kata Containers (GitHub), wasmtime-py (GitHub), Bytecode Alliance (WASI)
**Date:** 2026-03-12

---

## 1. gVisor Architecture

### Overview
gVisor is a user-space kernel written in Go that intercepts and implements Linux syscalls, providing a strong isolation boundary without the overhead of full VMs.

### Components
- **Sentry:** User-space kernel that intercepts application syscalls via ptrace or KVM. Implements ~70% of Linux syscall surface.
- **Gofer:** File proxy process. All host filesystem access goes through Gofer via 9P protocol. Sentry never directly accesses host FS.
- **runsc:** OCI-compatible container runtime. Drop-in replacement for runc.

### Syscall Flow
```
Application → syscall → Sentry (user-space) → filtered host syscall
                                             → or emulated in Sentry
```

### Kubernetes Integration
```yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: gvisor
handler: runsc
overhead:
  podFixed:
    memory: "64Mi"
    cpu: "50m"
scheduling:
  nodeSelector:
    orchestra.dev/sandbox: "gvisor"
```

Pod usage:
```yaml
spec:
  runtimeClassName: gvisor
  containers:
    - name: agent
      image: orchestra-agent:latest
```

### Performance Characteristics

| Operation | gVisor vs runc | Notes |
|-----------|---------------|-------|
| CPU compute | ~5-10% overhead | Syscall interception cost |
| Network I/O | ~10-20% overhead | Netstack reimplementation |
| Disk I/O | ~15-30% overhead | 9P protocol via Gofer |
| Memory | +64Mi base | Sentry process overhead |
| Startup | +200-500ms | Sentry initialization |

**For Orchestra:** Agent workloads are I/O-bound (API calls to LLM providers), not disk-bound. gVisor overhead is **negligible** for this use case.

### Limitations
- Not all syscalls supported (~70% coverage)
- No GPU passthrough (relevant if local model inference)
- `/proc` and `/sys` partially emulated
- Some Python packages with C extensions may hit unsupported syscalls

### Security Properties
- **Defense in depth:** Even if container escape vulnerability exists in runc, gVisor's user-space kernel blocks it
- **Reduced attack surface:** Only ~70 host syscalls used by Sentry (vs ~300+ for runc)
- **No shared kernel:** Each pod gets its own Sentry instance

---

## 2. Kata Containers Architecture

### Overview
Kata Containers runs each container/pod inside a lightweight virtual machine (micro-VM), providing hardware-level isolation via CPU virtualization (VT-x/AMD-V).

### Components
- **kata-runtime:** OCI-compatible runtime (replaces runc)
- **kata-agent:** Runs inside the micro-VM, manages container lifecycle
- **Hypervisor:** QEMU, Cloud Hypervisor, or Firecracker
- **Guest kernel:** Minimal Linux kernel inside VM

### Isolation Model
```
Host Kernel → Hypervisor (QEMU/Firecracker) → Guest Kernel → Container
```

### Kubernetes Integration
```yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: kata
handler: kata-qemu  # or kata-fc (Firecracker), kata-clh (Cloud Hypervisor)
overhead:
  podFixed:
    memory: "128Mi"
    cpu: "100m"
```

### Performance Characteristics

| Operation | Kata vs runc | Notes |
|-----------|-------------|-------|
| CPU compute | ~1-3% overhead | Hardware virtualization is efficient |
| Network I/O | ~5-10% overhead | virtio-net |
| Disk I/O | ~10-15% overhead | virtio-blk/9p |
| Memory | +128Mi base | Guest kernel + agent |
| Startup | +1-3s | VM boot time |

### When to Use Kata vs gVisor

| Factor | gVisor | Kata |
|--------|--------|------|
| Isolation strength | Strong (user-space kernel) | Strongest (hardware VM) |
| Startup time | ~200-500ms | ~1-3s |
| Memory overhead | ~64Mi | ~128Mi |
| Syscall compatibility | ~70% | ~100% (full Linux kernel) |
| GPU support | No | Yes (with PCI passthrough) |
| Cloud support | GKE native, EKS via DaemonSet | Custom AMI/bare metal |
| Best for | Most workloads | Untrusted code, GPU, compliance |

**Recommendation for Orchestra:**
- **gVisor** for agent workers (lower overhead, sufficient isolation)
- **Kata** for executing untrusted user-provided tools (maximum isolation)
- **Wasm** for lightweight tool execution (fastest, most restrictive)

---

## 3. Wasmtime-py: Python Wasm Runtime

### Overview
`wasmtime-py` is the Python binding for Wasmtime, a fast and secure WebAssembly runtime from the Bytecode Alliance.

### Installation
```bash
pip install wasmtime>=23.0.0
```

### Basic Usage
```python
import wasmtime

# Create engine with resource limits
config = wasmtime.Config()
config.consume_fuel = True  # Enable CPU limiting via fuel
config.epoch_interruption = True  # Enable timeout interruption

engine = wasmtime.Engine(config)
store = wasmtime.Store(engine)

# Set resource limits
store.set_fuel(1_000_000)  # CPU budget (fuel units)
store.set_epoch_deadline(1)  # Interrupt after 1 epoch

# Load and instantiate module
module = wasmtime.Module.from_file(engine, "tool.wasm")
instance = wasmtime.Instance(store, module, [])

# Call exported function
result = instance.exports(store)["run"](store, input_data)
```

### Resource Limits

| Resource | Mechanism | Example |
|----------|-----------|---------|
| CPU time | Fuel consumption | `store.set_fuel(1_000_000)` |
| Wall time | Epoch interruption | Background thread increments epoch |
| Memory | Module memory limits | `wasmtime.Memory` with max pages |
| Stack | Config option | `config.max_wasm_stack = 1048576` (1MB) |

### Fuel-Based CPU Limiting
```python
# Set fuel budget
store.set_fuel(10_000_000)  # Each Wasm instruction consumes ~1 fuel

# Execute
try:
    result = func(store, *args)
except wasmtime.WasmtimeError as e:
    if "fuel" in str(e):
        raise ToolTimeoutError("Tool exceeded CPU budget")
```

### Epoch-Based Wall Time Limiting
```python
import threading

def epoch_ticker(engine, interval=1.0):
    """Increment epoch every second."""
    while True:
        time.sleep(interval)
        engine.increment_epoch()

# Start ticker
threading.Thread(target=epoch_ticker, args=(engine,), daemon=True).start()

# Set deadline (2 epochs = ~2 seconds)
store.set_epoch_deadline(2)
```

### Memory Limiting
```python
# Create memory with limits
memory_type = wasmtime.MemoryType(
    wasmtime.Limits(min=1, max=256)  # 1-256 pages (64KB each = 16MB max)
)

# Or via module validation
# Reject modules that declare > 256 pages
for imp in module.imports:
    if isinstance(imp.type, wasmtime.MemoryType):
        if imp.type.limits.max > 256:
            raise ToolValidationError("Tool requests too much memory")
```

---

## 4. WASI: WebAssembly System Interface

### Overview
WASI defines a portable syscall interface for Wasm modules, using a **capability-based security model** where access is explicitly granted.

### Capability Model
By default, a Wasm module has **zero capabilities** — no filesystem, no network, no environment variables, no clock. Each capability must be explicitly granted:

```python
from wasmtime import WasiConfig

wasi_config = WasiConfig()

# Grant specific capabilities (or don't!)
# wasi_config.preopen_dir("/data", "/data")  # FS access — DON'T for tools
# wasi_config.inherit_stdin()   # stdin — DON'T
# wasi_config.inherit_stdout()  # stdout — MAYBE (for tool output)
# wasi_config.inherit_stderr()  # stderr — MAYBE (for debugging)
# wasi_config.inherit_env()     # env vars — DON'T

# For Orchestra tools: grant ONLY stdout for output
wasi_config.inherit_stdout()
```

### WASI Preview Versions

| Version | Status | Features |
|---------|--------|----------|
| Preview 1 | Stable | Basic FS, clock, random, args, env |
| Preview 2 | In progress | Component Model, async, sockets, HTTP |

**Recommendation:** Target Preview 1 for initial implementation. Preview 2 adds HTTP outbound which some tools may need later.

### Restricting Tool Execution
```python
class WasmToolSandbox:
    """Execute Orchestra tools in Wasm sandbox with zero capabilities."""

    def __init__(self):
        config = wasmtime.Config()
        config.consume_fuel = True
        config.epoch_interruption = True
        self.engine = wasmtime.Engine(config)
        self._start_epoch_ticker()

    def execute(self, wasm_bytes: bytes, input_data: bytes,
                fuel: int = 10_000_000,
                timeout_epochs: int = 5,
                max_memory_pages: int = 256) -> bytes:
        """Execute a tool with strict resource limits."""
        store = wasmtime.Store(self.engine)
        store.set_fuel(fuel)
        store.set_epoch_deadline(timeout_epochs)

        # WASI with zero capabilities (no FS, no net, no env)
        wasi_config = WasiConfig()
        store.set_wasi(wasi_config)

        # Validate module
        module = wasmtime.Module(self.engine, wasm_bytes)
        self._validate_module(module, max_memory_pages)

        # Link WASI
        linker = wasmtime.Linker(self.engine)
        linker.define_wasi()

        # Instantiate and run
        instance = linker.instantiate(store, module)
        run = instance.exports(store)["_start"]

        try:
            run(store)
            return self._read_output(instance, store)
        except wasmtime.WasmtimeError as e:
            if "fuel" in str(e):
                raise ToolCPUExceeded(f"Tool exceeded {fuel} fuel units")
            if "epoch" in str(e):
                raise ToolTimeoutError(f"Tool exceeded {timeout_epochs}s")
            raise ToolExecutionError(str(e))
```

---

## 5. Comparison: gVisor vs Kata vs Wasm

| Dimension | gVisor | Kata | Wasm |
|-----------|--------|------|------|
| **Isolation** | User-space kernel | Hardware VM | Language-level sandbox |
| **Startup** | ~200-500ms | ~1-3s | ~1-5ms |
| **Memory overhead** | ~64Mi | ~128Mi | ~1-10Mi |
| **Syscall compat** | ~70% | ~100% | WASI only |
| **Network access** | Yes (filtered) | Yes (virtio) | No (unless granted) |
| **FS access** | Via Gofer (filtered) | Via virtio | No (unless preopen) |
| **Python support** | Full (CPython in gVisor) | Full (native Linux) | Limited (via Wasm) |
| **Best for** | Agent pods | Untrusted code, compliance | Lightweight tools |
| **K8s integration** | RuntimeClass | RuntimeClass | Application-level |

### Orchestra Sandboxing Strategy (3 tiers)

```
Tier 1: Wasm Sandbox (T-4.3)
├── For: Lightweight, deterministic tools (parsers, formatters, calculators)
├── Properties: <5ms startup, zero capabilities, fuel-limited
└── Runtime: wasmtime-py in agent process

Tier 2: gVisor Sandbox (T-4.2)
├── For: Agent worker pods (full Python, LLM API calls)
├── Properties: ~300ms startup, filtered syscalls, network allowed
└── Runtime: runsc via RuntimeClass

Tier 3: Kata Sandbox (T-4.2, optional)
├── For: Untrusted user-provided code, compliance requirements
├── Properties: ~2s startup, full Linux, hardware isolation
└── Runtime: kata-qemu via RuntimeClass
```

---

## 6. Implementation Recommendations

### T-4.3: Wasm Tool Sandbox

**Files to create:**
- `src/orchestra/tools/wasm_runtime.py` — WasmToolSandbox class
- `src/orchestra/tools/sandbox.py` — Restriction policies (SandboxPolicy dataclass)
- `tests/unit/test_wasm_sandbox.py` — Test with sample .wasm tools

**Validation checklist:**
1. Wasm tool executes with fuel limiting
2. Wasm tool times out via epoch interruption
3. Host FS access attempt raises error
4. Network access attempt raises error
5. Memory exceeding max_pages raises error
6. Tool output captured via WASI stdout

### T-4.2: gVisor/Kata in Kubernetes

**Files to create:**
- `deploy/helm/orchestra/templates/runtimeclass-gvisor.yaml`
- `deploy/helm/orchestra/templates/runtimeclass-kata.yaml` (optional)
- `deploy/gvisor-installer-daemonset.yaml` (EKS only)

**Validation checklist:**
1. Pods start with `runtimeClassName: gvisor`
2. `dmesg` inside pod shows gVisor (not host kernel)
3. Syscall not implemented by Sentry returns ENOSYS
4. File operations route through Gofer (strace shows 9P)

---

## 7. Resolved Decisions

### Tool Compilation Pipeline (Gap 8 — RESOLVED)
- **Decision:** Native Wasm targets (Rust/C/Go) as primary compilation path
- Rust: `cargo build --target wasm32-wasip1` → ~50-500KB per tool
- Go: `GOARCH=wasm GOOS=wasip1 go build` via TinyGo
- C: `clang --target=wasm32-wasi`
- Provide `tool-template/` with minimal Rust JSON-in/JSON-out example
- **Eliminated:** Pyodide (6.4MB core, 4-5s cold start — disqualifying for server-side sandbox)
- **Eliminated:** Extism (bundles own runtime via `extism_sys`, conflicts with `wasmtime>=25.0.0` version lock)
- **Deferred to Phase 5:** componentize-py for typed Python Wasm components (toolchain still maturing)

### Tool I/O Protocol (Gap 9 — RESOLVED)
- **Decision:** stdin/stdout with JSON serialization
- Tool contract: read JSON from stdin, write JSON to stdout, exit 0 on success
- Host uses `WasiCtxBuilder` with `.stdin(pipe)` and `.stdout(pipe)` redirection
- Language-agnostic (any WASI tool that can print works)
- Debuggable locally: `echo '{"x":1}' | wasmtime tool.wasm`
- Negligible overhead vs LLM call latency (microseconds for KB-sized payloads)
- Migration to Component Model WIT interfaces (Phase 5) is non-breaking addition

### WASI Version (Gap 10 — RESOLVED)
- **Decision:** Target WASI Preview 1 (`wasm32-wasip1`) for T-4.3
- P2 Component Model deferred to Phase 5 (spec 0.3.0 shipped Feb 2026, still evolving)
- wasi:http (P2's main addition) is intentionally blocked by sandbox policy → no benefit now
- P1→P2 migration non-breaking: host detects module vs component at load time
- Tighten library pin: `wasmtime>=25.0.0` (first version with formal WASI 0.2.1 compat)

### Kata Containers (Gap 6 — RESOLVED)
- **Decision:** Defer Kata to Phase 5
- GKE (primary cloud) doesn't support Kata
- gVisor sufficient for I/O-bound agent workloads
- Wasm sandbox handles lightweight tool isolation at application level
- Helm chart `runtimeClassName` stays configurable for future Kata drop-in

## 8. Remaining Open Questions

1. **gVisor + GPU:** If local model inference is added later, gVisor won't support GPU. Need escape hatch to `runc` RuntimeClass for GPU pods.

---

## 8. Cross-References

- **K8s RuntimeClass config:** See `wave1-k8s-helm-keda-terraform.md` Section 4-5
- **gVisor on EKS:** See `wave1-k8s-helm-keda-terraform.md` Section 4 (DaemonSet)
- **Existing research:** `01-infrastructure-scalability.md`, `02-agent-iam-security.md`, `05-testing-safety-guardrails.md`
