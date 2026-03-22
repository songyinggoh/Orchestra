"""Centralized error hierarchy for Orchestra framework.

Every error includes: (a) what happened, (b) where, (c) how to fix.
"""

from __future__ import annotations

from typing import Any


class OrchestraError(Exception):
    """Base exception for all Orchestra errors."""


# --- Graph Errors ---


class GraphError(OrchestraError):
    """Base for graph-related errors."""


class GraphCompileError(GraphError):
    """Raised when graph compilation/validation fails."""


class UnreachableNodeError(GraphError):
    """Raised when a node has no incoming edges."""


class CycleWithoutGuardError(GraphError):
    """Raised when a cycle has no exit condition or max_turns guard."""


class StateConflictError(GraphError):
    """Raised when parallel writes conflict without a reducer."""


# --- Agent Errors ---


class AgentError(OrchestraError):
    """Base for agent-related errors."""


class AgentTimeoutError(AgentError):
    """Raised when an agent exceeds its time limit."""


class OutputValidationError(AgentError):
    """Raised when agent output fails structured output validation."""


class MaxIterationsError(AgentError):
    """Raised when an agent exceeds max tool-calling iterations.

    Attributes:
        partial_output: The AgentResult captured at the point the limit was
            hit.  It is always populated so callers can inspect whatever work
            was completed before the limit was reached.
    """

    def __init__(self, message: str, partial_output: Any = None) -> None:
        super().__init__(message)
        self.partial_output = partial_output


# --- Provider Errors ---


class ProviderError(OrchestraError):
    """Base for LLM provider errors."""


class RateLimitError(ProviderError):
    """Raised when rate limited by the provider."""

    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class AuthenticationError(ProviderError):
    """Raised when API key is invalid or missing."""


class ContextWindowError(ProviderError):
    """Raised when input exceeds the model's context window."""

    def __init__(self, message: str, context_length: int = 0, max_context_length: int = 0) -> None:
        super().__init__(message)
        self.context_length = context_length
        self.max_context_length = max_context_length


class ProviderUnavailableError(ProviderError):
    """Raised when the provider endpoint is unreachable."""


# --- Tool Errors ---


class ToolError(OrchestraError):
    """Base for tool-related errors."""


class ToolNotFoundError(ToolError):
    """Raised when a requested tool is not registered."""


class ToolTimeoutError(ToolError):
    """Raised when a tool execution exceeds its time limit."""


class ToolPermissionError(ToolError):
    """Raised when an agent lacks permission to use a tool."""


class ToolExecutionError(ToolError):
    """Raised when a tool execution fails."""


# --- State Errors ---


class StateError(OrchestraError):
    """Base for state-related errors."""


class ReducerError(StateError):
    """Raised when a reducer function fails."""


class StateValidationError(StateError):
    """Raised when state fails Pydantic validation."""


# --- Persistence Errors ---


class PersistenceError(OrchestraError):
    """Base for storage/persistence errors."""


class EventStoreError(PersistenceError):
    """Raised when event store operations fail."""


class CheckpointError(PersistenceError):
    """Raised when checkpoint operations fail."""


class ContractValidationError(PersistenceError):
    """Raised when agent output fails boundary contract validation."""


# --- MCP Errors ---


class MCPError(OrchestraError):
    """Base for MCP-related errors."""


class MCPConnectionError(MCPError):
    """Raised when MCP server connection fails."""


class MCPToolError(MCPError):
    """Raised when MCP tool execution fails."""


class MCPTimeoutError(MCPError):
    """Raised when MCP server times out."""


# --- Budget Errors ---


class BudgetExceededError(OrchestraError):
    """Raised when a hard budget limit is exceeded before an LLM call."""


# --- Routing Errors ---


class RoutingError(OrchestraError):
    """Base for routing/model-selection errors."""


class ModelSelectionError(RoutingError):
    """No model satisfies both SLA and budget constraints."""

    def __init__(self, message: str, sla: Any = None, budget: Any = None) -> None:
        super().__init__(message)
        self.sla = sla
        self.budget = budget


class AllProvidersUnavailableError(RoutingError):
    """All providers in failover chain failed or are circuit-broken."""


# --- Identity Errors ---


class IdentityError(OrchestraError):
    """Base for agent identity errors."""


class InvalidSignatureError(IdentityError):
    """Agent Card or message signature verification failed."""


class DelegationDepthExceededError(IdentityError):
    """Delegation chain exceeds max_depth."""


class AgentRevokedException(IdentityError):
    """Raised when an agent's DID appears in the active revocation list.

    This is checked BEFORE signature verification and BEFORE UCAN/ACL checks
    so that a compromised agent is blocked at the earliest possible point.

    Attributes:
        did: The revoked DID that triggered the exception.
    """

    def __init__(self, did: str) -> None:
        self.did = did
        super().__init__(
            f"Agent DID '{did}' has been revoked and is no longer authorized. "
            "Re-provision a new identity to regain access."
        )


# --- Authorization Errors ---


class AuthorizationError(OrchestraError):
    """Base for capability/authorization errors."""


class UCANVerificationError(AuthorizationError):
    """UCAN token is expired, has invalid audience, or bad signature."""


class CapabilityDeniedError(AuthorizationError):
    """UCAN does not grant the required capability."""
