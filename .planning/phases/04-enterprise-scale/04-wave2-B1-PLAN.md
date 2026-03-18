---
phase: 04-enterprise-scale
plan: wave2-B1
type: execute
wave: 1
depends_on: []
files_modified:
  - src/orchestra/identity/types.py
autonomous: true
requirements: [T-4.6, T-4.7]
must_haves:
  truths:
    - "DelegationContext supports chain operations: root(), delegate_to(), to_baggage_value(), from_baggage_value() (DD-5)"
    - "DelegationDepthExceededError raised when depth >= max_depth in delegate_to()"
    - "UCANCapability and UCANToken are importable type contracts (DD-4 resource pointer format)"
    - "SecretProvider is a runtime_checkable Protocol with get_secret/put_secret/delete_secret"
  artifacts:
    - path: "src/orchestra/identity/types.py"
      provides: "Type contracts: DelegationContext, UCANCapability, UCANToken, SecretProvider"
      min_lines: 70
  key_links:
    - from: "src/orchestra/identity/delegation.py"
      to: "src/orchestra/identity/types.py"
      via: "from orchestra.identity.types import DelegationContext, UCANCapability"
      pattern: "from orchestra\\.identity\\.types import"
    - from: "src/orchestra/identity/ucan.py"
      to: "src/orchestra/identity/types.py"
      via: "from orchestra.identity.types import UCANCapability, UCANToken"
      pattern: "from orchestra\\.identity\\.types import"
---

<objective>
Define type contracts for the entire identity and authorization subsystem (Track B equivalent of A1).

Purpose: Plans B2, B3, B4 all import DelegationContext, UCANCapability, UCANToken, and SecretProvider. Creating these contracts in Wave 1 lets B2 and B3 run in parallel (both depend on B1, not on each other). This plan runs parallel to A1.
Output: src/orchestra/identity/types.py with all identity/authorization type contracts.
</objective>

<execution_context>
@C:/Users/user/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/user/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/04-enterprise-scale/PLAN.md
@.planning/phases/04-enterprise-scale/WAVE2-DESIGN-DECISIONS.md
</context>

<tasks>

<task type="auto" tdd="true" id="B1.1" name="Create identity type contracts">
  <files>src/orchestra/identity/types.py</files>
  <behavior>
    - DelegationContext.root('did:test:1') creates chain=('did:test:1',), depth=0, issuer_did='did:test:1'
    - DelegationContext.delegate_to('did:test:2') creates chain=('did:test:1','did:test:2'), depth=1
    - DelegationContext.delegate_to raises DelegationDepthExceededError when depth >= max_depth
    - DelegationContext.to_baggage_value() returns comma-separated DID chain string
    - DelegationContext.from_baggage_value('did:A,did:B') reconstructs chain correctly
    - UCANToken.is_expired returns True when time.time() > expires_at
    - SecretProvider isinstance check works via runtime_checkable Protocol
  </behavior>
  <action>
Create src/orchestra/identity/types.py with the following exact content. This is contracts only — no external dependencies, no IO:

```python
# src/orchestra/identity/types.py
"""Type contracts for the identity and authorization subsystem.

These are the interfaces that B2 (AgentIdentity/Discovery), B3 (UCAN), and B4 (ACL integration)
implement against. No implementation logic here — contracts only.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class DelegationContext:
    """Tracks the delegation chain from root to current agent (DD-5).

    Serialized into OTel Baggage as: orchestra.delegation_chain=did:A,did:B,did:C
    """
    chain: tuple[str, ...]     # DIDs from root to current: ("did:A", "did:B", "did:C")
    issuer_did: str            # Who started the chain (chain[0])
    current_did: str           # Current agent (chain[-1])
    depth: int                 # len(chain) - 1
    max_depth: int = 3         # From root AgentIdentity.max_delegation_depth (default=3)

    @classmethod
    def root(cls, did: str, max_depth: int = 3) -> DelegationContext:
        """Create a root delegation context for an agent."""
        return cls(
            chain=(did,),
            issuer_did=did,
            current_did=did,
            depth=0,
            max_depth=max_depth,
        )

    def delegate_to(self, child_did: str) -> DelegationContext:
        """Extend the delegation chain to a child agent.

        Raises DelegationDepthExceededError if depth >= max_depth.
        """
        if self.depth >= self.max_depth:
            from orchestra.core.errors import DelegationDepthExceededError
            raise DelegationDepthExceededError(
                f"Delegation depth {self.depth} >= max_depth {self.max_depth}. "
                f"Chain: {','.join(self.chain)}"
            )
        new_chain = self.chain + (child_did,)
        return DelegationContext(
            chain=new_chain,
            issuer_did=self.issuer_did,
            current_did=child_did,
            depth=len(new_chain) - 1,
            max_depth=self.max_depth,
        )

    def to_baggage_value(self) -> str:
        """Serialize for OTel Baggage header (DD-5).
        Key: orchestra.delegation_chain
        Value: did:A,did:B,did:C
        """
        return ",".join(self.chain)

    @classmethod
    def from_baggage_value(cls, value: str, max_depth: int = 3) -> DelegationContext:
        """Reconstruct from OTel Baggage value. Treats malformed as anonymous (DD-5).

        Callers should catch ValueError and apply deny-all if malformed.
        """
        dids = tuple(d.strip() for d in value.split(",") if d.strip())
        if not dids:
            raise ValueError(f"Cannot parse delegation chain from baggage value: {value!r}")
        return cls(
            chain=dids,
            issuer_did=dids[0],
            current_did=dids[-1],
            depth=len(dids) - 1,
            max_depth=max_depth,
        )


@dataclass(frozen=True)
class UCANCapability:
    """A UCAN capability grant using Orchestra resource pointer format (DD-4).

    Resource format:
        orchestra:tools/{tool_name}        e.g., orchestra:tools/web_search
        orchestra:agents/{agent_id}        e.g., orchestra:agents/summarizer
        orchestra:workflows/{workflow_id}  e.g., orchestra:workflows/research-pipeline

    Ability verbs:
        tool/invoke     execute a tool
        agent/delegate  delegate to a sub-agent
        workflow/run    start a workflow
    """
    resource: str              # e.g., "orchestra:tools/web_search"
    ability: str               # e.g., "tool/invoke"
    max_calls: int | None = None  # Optional invocation limit per DD-4


@dataclass(frozen=True)
class UCANToken:
    """Parsed UCAN token metadata (DD-9: joserfc JWT, UCAN 0.8.1 format)."""
    raw: str                              # The raw JWT string
    issuer_did: str                       # iss
    audience_did: str                     # aud
    capabilities: tuple[UCANCapability, ...]
    not_before: int                       # nbf (Unix timestamp)
    expires_at: int                       # exp (Unix timestamp)
    nonce: str                            # nnc
    proofs: tuple[str, ...]               # prf (inline JWT strings for delegation chains)

    @property
    def is_expired(self) -> bool:
        """Returns True if the current time is past the token's expiry."""
        return time.time() > self.expires_at


@runtime_checkable
class SecretProvider(Protocol):
    """Protocol for secret storage backends (DD-7: key material storage).

    Implementations: InMemorySecretProvider (testing), VaultSecretProvider (production).
    """
    async def get_secret(self, path: str) -> bytes: ...
    async def put_secret(self, path: str, value: bytes) -> None: ...
    async def delete_secret(self, path: str) -> None: ...
```
  </action>
  <verify>
    <automated>python -c "
from orchestra.identity.types import DelegationContext, UCANCapability, UCANToken, SecretProvider
dc = DelegationContext.root('did:test:1')
dc2 = dc.delegate_to('did:test:2')
assert dc2.chain == ('did:test:1', 'did:test:2'), f'chain mismatch: {dc2.chain}'
assert dc2.depth == 1
assert dc2.to_baggage_value() == 'did:test:1,did:test:2'
dc3 = DelegationContext.from_baggage_value(dc2.to_baggage_value())
assert dc3.chain == dc2.chain
try:
    dc_deep = DelegationContext.root('a', max_depth=1)
    dc_deep.delegate_to('b')  # depth 0 -> 1, OK
    dc_deep = dc_deep.delegate_to('b')
    dc_deep.delegate_to('c')  # depth 1 >= max_depth 1 -> should raise
    print('FAIL: DelegationDepthExceededError not raised')
except Exception as e:
    print(f'depth exceeded correctly: {type(e).__name__}')
cap = UCANCapability('orchestra:tools/web_search', 'tool/invoke', max_calls=5)
import time
tok = UCANToken('jwt', 'did:a', 'did:b', (cap,), int(time.time())-120, int(time.time())-60, 'nonce', ())
assert tok.is_expired, 'Token should be expired'
print('B1 verification passed')
"
</automated>
  </verify>
  <done>DelegationContext supports chain operations, depth enforcement, and baggage serialization. UCANCapability, UCANToken, SecretProvider all importable. DelegationDepthExceededError raised correctly.</done>
</task>

</tasks>

<verification>
python -c "
from orchestra.identity.types import DelegationContext, UCANCapability, UCANToken, SecretProvider
print('B1 imports OK')
# Verify Protocol runtime_checkable works
class FakeSecretProvider:
    async def get_secret(self, path: str) -> bytes: return b''
    async def put_secret(self, path: str, value: bytes) -> None: pass
    async def delete_secret(self, path: str) -> None: pass
assert isinstance(FakeSecretProvider(), SecretProvider), 'Protocol check failed'
print('SecretProvider protocol check OK')
"
</verification>

<success_criteria>
- src/orchestra/identity/types.py exists with all 4 types
- DelegationContext chain operations work correctly
- DelegationDepthExceededError raised when depth >= max_depth
- UCANToken.is_expired works against real time.time()
- SecretProvider is runtime_checkable
- No external dependencies in this file
</success_criteria>

<output>
After completion, create .planning/phases/04-enterprise-scale/04-wave2-B1-SUMMARY.md
</output>
