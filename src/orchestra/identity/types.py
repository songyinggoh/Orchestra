# src/orchestra/identity/types.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class DelegationContext:
    """Tracks the delegation chain from root to current agent (DD-5)."""
    chain: tuple[str, ...]     # DIDs from root to current: ("did:A", "did:B", "did:C")
    issuer_did: str            # Who started the chain (chain[0])
    current_did: str           # Current agent (chain[-1])
    depth: int                 # len(chain) - 1
    max_depth: int = 3         # From root's AgentIdentity.max_delegation_depth

    @classmethod
    def root(cls, did: str, max_depth: int = 3) -> DelegationContext:
        return cls(chain=(did,), issuer_did=did, current_did=did, depth=0, max_depth=max_depth)

    def delegate_to(self, child_did: str) -> DelegationContext:
        if self.depth >= self.max_depth:
            from orchestra.core.errors import DelegationDepthExceededError
            raise DelegationDepthExceededError(
                f"Delegation depth {self.depth} >= max {self.max_depth}"
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
        """Serialize for OTel Baggage (DD-5)."""
        return ",".join(self.chain)

    @classmethod
    def from_baggage_value(cls, value: str, max_depth: int = 3) -> DelegationContext:
        dids = tuple(value.split(","))
        return cls(chain=dids, issuer_did=dids[0], current_did=dids[-1],
                   depth=len(dids) - 1, max_depth=max_depth)


@dataclass(frozen=True)
class UCANCapability:
    """A UCAN capability grant (DD-4 resource pointer format)."""
    resource: str   # e.g., "orchestra:tools/web_search"
    ability: str    # e.g., "tool/invoke"
    max_calls: int | None = None  # Optional invocation limit


@dataclass(frozen=True)
class UCANToken:
    """Parsed UCAN token metadata."""
    raw: str                          # The JWT string
    issuer_did: str                   # iss
    audience_did: str                 # aud
    capabilities: tuple[UCANCapability, ...]
    not_before: int                   # nbf (Unix timestamp)
    expires_at: int                   # exp (Unix timestamp)
    nonce: str                        # nnc
    proofs: tuple[str, ...]           # prf (inline JWT strings)

    @property
    def is_expired(self) -> bool:
        import time
        return time.time() > self.expires_at


@runtime_checkable
class SecretProvider(Protocol):
    """ABC for secret storage backends (DD-7: key material storage)."""
    async def get_secret(self, path: str) -> bytes: ...
    async def put_secret(self, path: str, value: bytes) -> None: ...
    async def delete_secret(self, path: str) -> None: ...
