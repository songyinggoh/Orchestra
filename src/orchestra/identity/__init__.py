# src/orchestra/identity/__init__.py
from orchestra.identity.agent_identity import (
    AgentCard,
    AgentIdentity,
    AgentIdentityValidator,
    Ed25519Signer,
    RevocationList,
    Signer,
)
from orchestra.identity.discovery import SignedDiscoveryProvider
from orchestra.identity.types import DelegationContext, SecretProvider, UCANCapability, UCANToken

__all__ = [
    "AgentCard",
    "AgentIdentity",
    "AgentIdentityValidator",
    "DelegationContext",
    "DidWebManager",
    "Ed25519Signer",
    "RevocationList",
    "SecretProvider",
    "SignedDiscoveryProvider",
    "Signer",
    "UCANCapability",
    "UCANToken",
]


def __getattr__(name: str) -> object:
    if name == "DidWebManager":
        from orchestra.identity.did_web import DidWebManager

        return DidWebManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
