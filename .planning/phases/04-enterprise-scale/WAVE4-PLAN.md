# Wave 4 Execution Plan — Ecosystem & Cryptographic Integrity

**Created:** 2026-03-14
**Status:** READY FOR EXECUTION
**Depends on:** Wave 1-3 complete.
**Tasks:** T-4.11 (A2A & ZKP), T-4.12 (Dynamic Subgraphs), T-4.13 (TypeScript SDK).

---

## T-4.11: A2A Protocol & ZKP Input Commitments

### Step 1: State Canonicalization (RFC 8785)
- Implement `orchestra.interop.zkp.jcs_canonicalize(state: dict) -> bytes`.
- Follow RFC 8785 for lexicographic sorting and number serialization.
- Add unit tests for cross-platform JSON stability (e.g., nesting, floats).

### Step 2: Pedersen Commitments (blst)
- Integrate `blst` library for BLS12-381 curve operations.
- Implement `PedersenCommitment` class in `src/orchestra/interop/zkp.py`.
- Implement RFC 9380 (Hash-to-Curve) for NUMS generator $H$.
- Implement Tier 1 (SHA-256) and Tier 2 (Pedersen) commitment logic.

### Step 3: A2A Envelope & Discovery
- Define `A2AStateTransfer` envelope with cryptographic bindings.
- Implement `DiscoveryService` for `AgentCard` resolution.

---

## T-4.12: Dynamic Subgraphs

### Step 1: Send API (Dynamic Fan-Out)
- Add `Send` dataclass to `src/orchestra/core/types.py`.
- Modify `CompiledGraph._resolve_next()` in `src/orchestra/core/compiled.py` to handle `list[Send]` return values from conditional edges.
- Implement `CompiledGraph._execute_sends()` for concurrent execution of dynamic targets.

### Step 2: YAML Serialization (ruamel.yaml)
- Implement `load_graph_yaml` and `dump_graph_yaml` using `ruamel.yaml` for round-trip support.
- Add Pydantic-based schema validation for the hydrated graph structure.

### Step 3: Hot-Reloading (watchfiles)
- Implement `GraphHotReloader` using `watchfiles` to monitor directory changes.
- Implement atomic swap in `GraphRegistry` to update graph definitions without disrupting in-flight runs.

### Step 4: Security (Dotted-Path Validation)
- Implement a strict allowlist for dotted-path resolution in `SubgraphBuilder`.
- Add checks for maximum subgraph nesting depth (default: 10).

---

## T-4.13: TypeScript Client SDK

### Step 1: Scaffolding & Test Setup
- Initialize `sdk/typescript/` with `tsup`.
- Configure `vitest` for unit testing.
- Set up `msw` for network-level mocking, including SSE stream mocking patterns using `ReadableStream`.

### Step 2: Type Generation & Client Implementation
- Implement `extract-openapi.py` to dump the FastAPI schema.
- Use `openapi-typescript` to generate type definitions from the schema.
- Implement `OrchestraClient` using `openapi-fetch`, adding middleware support for authentication.

### Step 3: Streaming Client Implementation
- Implement `streamRunEvents` using native `fetch` and `fetch-event-stream`.
- Add support for `Last-Event-ID` reconnection and `AbortSignal` for request cancellation.
- Define a discriminated union for all SSE event types to ensure type-safe stream consumption.

---

## Verification Strategy

```bash
# T-4.11: Cryptography
pytest tests/unit/test_zkp_commitments.py
pytest tests/unit/test_jcs.py

# T-4.12: Dynamic Logic
pytest tests/integration/test_dynamic_subgraphs.py

# T-4.13: SDK
cd sdk/typescript && npm test
```
