"""Orchestra: Python-first multi-agent orchestration framework."""

__version__ = "0.1.0"

from orchestra.core.agent import BaseAgent, DecoratedAgent, agent
from orchestra.core.context import ExecutionContext
from orchestra.core.errors import OrchestraError
from orchestra.core.graph import WorkflowGraph
from orchestra.core.runner import RunResult, run, run_sync
from orchestra.core.state import WorkflowState
from orchestra.core.types import END, START, Message, MessageRole
from orchestra.tools.base import tool

# Security — prompt injection detection (Rebuff)
from orchestra.security import (
    InjectionAuditorAgent,
    InjectionDetectionResult,
    InjectionReport,
    PromptInjectionAgent,
    RebuffChecker,
    make_injection_guard_node,
    rebuff_tool,
)

# Reasoning — structured multi-step reasoning strategies
from orchestra.reasoning import ThoughtNode, ToTSearchStrategy, TreeOfThoughtsAgent

# Reliability — hallucination detection (SelfCheckGPT + FActScore)
from orchestra.reliability import (
    AuditReport,
    FactScoreChecker,
    FactScoreResult,
    FactScorerAgent,
    SelfCheckAgent,
    SelfCheckMethod,
    SelfCheckResult,
    SelfChecker,
    SentenceScore,
    SessionAuditorAgent,
    factscore_tool,
    make_factscore_node,
    make_selfcheck_node,
    selfcheck_tool,
)

__all__ = [
    # Core
    "END",
    "START",
    "BaseAgent",
    "DecoratedAgent",
    "ExecutionContext",
    "Message",
    "MessageRole",
    "OrchestraError",
    "RunResult",
    "WorkflowGraph",
    "WorkflowState",
    "agent",
    "run",
    "run_sync",
    "tool",
    # Reasoning — Tree of Thoughts
    "TreeOfThoughtsAgent",
    "ToTSearchStrategy",
    "ThoughtNode",
    # Security — Rebuff prompt injection detection
    "RebuffChecker",
    "InjectionDetectionResult",
    "InjectionReport",
    "PromptInjectionAgent",
    "InjectionAuditorAgent",
    "make_injection_guard_node",
    "rebuff_tool",
    # Reliability — SelfCheckGPT
    "SelfChecker",
    "SelfCheckMethod",
    "SelfCheckResult",
    "SentenceScore",
    "SelfCheckAgent",
    "SessionAuditorAgent",
    "AuditReport",
    "make_selfcheck_node",
    "selfcheck_tool",
    # Reliability — FActScore
    "FactScoreChecker",
    "FactScoreResult",
    "FactScorerAgent",
    "make_factscore_node",
    "factscore_tool",
]
