---
phase: 04-enterprise-scale
plan: wave2-C1
type: execute
wave: 5
depends_on: [wave2-A4, wave2-B4]
files_modified:
  - src/orchestra/core/context.py
  - tests/unit/test_wave2_integration.py
autonomous: true
requirements: [T-4.4, T-4.5, T-4.6, T-4.7]
must_haves:
  truths:
    - "ExecutionContext carries identity, ucan_token, tenant_id, delegation_context, ucan_call_counts (all Optional)"
    - "End-to-end Wave 2 flow passes: identity -> signed card -> discovery -> UCAN issue -> ACL intersection -> budget debit -> cost routing"
    - "No existing ExecutionContext usage broken (all new fields default to None)"
    - "All Wave 2 subsystems wired together in one integration test"
  artifacts:
    - path: "src/orchestra/core/context.py"
      provides: "ExecutionContext extended with identity, ucan_token, tenant_id, delegation_context, ucan_call_counts"
      contains: "tenant_id"
    - path: "tests/unit/test_wave2_integration.py"
      provides: "End-to-end integration test covering all Wave 2 subsystems in sequence"
      min_lines: 100
  key_links:
    - from: "src/orchestra/core/context.py"
      to: "src/orchestra/identity/types.py"
      via: "TYPE_CHECKING import for DelegationContext type hint"
      pattern: "DelegationContext"
    - from: "tests/unit/test_wave2_integration.py"
      to: "src/orchestra/identity/agent_identity.py"
      via: "from orchestra.identity import AgentIdentity"
      pattern: "AgentIdentity"
    - from: "tests/unit/test_wave2_integration.py"
      to: "src/orchestra/routing/router.py"
      via: "from orchestra.routing import CostAwareRouter"
      pattern: "CostAwareRouter"
    - from: "tests/unit/test_wave2_integration.py"
      to: "src/orchestra/cost/persistent_budget.py"
      via: "from orchestra.cost import PersistentBudgetStore"
      pattern: "PersistentBudgetStore"
---

<objective>
Extend ExecutionContext with Wave 2 fields and validate the full system with an end-to-end integration test.

Purpose: This is the sync plan (C1) that wires both tracks together. ExecutionContext is the runtime carrier that connects identity (Track B) with cost routing (Track A) — agents need to carry their identity, UCAN token, tenant ID, and delegation chain in a single context object. The integration test proves all subsystems interoperate correctly.
Output: Extended context.py (backward compatible), end-to-end integration test with 1 comprehensive test function.
</objective>

<execution_context>
@C:/Users/user/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/user/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/04-enterprise-scale/PLAN.md
@.planning/phases/04-enterprise-scale/WAVE2-DESIGN-DECISIONS.md

<interfaces>
<!-- Track A outputs (from A2, A3, A4 SUMMARYs) -->
```python
# From orchestra.routing
from orchestra.routing import CostAwareRouter, ModelOption, SelectionFallback
from orchestra.routing.types import BudgetConstraint, RoutingDecision

# CostAwareRouter.select_model() returns RoutingDecision
decision = await router.select_model(
    options, task_description, estimated_tokens,
    budget=BudgetConstraint(max_cost_usd=0.005),
    fallback=SelectionFallback.FAIL_FAST,
)

# From orchestra.cost
from orchestra.cost import PersistentBudgetStore, TenantBudgetManager
store = PersistentBudgetStore(":memory:")
await store.initialize()
await store.create_account("tenant-1", None, 10.0, "monthly")
remaining = await store.check_and_debit("tenant-1", 2.50, "run-1", "gpt-4o", "key-1")
```

<!-- Track B outputs (from B2, B3, B4 SUMMARYs) -->
```python
# From orchestra.identity
from orchestra.identity import AgentIdentity, AgentCard, SignedDiscoveryProvider
from orchestra.identity.types import DelegationContext, UCANCapability, UCANToken
from orchestra.identity.ucan import UCANService
from orchestra.security.acl import ToolACL

# AgentIdentity.create() -> has .did, .sign_card(), .delegation_context
# UCANService.issue() -> JWT string
# UCANService.verify() -> UCANToken
# SignedDiscoveryProvider.register(card) -> bool
# ToolACL.is_authorized(tool, ucan=token) -> bool
```
</interfaces>
</context>

<tasks>

<task type="auto" id="C1.1" name="Extend ExecutionContext with Wave 2 fields">
  <files>src/orchestra/core/context.py</files>
  <action>
Read src/orchestra/core/context.py first to understand the existing fields and dataclass structure.

Add the following Optional fields to ExecutionContext (all default to None or empty dict for backward compatibility):

```python
from __future__ import annotations
from typing import TYPE_CHECKING, Any
if TYPE_CHECKING:
    from orchestra.identity.types import DelegationContext

# In the ExecutionContext dataclass, add these fields AFTER all existing fields:

    # Phase 4 Wave 2 extensions — all Optional for full backward compatibility
    identity: Any = None                    # AgentIdentity instance (type: Any to avoid circular imports)
    ucan_token: str | None = None           # Raw UCAN JWT string for current context
    tenant_id: str | None = None            # Budget tenant ID for cost tracking
    delegation_context: Any = None          # DelegationContext instance (serialized to OTel Baggage)
    ucan_call_counts: dict[str, int] = field(default_factory=dict)  # max_calls tracker per tool (DD-4)
```

Use TYPE_CHECKING for DelegationContext to avoid circular imports. Use Any for identity and delegation_context types in the runtime field definition.

Verify all existing fields remain in their original positions (no reordering that could break positional instantiation).
  </action>
  <verify>
    <automated>python -c "
from orchestra.core.context import ExecutionContext
# Test backward compat: create without new fields
ctx = ExecutionContext()
assert ctx.identity is None
assert ctx.ucan_token is None
assert ctx.tenant_id is None
assert ctx.delegation_context is None
assert ctx.ucan_call_counts == {}
print('ExecutionContext backward compat OK')
"</automated>
  </verify>
  <done>ExecutionContext has all 5 new fields with None/empty defaults. All existing code still works (no positional arg changes).</done>
</task>

<task type="auto" tdd="true" id="C1.2" name="End-to-end Wave 2 integration test">
  <files>tests/unit/test_wave2_integration.py</files>
  <behavior>
    - test_full_wave2_flow: Single async test that exercises the complete Wave 2 pipeline:
      1. Create parent + child AgentIdentity (did:peer:2)
      2. Parent signs an AgentCard with JWS
      3. Register card with SignedDiscoveryProvider -> accepted
      4. Register unsigned card -> rejected
      5. Parent issues UCAN to child with max_calls=5 and TTL=300s
      6. Child verifies UCAN with parent's key -> UCANToken
      7. ToolACL intersection: web_search in both ACL and UCAN -> allowed; code_exec in ACL but not UCAN -> denied
      8. Delegation chain: ctx.delegate_to(child.did) -> depth=1, baggage serialization correct
      9. PersistentBudgetStore: create account $10, debit $2.50, remaining=$7.50, second debit $8 raises BudgetExceededError
      10. CostAwareRouter: gpt-4o-mini selected over gpt-4o when budget constraint is $0.005
      11. Wire everything into ExecutionContext: identity, ucan_token, tenant_id, delegation_context
      12. Assertions on all fields pass
  </behavior>
  <action>
Create tests/unit/test_wave2_integration.py:

```python
"""End-to-end integration test for Phase 4 Wave 2.

Verifies that all Wave 2 subsystems (identity, UCAN, budget, routing) work together
when wired through ExecutionContext.

This test acts as the acceptance gate for T-4.4, T-4.5, T-4.6, T-4.7.
"""
import asyncio
import time
import pytest
import pytest_asyncio

from orchestra.identity import AgentIdentity, AgentCard, SignedDiscoveryProvider
from orchestra.identity.types import DelegationContext, UCANCapability
from orchestra.identity.ucan import UCANService
from orchestra.security.acl import ToolACL
from orchestra.cost.persistent_budget import PersistentBudgetStore
from orchestra.core.errors import BudgetExceededError
from orchestra.core.context import ExecutionContext
from orchestra.routing import CostAwareRouter, ModelOption
from orchestra.routing.types import BudgetConstraint, SelectionFallback


@pytest.mark.asyncio
async def test_full_wave2_flow():
    """Integration: identity -> UCAN -> ACL intersection -> budget -> cost routing -> ExecutionContext."""

    # --- Track B: Identity ---
    parent = AgentIdentity.create()
    child = AgentIdentity.create()

    # Sign an agent card
    card = parent.create_card(parent.did, "orchestrator", "supervisor", capabilities=["delegate", "web_search"])
    signed_card = parent.sign_card(card)
    assert signed_card.signature is not None, "Card must have JWS signature"

    # Register signed card
    discovery = SignedDiscoveryProvider()
    result = discovery.register(signed_card)
    assert result is True, "Signed card must be accepted"

    # Reject unsigned card
    unsigned_card = parent.create_card(parent.did, "bad-agent", "attacker", capabilities=[])
    # unsigned_card has signature=None -> rejected
    reject_result = discovery.register(unsigned_card)
    assert reject_result is False, "Unsigned card must be rejected (gossip poisoning defense S3)"

    # --- Track B: UCAN ---
    okp_key = parent._make_okp_key()
    ucan_service = UCANService(okp_key, parent.did)
    token = ucan_service.issue(
        audience_did=child.did,
        capabilities=[
            UCANCapability("orchestra:tools/web_search", "tool/invoke", max_calls=5),
        ],
        ttl_seconds=300,
    )
    assert isinstance(token, str) and len(token.split('.')) == 3, "Token must be 3-part JWT"

    parsed = UCANService.verify(token, okp_key, child.did)
    assert parsed.issuer_did == parent.did
    assert parsed.audience_did == child.did
    assert len(parsed.capabilities) == 1
    assert not parsed.is_expired

    # --- Track B: ACL Intersection ---
    acl = ToolACL(allowed_tools={"web_search", "code_exec"}, allow_all=False)
    assert acl.is_authorized("web_search", ucan=parsed) is True, "web_search in both ACL and UCAN -> allowed"
    assert acl.is_authorized("code_exec", ucan=parsed) is False, "code_exec in ACL but not UCAN -> denied (S7)"

    # Delegation chain
    parent_ctx = DelegationContext.root(parent.did)
    child_ctx = parent_ctx.delegate_to(child.did)
    assert child_ctx.depth == 1
    baggage = child_ctx.to_baggage_value()
    assert baggage == f"{parent.did},{child.did}"
    restored = DelegationContext.from_baggage_value(baggage)
    assert restored.chain == child_ctx.chain

    # --- Track A: Budget ---
    store = PersistentBudgetStore(":memory:")
    await store.initialize()
    await store.create_account("tenant-1", None, 10.0, "monthly")

    remaining = await store.check_and_debit("tenant-1", 2.50, "run-1", "gpt-4o", "idkey-1")
    assert abs(remaining - 7.50) < 0.01, f"Expected 7.50 remaining, got {remaining}"

    with pytest.raises(BudgetExceededError):
        await store.check_and_debit("tenant-1", 8.00, "run-2", "gpt-4o", "idkey-2")

    # --- Track A: Cost Routing ---
    router = CostAwareRouter()
    options = [
        ModelOption("gpt-4o", "openai", 0.01, 0.03, capability_score=5, latency_score=200),
        ModelOption("gpt-4o-mini", "openai", 0.001, 0.002, capability_score=3, latency_score=100),
    ]
    decision = await router.select_model(
        options,
        "simple query",
        200,
        budget=BudgetConstraint(max_cost_usd=0.005),
        fallback=SelectionFallback.FAIL_FAST,
    )
    assert decision.model.model_name == "gpt-4o-mini", "Only gpt-4o-mini fits $0.005 budget"

    # --- Sync: Wire into ExecutionContext ---
    ectx = ExecutionContext(
        identity=parent,
        ucan_token=token,
        tenant_id="tenant-1",
        delegation_context=child_ctx,
    )
    assert ectx.identity is parent
    assert ectx.ucan_token == token
    assert ectx.tenant_id == "tenant-1"
    assert ectx.delegation_context.depth == 1
    assert ectx.ucan_call_counts == {}

    # max_calls tracking
    for i in range(5):
        ok = acl.check_ucan_call_limit("web_search", parsed, ectx.ucan_call_counts)
        assert ok, f"Call {i+1} should be allowed"
    over = acl.check_ucan_call_limit("web_search", parsed, ectx.ucan_call_counts)
    assert not over, "6th call should be denied (max_calls=5 exhausted)"
```

Ensure pytest-asyncio is configured (add asyncio_mode = "auto" to pytest.ini or use @pytest.mark.asyncio decorator). If ModelOption constructor signature differs from what's used in the test, check the actual signature from router.py SUMMARY and adjust.
  </action>
  <verify>
    <automated>pytest tests/unit/test_wave2_integration.py -x -v</automated>
  </verify>
  <done>End-to-end Wave 2 flow passes. All subsystems wired through ExecutionContext. Integration test passes with 0 failures.</done>
</task>

</tasks>

<verification>
pytest tests/unit/test_wave2_integration.py -v
# Full regression sweep:
pytest tests/unit/ -x -q 2>&amp;1 | tail -20
</verification>

<success_criteria>
- test_full_wave2_flow passes end-to-end without mocks
- ExecutionContext has all 5 new fields (identity, ucan_token, tenant_id, delegation_context, ucan_call_counts)
- No existing unit tests broken (all 244+ tests still pass)
- Observable Truth S3 verified: unsigned card rejected by SignedDiscoveryProvider
- Observable Truth S6 verified: gpt-4o-mini selected over gpt-4o under budget constraint
- Observable Truth S7 verified: max_calls exhaustion enforced
</success_criteria>

<output>
After completion, create .planning/phases/04-enterprise-scale/04-wave2-C1-SUMMARY.md

Include in summary:
- Wave 2 complete status (all T-4.4 through T-4.7 satisfied)
- Test count delta (how many new tests added)
- Any integration issues found and resolved during this plan
- Observable truths verified: S3, S6, S7
</output>
