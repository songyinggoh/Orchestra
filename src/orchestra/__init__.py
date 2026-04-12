"""Orchestra: Python-first multi-agent orchestration framework."""

__version__ = "0.1.0"

from orchestra.core.agent import BaseAgent, DecoratedAgent, agent
from orchestra.core.context import ExecutionContext
from orchestra.core.errors import OrchestraError
from orchestra.core.graph import WorkflowGraph
from orchestra.core.runner import RunResult, run, run_sync
from orchestra.core.state import WorkflowState
from orchestra.core.types import END, START, Message, MessageRole

# Reasoning — structured multi-step reasoning strategies
from orchestra.reasoning import ThoughtNode, ToTSearchStrategy, TreeOfThoughtsAgent

# Reliability — hallucination detection (SelfCheckGPT + FActScore)
from orchestra.reliability import (
    AuditReport,
    FactScoreChecker,
    FactScorerAgent,
    FactScoreResult,
    SelfCheckAgent,
    SelfChecker,
    SelfCheckMethod,
    SelfCheckResult,
    SentenceScore,
    SessionAuditorAgent,
    factscore_tool,
    make_factscore_node,
    make_selfcheck_node,
    selfcheck_tool,
)

# Security — prompt injection detection (Rebuff, optional)
_REBUFF_NAMES: list[str] = []
try:
    from orchestra.security import (  # type: ignore[attr-defined]  # noqa: F401
        InjectionAuditorAgent,
        InjectionDetectionResult,
        InjectionReport,
        PromptInjectionAgent,
        RebuffChecker,
        make_injection_guard_node,
        rebuff_tool,
    )

    _REBUFF_NAMES = [
        "InjectionAuditorAgent",
        "InjectionDetectionResult",
        "InjectionReport",
        "PromptInjectionAgent",
        "RebuffChecker",
        "make_injection_guard_node",
        "rebuff_tool",
    ]
except (ImportError, AttributeError):
    pass

from orchestra.tools.base import tool  # noqa: E402

__all__ = [
    "END",
    "START",
    "AuditReport",
    "BaseAgent",
    "DecoratedAgent",
    "ExecutionContext",
    "FactScoreChecker",
    "FactScoreResult",
    "FactScorerAgent",
    "Message",
    "MessageRole",
    "OrchestraError",
    "RunResult",
    "SelfCheckAgent",
    "SelfCheckMethod",
    "SelfCheckResult",
    "SelfChecker",
    "SentenceScore",
    "SessionAuditorAgent",
    "ThoughtNode",
    "ToTSearchStrategy",
    "TreeOfThoughtsAgent",
    "WorkflowGraph",
    "WorkflowState",
    "agent",
    "factscore_tool",
    "make_factscore_node",
    "make_selfcheck_node",
    "run",
    "run_sync",
    "selfcheck_tool",
    "tool",
    *_REBUFF_NAMES,
]
