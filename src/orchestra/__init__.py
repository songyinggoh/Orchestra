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
from orchestra.tools.base import tool

__all__ = [
    "AuditReport",
    "BaseAgent",
    "DecoratedAgent",
    "END",
    "ExecutionContext",
    "FactScoreChecker",
    "FactScorerAgent",
    "FactScoreResult",
    "InjectionAuditorAgent",
    "InjectionDetectionResult",
    "InjectionReport",
    "Message",
    "MessageRole",
    "OrchestraError",
    "PromptInjectionAgent",
    "RunResult",
    "START",
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
    "make_injection_guard_node",
    "make_selfcheck_node",
    "rebuff_tool",
    "run",
    "run_sync",
    "selfcheck_tool",
    "tool",
]
