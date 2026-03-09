"""Orchestra security module — prompt injection detection.

Rebuff (https://github.com/protectai/rebuff) integration:
  RebuffChecker           — async wrapper around RebuffSdk
  InjectionDetectionResult — per-check result with layer scores
  InjectionReport          — full audit report (includes canary findings)
  PromptInjectionAgent     — BaseAgent subclass with built-in injection blocking
  InjectionAuditorAgent    — standalone pre-processing auditor node
  make_injection_guard_node() — graph node factory
  rebuff_tool()            — Tool for inline injection checking in agent loops

Requires:
    pip install rebuff

Environment variables (alternative to passing keys):
    REBUFF_OPENAI_KEY
    REBUFF_PINECONE_KEY
    REBUFF_PINECONE_INDEX
    REBUFF_OPENAI_MODEL  (optional)
"""

from orchestra.security.rebuff import (
    InjectionAuditorAgent,
    InjectionDetectionResult,
    InjectionReport,
    PromptInjectionAgent,
    RebuffChecker,
    make_injection_guard_node,
    rebuff_tool,
)

__all__ = [
    "RebuffChecker",
    "InjectionDetectionResult",
    "InjectionReport",
    "PromptInjectionAgent",
    "InjectionAuditorAgent",
    "make_injection_guard_node",
    "rebuff_tool",
]
