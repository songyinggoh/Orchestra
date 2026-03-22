"""Orchestra agents for session hallucination detection.

Two agents:

SelfCheckAgent
  A drop-in BaseAgent subclass. After every run() it samples its own output
  N more times and scores consistency via SelfCheckGPT. Annotates the result
  with hallucination metadata and can retry on high risk.

  Usage:
      agent = SelfCheckAgent(
          name="researcher",
          model="gpt-4o-mini",
          system_prompt="You are a research analyst.",
          selfcheck_method=SelfCheckMethod.NLI,
          selfcheck_samples=3,
          retry_on_high_risk=True,
      )

SessionAuditorAgent
  A standalone auditor node. Receives a response + the messages that produced
  it, runs SelfCheckGPT, and returns a plain-text audit report. Wire it as
  a post-processing node in a WorkflowGraph.

  Usage:
      # In a workflow graph:
      graph.add_node("audit", auditor_agent)
      graph.add_edge("researcher", "audit")

make_selfcheck_node()
  Factory returning a plain async node function compatible with @node / graph.
  Use when you want hallucination checking without subclassing.

  Usage:
      selfcheck = make_selfcheck_node(method=SelfCheckMethod.NLI, num_samples=3)
      graph.add_node("selfcheck", selfcheck)
      graph.add_edge("researcher", "selfcheck")
"""

from __future__ import annotations

from typing import Any

import structlog
from pydantic import BaseModel, Field

from orchestra.core.agent import BaseAgent
from orchestra.core.context import ExecutionContext
from orchestra.core.types import AgentResult, Message, MessageRole
from orchestra.reliability.selfcheck import SelfChecker, SelfCheckMethod, SelfCheckResult

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Structured audit report (output_type for SessionAuditorAgent)
# ---------------------------------------------------------------------------


class AuditReport(BaseModel):
    """Structured hallucination audit report for a single agent response."""

    agent_name: str = ""
    response: str = ""
    consistency_score: float = 1.0
    hallucination_risk: str = "low"
    num_sentences: int = 0
    num_flagged: int = 0
    flagged_sentences: list[str] = Field(default_factory=list)
    method: str = ""
    num_samples: int = 0
    sample_tokens_used: int = 0

    def to_text(self) -> str:
        lines = [
            f"=== Hallucination Audit: {self.agent_name} ===",
            f"Risk Level        : {self.hallucination_risk.upper()}",
            f"Consistency Score : {self.consistency_score:.2%}",
            f"Method            : {self.method}",
            f"Samples Used      : {self.num_samples}",
            f"Sentences Checked : {self.num_sentences}",
            f"Flagged (>0.5)    : {self.num_flagged}",
        ]
        if self.flagged_sentences:
            lines.append("\nFlagged sentences:")
            for s in self.flagged_sentences:
                lines.append(f"  • {s}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# SelfCheckAgent — BaseAgent subclass with built-in self-checking
# ---------------------------------------------------------------------------


class SelfCheckAgent(BaseAgent):
    """A BaseAgent that checks its own output for hallucinations after every run.

    Internally it:
      1. Calls the LLM normally (via super().run()).
      2. Samples the same prompt N more times at high temperature.
      3. Scores sentence-level consistency via SelfCheckGPT.
      4. Annotates AgentResult.state_updates with the SelfCheckResult.
      5. Optionally retries once if hallucination_risk is "high".

    The selfcheck metadata is stored in state_updates["selfcheck"] as a dict
    and is accessible to downstream nodes via the workflow state.
    """

    selfcheck_method: SelfCheckMethod = SelfCheckMethod.NLI
    selfcheck_samples: int = 3
    selfcheck_temperature: float = 1.0
    selfcheck_device: str = "cpu"
    retry_on_high_risk: bool = False  # retry once if risk is "high"

    model_config = {"arbitrary_types_allowed": True}

    async def run(
        self,
        input: str | list[Message],
        context: ExecutionContext,
    ) -> AgentResult:
        checker = SelfChecker(
            method=self.selfcheck_method,
            num_samples=self.selfcheck_samples,
            sample_temperature=self.selfcheck_temperature,
            device=self.selfcheck_device,
        )

        # Build the message list for re-sampling before the primary call
        messages_for_sampling = self._build_sampling_messages(input)

        # Primary agent run
        result = await super().run(input, context)

        # Score the primary output
        sc_result = await checker.check(
            response=result.output,
            messages=messages_for_sampling,
            provider=context.provider,
            model=self.model,
        )

        logger.info(
            "selfcheck_agent_scored",
            agent=self.name,
            risk=sc_result.hallucination_risk,
            consistency=round(sc_result.consistency_score, 3),
        )

        # Optionally retry once on high risk
        if sc_result.hallucination_risk == "high" and self.retry_on_high_risk:
            logger.info("selfcheck_retrying_due_to_high_risk", agent=self.name)
            retry_result = await super().run(input, context)
            retry_sc = await checker.check(
                response=retry_result.output,
                messages=messages_for_sampling,
                provider=context.provider,
                model=self.model,
            )
            # Keep whichever response scored better
            if retry_sc.consistency_score > sc_result.consistency_score:
                result = retry_result
                sc_result = retry_sc
                logger.info(
                    "selfcheck_kept_retry",
                    agent=self.name,
                    new_consistency=round(sc_result.consistency_score, 3),
                )

        # Annotate state_updates with selfcheck metadata
        updated_state = dict(result.state_updates)
        updated_state["selfcheck"] = {
            "consistency_score": sc_result.consistency_score,
            "hallucination_risk": sc_result.hallucination_risk,
            "method": sc_result.method,
            "num_samples": sc_result.num_samples,
            "num_sentences": len(sc_result.sentences),
            "flagged": [s.sentence for s in sc_result.sentences if s.score > 0.5],
            "sentence_scores": [
                {"sentence": s.sentence, "score": round(s.score, 4)} for s in sc_result.sentences
            ],
        }

        return AgentResult(
            agent_name=result.agent_name,
            output=result.output,
            structured_output=result.structured_output,
            messages=result.messages,
            tool_calls_made=result.tool_calls_made,
            handoff_to=result.handoff_to,
            state_updates=updated_state,
            token_usage=result.token_usage,
        )

    def _build_sampling_messages(self, input: str | list[Message]) -> list[Message]:
        """Build messages list for re-sampling (system + user only)."""
        msgs = [Message(role=MessageRole.SYSTEM, content=self.system_prompt)]
        if isinstance(input, str):
            if input:
                msgs.append(Message(role=MessageRole.USER, content=input))
        else:
            msgs.extend(input)
        return msgs


# ---------------------------------------------------------------------------
# SessionAuditorAgent — standalone auditor node
# ---------------------------------------------------------------------------

_AUDITOR_SYSTEM = """\
You are a hallucination auditor. You will be given the output of another AI agent.
Your job is to assess factual consistency by analyzing the selfcheck scores provided
and summarise what was found. Be concise and factual. Do not add new claims."""


class SessionAuditorAgent(BaseAgent):
    """Standalone auditor agent that checks any response for hallucinations.

    Designed to be wired as a post-processing node after another agent.
    Reads `state["output"]` and `state["messages"]` from the workflow state,
    runs SelfCheckGPT, and writes an AuditReport to `state["audit"]`.

    The agent's own run() output is a plain-text audit summary (the LLM
    formats the SelfCheckResult into natural language).

    Configuration:
        selfcheck_method:   Which SelfCheckGPT variant to use.
        selfcheck_samples:  Number of samples to draw for consistency checking.
        audited_agent_key:  State key holding the response to audit (default "output").
        messages_key:       State key holding the messages used to generate it (default "messages").
    """

    name: str = "session_auditor"
    model: str = "gpt-4o-mini"
    system_prompt: str = _AUDITOR_SYSTEM
    selfcheck_method: SelfCheckMethod = SelfCheckMethod.NLI
    selfcheck_samples: int = 3
    selfcheck_temperature: float = 1.0
    selfcheck_device: str = "cpu"
    audited_agent_key: str = "output"  # state key → response to audit
    messages_key: str = "messages"  # state key → original messages

    model_config = {"arbitrary_types_allowed": True}

    async def run(
        self,
        input: str | list[Message],
        context: ExecutionContext,
    ) -> AgentResult:
        # Pull the response to audit from workflow state
        response_to_audit: str = context.state.get(self.audited_agent_key, "")
        original_messages: list[Message] = context.state.get(self.messages_key, [])

        if not response_to_audit:
            return AgentResult(
                agent_name=self.name,
                output="No response found in state to audit.",
                state_updates={"audit": None},
            )

        # If state has no messages, fall back to the agent's own input
        if not original_messages:
            if isinstance(input, list):
                original_messages = input
            elif isinstance(input, str) and input:
                original_messages = [Message(role=MessageRole.USER, content=input)]

        checker = SelfChecker(
            method=self.selfcheck_method,
            num_samples=self.selfcheck_samples,
            sample_temperature=self.selfcheck_temperature,
            device=self.selfcheck_device,
        )

        sc_result: SelfCheckResult = await checker.check(
            response=response_to_audit,
            messages=original_messages,
            provider=context.provider,
            model=self.model,
        )

        # Build the structured AuditReport
        flagged = [s.sentence for s in sc_result.sentences if s.score > 0.5]
        report = AuditReport(
            agent_name=context.state.get("agent_name", "unknown"),
            response=response_to_audit,
            consistency_score=sc_result.consistency_score,
            hallucination_risk=sc_result.hallucination_risk,
            num_sentences=len(sc_result.sentences),
            num_flagged=len(flagged),
            flagged_sentences=flagged,
            method=sc_result.method,
            num_samples=sc_result.num_samples,
            sample_tokens_used=sc_result.sample_token_usage.total_tokens,
        )

        logger.info(
            "session_auditor_complete",
            risk=report.hallucination_risk,
            consistency=round(report.consistency_score, 3),
            flagged=report.num_flagged,
        )

        # Ask the LLM to summarise the audit in natural language
        summary_prompt = (
            f"Here is a selfcheck hallucination audit result:\n\n"
            f"{report.to_text()}\n\n"
            "Write a concise 2–3 sentence summary of the findings for a human reviewer."
        )
        summary_result = await super().run(summary_prompt, context)

        return AgentResult(
            agent_name=self.name,
            output=summary_result.output,
            state_updates={"audit": report.model_dump()},
            token_usage=summary_result.token_usage,
        )


# ---------------------------------------------------------------------------
# make_selfcheck_node — graph node factory (no subclassing required)
# ---------------------------------------------------------------------------


def make_selfcheck_node(
    method: SelfCheckMethod = SelfCheckMethod.NLI,
    num_samples: int = 3,
    sample_temperature: float = 1.0,
    device: str = "cpu",
    response_key: str = "output",
    messages_key: str = "messages",
    result_key: str = "selfcheck",
) -> Any:
    """Return an async node function that runs SelfCheckGPT on workflow state.

    The node reads state[response_key] and state[messages_key], runs
    SelfCheckGPT, and writes the result dict to state[result_key].

    Usage:
        from orchestra.reliability.agents import make_selfcheck_node, SelfCheckMethod

        selfcheck = make_selfcheck_node(method=SelfCheckMethod.NLI, num_samples=3)
        graph.add_node("selfcheck", selfcheck)
        graph.add_edge("researcher", "selfcheck")

    The result stored in state[result_key] contains:
        consistency_score, hallucination_risk, method, num_samples,
        num_sentences, flagged (list of sentences), sentence_scores
    """
    checker = SelfChecker(
        method=method,
        num_samples=num_samples,
        sample_temperature=sample_temperature,
        device=device,
    )

    async def selfcheck_node(state: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        response: str = state.get(response_key, "")
        messages: list[Message] = state.get(messages_key, [])

        if not response:
            logger.warning("selfcheck_node_empty_response", response_key=response_key)
            return state

        sc_result = await checker.check(
            response=response,
            messages=messages,
            provider=context.provider,
        )

        return {
            **state,
            result_key: {
                "consistency_score": sc_result.consistency_score,
                "hallucination_risk": sc_result.hallucination_risk,
                "method": sc_result.method,
                "num_samples": sc_result.num_samples,
                "num_sentences": len(sc_result.sentences),
                "flagged": [s.sentence for s in sc_result.sentences if s.score > 0.5],
                "sentence_scores": [
                    {"sentence": s.sentence, "score": round(s.score, 4)}
                    for s in sc_result.sentences
                ],
            },
        }

    selfcheck_node.__name__ = f"selfcheck_{method.value}_node"
    return selfcheck_node
