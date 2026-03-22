"""Tool Access Control Lists (ACLs) for agent security.

Enables fine-grained control over which tools an agent is authorized
to execute based on name, patterns, or namespaces.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orchestra.identity.agent_identity import RevocationList
    from orchestra.identity.types import UCANCapability, UCANToken


def validate_narrowing(
    parent_caps: Iterable[UCANCapability],
    child_caps: Iterable[UCANCapability],
) -> bool:
    """Verify that child capabilities are a strict subset of parent capabilities.

    DD-4 rule: capabilities can only narrow, never widen.  For every capability
    in *child_caps*, there must be a matching capability in *parent_caps* such
    that:

    * The child resource is identical to the parent resource, OR the child
      resource is a sub-path of the parent resource (parent ends with ``/*``
      and the child resource starts with the parent's namespace prefix), OR
      the parent resource is the explicit wildcard ``orchestra:tools/*``.
    * The child ability matches the parent ability, OR the parent ability is
      ``"*"`` (grants all abilities).

    A child capability that has no covering parent is a widening attempt and
    causes the function to return ``False`` immediately.

    Args:
        parent_caps: Capabilities granted by the parent (issuing) UCAN token.
        child_caps: Capabilities claimed by the child (delegated) UCAN token.

    Returns:
        ``True`` if every child capability is covered by at least one parent
        capability; ``False`` if any child capability is broader than or
        outside the parent's grant.
    """
    parent_list = list(parent_caps)
    for child in child_caps:
        covered = False
        for parent in parent_list:
            # Ability check: parent "*" covers any child ability;
            # otherwise must match exactly.
            ability_ok = parent.ability == "*" or parent.ability == child.ability

            # Resource check — four cases:
            # 1. Exact match
            # 2. Parent is the explicit tools wildcard "orchestra:tools/*"
            # 3. Parent ends with "/*" — child must be a sub-resource within
            #    that namespace (e.g. parent "ns:tools/*" covers "ns:tools/x")
            # 4. Child is a wildcard that is covered by the parent wildcard
            if parent.resource == child.resource or parent.resource == "orchestra:tools/*":
                resource_ok = True
            elif parent.resource.endswith("/*"):
                # parent namespace prefix: "orchestra:tools" (strip trailing "/*")
                parent_ns = parent.resource[:-2]
                # child must start with that prefix followed by "/" or be equal
                resource_ok = child.resource == parent_ns or child.resource.startswith(
                    parent_ns + "/"
                )
            else:
                resource_ok = False

            if ability_ok and resource_ok:
                covered = True
                break

        if not covered:
            return False
    return True


@dataclass(frozen=True)
class ToolACL:
    """Access control list for tool execution."""

    allowed_tools: frozenset[str] = field(default_factory=frozenset)
    denied_tools: frozenset[str] = field(default_factory=frozenset)
    allow_patterns: tuple[str, ...] = field(default_factory=tuple)
    deny_patterns: tuple[str, ...] = field(default_factory=tuple)
    allow_all: bool = False

    def __post_init__(self) -> None:
        """Coerce mutable collection types to their immutable equivalents.

        Callers passing ``set(...)`` or ``[...]`` continue to work without
        changes.  ``frozen=True`` prevents direct attribute assignment, so
        ``object.__setattr__`` is required.
        """
        if not isinstance(self.allowed_tools, frozenset):
            object.__setattr__(self, "allowed_tools", frozenset(self.allowed_tools))
        if not isinstance(self.denied_tools, frozenset):
            object.__setattr__(self, "denied_tools", frozenset(self.denied_tools))
        if not isinstance(self.allow_patterns, tuple):
            object.__setattr__(self, "allow_patterns", tuple(self.allow_patterns))
        if not isinstance(self.deny_patterns, tuple):
            object.__setattr__(self, "deny_patterns", tuple(self.deny_patterns))

    def is_authorized(
        self,
        tool_name: str,
        *,
        ucan: UCANToken | None = None,
        agent_did: str | None = None,
        revocation_list: RevocationList | None = None,
    ) -> bool:
        """Check if a tool is authorized.

        DD-4 rules (applied in order):
        0. Revocation gate: if agent_did is provided and revocation_list is
           provided, the DID is checked BEFORE anything else.  A revoked agent
           is denied regardless of ACL or UCAN state.
           Raises AgentRevokedException (not returns False) so the caller can
           distinguish "denied" from "revoked".
        1. ACL deny-list always wins (deny_patterns and denied_tools).
        2. If ucan is None: ACL-only mode (backward compatible, no behavior change).
        3. If ucan is provided AND expired: DENY ALL tools (do NOT fall back to ACL).
        4. If ucan is provided AND valid: effective = strict intersection(ACL, UCAN).
           Tool must appear in ucan.capabilities with resource=orchestra:tools/{name}
           and ability=tool/invoke.

        Args:
            tool_name: The tool being requested.
            ucan: Optional UCAN token to intersect with the ACL.
            agent_did: Optional DID of the requesting agent.  Required for
                revocation checking.  When None, revocation is not checked.
            revocation_list: Optional RevocationList.  When both agent_did and
                revocation_list are provided, the DID is checked against the
                list before any other rule.  When None (default), revocation
                checking is skipped — existing callers are unaffected.

        Raises:
            AgentRevokedException: If agent_did is in revocation_list.
        """
        # Step 0: Revocation gate — checked before deny lists and UCAN.
        if (
            agent_did is not None
            and revocation_list is not None
            and revocation_list.is_revoked(agent_did)
        ):
            from orchestra.core.errors import AgentRevokedException

            raise AgentRevokedException(agent_did)

        # Step 1: Explicit denial always wins
        if tool_name in self.denied_tools:
            return False

        for pattern in self.deny_patterns:
            if fnmatch.fnmatch(tool_name, pattern):
                return False

        # Step 2: ACL-only mode (backward compatible)
        if ucan is None:
            return self._check_acl_only(tool_name)

        # Step 3: expired UCAN = deny all (DD-4 rule 4)
        if ucan.is_expired:
            return False

        # Step 4: must pass ACL check first
        if not self._check_acl_only(tool_name):
            return False

        # Step 5: must also appear in UCAN grants.
        # DD-4: capabilities can only narrow, never widen.
        # Allowed resource forms:
        #   exact:    "orchestra:tools/{tool_name}"
        #   wildcard: "orchestra:tools/*"  (explicit — grants all tools)
        # NOT allowed: bare "orchestra:tools" (implicit parent-scope passthrough)
        tool_authorized = False
        for cap in ucan.capabilities:
            resource_match = (
                cap.resource == f"orchestra:tools/{tool_name}"
                or cap.resource == "orchestra:tools/*"
            )
            ability_match = cap.ability == "tool/invoke" or cap.ability == "*"

            if resource_match and ability_match:
                tool_authorized = True
                break

        if not tool_authorized:
            return False  # Not in UCAN = denied

        # Step 6: delegation chain narrowing validation (DD-4).
        # When the UCAN has proof tokens (prf chain), each child token's
        # capabilities must be a strict subset of its parent's capabilities.
        # We validate the chain by parsing the embedded proof UCANs in order.
        if ucan.proofs:
            self._validate_proof_chain(ucan)

        return True

    def _validate_proof_chain(self, ucan: UCANToken) -> None:
        """Validate that each link in the proof chain only narrows capabilities.

        Iterates over ``ucan.proofs`` (inline JWT strings or serialised
        UCANToken representations) and checks that the capabilities in the
        child token do not exceed those in the parent.

        Raises:
            CapabilityDeniedError: If any child token claims capabilities that
                are not covered by its parent, indicating a widening attempt.
        """
        from orchestra.core.errors import CapabilityDeniedError

        # Build the parent–child pairs: proofs are ordered from root → issuer,
        # so proofs[0] is the root grant and the *current* ucan is the leaf.
        # We treat each adjacent pair (proofs[i], proofs[i+1]) as parent/child,
        # and finally (proofs[-1], ucan) as the last parent/child pair.
        proof_ucans: list[UCANToken] = []
        for raw_proof in ucan.proofs:
            parsed = self._parse_proof(raw_proof)
            if parsed is not None:
                proof_ucans.append(parsed)

        # Build the full chain: [proof_0, proof_1, ..., proof_n, leaf_ucan]
        full_chain = proof_ucans + [ucan]

        for i in range(len(full_chain) - 1):
            parent_token = full_chain[i]
            child_token = full_chain[i + 1]
            if not validate_narrowing(parent_token.capabilities, child_token.capabilities):
                raise CapabilityDeniedError(
                    f"Delegation chain widening detected at depth {i + 1}: "
                    f"child capabilities are not a subset of parent capabilities. "
                    "This may indicate a privilege escalation attempt (DD-4)."
                )

    @staticmethod
    def _parse_proof(raw: str) -> UCANToken | None:
        """Attempt to deserialise a proof string into a UCANToken.

        Proofs may be stored as serialised UCANToken ``repr``-style strings or
        as raw JWT strings.  We support two formats:
          1. A ``UCANToken`` instance serialised by the UCAN library (dict form).
          2. A plain JWT string — in this case we skip validation (we cannot
             verify the signature without the issuer's public key, and the
             proof is treated as opaque).

        Returns ``None`` when the proof cannot be parsed so that the caller
        can skip that entry rather than crash.
        """
        import json as _json

        from orchestra.identity.types import UCANCapability, UCANToken

        # Try JSON-serialised UCANToken dict first.
        try:
            data = _json.loads(raw)
            if isinstance(data, dict) and "capabilities" in data:
                caps = tuple(
                    UCANCapability(
                        resource=c["resource"],
                        ability=c["ability"],
                        max_calls=c.get("max_calls"),
                    )
                    for c in data.get("capabilities", [])
                )
                return UCANToken(
                    raw=raw,
                    issuer_did=data.get("issuer_did", ""),
                    audience_did=data.get("audience_did", ""),
                    capabilities=caps,
                    not_before=data.get("not_before", 0),
                    expires_at=data.get("expires_at", 0),
                    nonce=data.get("nonce", ""),
                    proofs=tuple(data.get("proofs", [])),
                )
        except Exception:
            pass

        # Opaque JWT string — cannot decode without public key; skip.
        return None

    def _check_acl_only(self, tool_name: str) -> bool:
        """Original ACL-only authorization logic."""
        # Check allow-all
        if self.allow_all:
            return True

        # Explicit allowance
        if tool_name in self.allowed_tools:
            return True

        for pattern in self.allow_patterns:
            if fnmatch.fnmatch(tool_name, pattern):
                return True

        return False

    def check_ucan_call_limit(
        self,
        tool_name: str,
        ucan: UCANToken,
        call_counts: dict[str, int],
    ) -> bool:
        """Check and decrement UCAN max_calls for a tool.

        call_counts is a mutable dict on ExecutionContext (not persisted).
        Returns True if call is within limit (and increments counter).
        Returns False if max_calls exhausted.
        """
        for cap in ucan.capabilities:
            # DD-4: same narrowing rule as is_authorized — exact or explicit wildcard only.
            resource_match = (
                cap.resource == f"orchestra:tools/{tool_name}"
                or cap.resource == "orchestra:tools/*"
            )
            if resource_match and (cap.ability == "tool/invoke" or cap.ability == "*"):
                if cap.max_calls is None:
                    return True  # Unlimited
                current = call_counts.get(tool_name, 0)
                if current >= cap.max_calls:
                    return False
                call_counts[tool_name] = current + 1
                return True
        return False

    @classmethod
    def allow_list(cls, tools: Iterable[str]) -> ToolACL:
        """Create an ACL that only allows specified tools."""
        return cls(allowed_tools=frozenset(tools), allow_all=False)

    @classmethod
    def deny_list(cls, tools: Iterable[str]) -> ToolACL:
        """Create an ACL that allows everything except specified tools."""
        return cls(denied_tools=frozenset(tools), allow_all=True)

    @classmethod
    def open(cls) -> ToolACL:
        """Create an ACL that allows all tools."""
        return cls(allow_all=True)


class UnauthorizedToolError(Exception):
    """Raised when an agent attempts to call a tool not authorized by its ACL."""

    def __init__(self, tool_name: str, agent_name: str) -> None:
        self.tool_name = tool_name
        self.agent_name = agent_name
        super().__init__(f"Agent '{agent_name}' is not authorized to execute tool '{tool_name}'.")
