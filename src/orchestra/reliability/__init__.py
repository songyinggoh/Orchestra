"""Orchestra reliability module — hallucination detection.

SelfCheckGPT  (zero-resource, black-box, no knowledge source needed)
  SelfChecker           — core checker class
  SelfCheckMethod       — NLI | BERTSCORE | NGRAM | LLM
  SelfCheckResult       — result with per-sentence scores
  SelfCheckAgent        — BaseAgent subclass with built-in self-checking
  SessionAuditorAgent   — standalone post-processing auditor node
  make_selfcheck_node() — graph node factory

FActScore  (retrieval-augmented, requires knowledge source + OpenAI key)
  FactScoreChecker      — core checker class
  FactScoreResult       — result with factscore and risk level
  FactScorerAgent       — BaseAgent subclass with built-in FActScore checking
  make_factscore_node() — graph node factory
"""

from orchestra.reliability.agents import (
    AuditReport,
    SelfCheckAgent,
    SessionAuditorAgent,
    make_selfcheck_node,
)
from orchestra.reliability.factscore import FactScoreChecker, FactScoreResult
from orchestra.reliability.factscore_agents import FactScorerAgent, make_factscore_node
from orchestra.reliability.selfcheck import (
    SelfChecker,
    SelfCheckMethod,
    SelfCheckResult,
    SentenceScore,
)
from orchestra.reliability.tools import factscore_tool, selfcheck_tool

__all__ = [
    "AuditReport",
    "FactScoreChecker",
    "FactScoreResult",
    "FactScorerAgent",
    "SelfCheckAgent",
    "SelfCheckMethod",
    "SelfCheckResult",
    "SelfChecker",
    "SentenceScore",
    "SessionAuditorAgent",
    "factscore_tool",
    "make_factscore_node",
    "make_selfcheck_node",
    "selfcheck_tool",
]
