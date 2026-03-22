"""Orchestra agents for FActScore-based factual precision checking.

Two agents:

FactScorerAgent
  A BaseAgent subclass that checks its own output using FActScore after
  every run(). Requires a topic to be present in the state or input.
  Annotates AgentResult.state_updates["factscore"] with the result.

  Usage:
      agent = FactScorerAgent(
          name="biographer",
          model="gpt-4o-mini",
          system_prompt="Write a biography of the given person.",
          openai_key="sk-...",
          knowledge_source="enwiki-20230401",
      )

make_factscore_node()
  Factory returning a plain async node function compatible with graph.add_node.
  Reads state["output"] and state["topic"], writes state["factscore"].

  Usage:
      fsnode = make_factscore_node(openai_key="sk-...")
      graph.add_node("factscore", fsnode)
      graph.add_edge("biographer", "factscore")
"""

from __future__ import annotations

from typing import Any

import structlog

from orchestra.core.agent import BaseAgent
from orchestra.core.context import ExecutionContext
from orchestra.core.types import AgentResult, Message, MessageRole
from orchestra.reliability.factscore import FactScoreChecker, FactScoreResult

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# FactScorerAgent — BaseAgent subclass with built-in FActScore checking
# ---------------------------------------------------------------------------


class FactScorerAgent(BaseAgent):
    """A BaseAgent that validates its output with FActScore after every run().

    The agent reads the topic from:
      1. state["topic"]  (preferred — set by upstream node)
      2. The first user message content (fallback)

    FActScore result is stored in state_updates["factscore"].

    Note: FActScore makes API calls (OpenAI) and can take several seconds.
    Estimated cost: ~$0.01 per 100 sentences via ChatGPT.
    """

    openai_key: str = ""
    factscore_model: str = "retrieval+ChatGPT"
    knowledge_source: str = "enwiki-20230401"
    factscore_data_dir: str = ".cache/factscore"
    factscore_gamma: int = 10
    topic_state_key: str = "topic"  # state key to read the topic from

    model_config: dict = {"arbitrary_types_allowed": True}  # noqa: RUF012

    async def run(
        self,
        input: str | list[Message],
        context: ExecutionContext,
    ) -> AgentResult:
        # Primary agent run
        result = await super().run(input, context)

        # Resolve the topic
        topic = context.state.get(self.topic_state_key, "")
        if not topic:
            topic = self._extract_topic_from_input(input)

        if not topic:
            logger.warning(
                "factscore_agent_no_topic",
                agent=self.name,
                hint=f"Set state['{self.topic_state_key}'] before this agent runs.",
            )
            return result

        checker = FactScoreChecker(
            openai_key=self.openai_key,
            model_name=self.factscore_model,
            knowledge_source=self.knowledge_source,
            data_dir=self.factscore_data_dir,
            gamma=self.factscore_gamma,
        )

        fs_result: FactScoreResult = await checker.check(
            topic=topic,
            response=result.output,
        )

        logger.info(
            "factscore_agent_scored",
            agent=self.name,
            topic=topic,
            factscore=round(fs_result.factscore, 3),
            risk=fs_result.hallucination_risk,
        )

        updated_state = dict(result.state_updates)
        updated_state["factscore"] = {
            "factscore": fs_result.factscore,
            "init_score": fs_result.init_score,
            "hallucination_risk": fs_result.hallucination_risk,
            "num_facts": fs_result.num_facts,
            "respond_ratio": fs_result.respond_ratio,
            "knowledge_source": fs_result.knowledge_source,
            "topic": topic,
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

    def _extract_topic_from_input(self, input: str | list[Message]) -> str:
        """Best-effort topic extraction: use first user message content."""
        if isinstance(input, str):
            return input[:100]
        for msg in input:
            if msg.role == MessageRole.USER and msg.content:
                return msg.content[:100]
        return ""


# ---------------------------------------------------------------------------
# make_factscore_node — graph node factory
# ---------------------------------------------------------------------------


def make_factscore_node(
    openai_key: str = "",
    model_name: str = "retrieval+ChatGPT",
    knowledge_source: str = "enwiki-20230401",
    data_dir: str = ".cache/factscore",
    gamma: int = 10,
    response_key: str = "output",
    topic_key: str = "topic",
    result_key: str = "factscore",
) -> Any:
    """Return an async node function that runs FActScore on workflow state.

    The node reads:
      state[response_key]  — the text to evaluate (default "output")
      state[topic_key]     — the entity the response is about (default "topic")

    And writes:
      state[result_key]    — FActScore result dict (default "factscore")

    Usage:
        fsnode = make_factscore_node(openai_key="sk-...")
        graph.add_node("factscore", fsnode)
        graph.add_edge("biographer", "factscore")
        graph.add_conditional_edge(
            "factscore",
            lambda s: "done" if s["factscore"]["hallucination_risk"] == "low" else "retry",
        )
    """
    checker = FactScoreChecker(
        openai_key=openai_key,
        model_name=model_name,
        knowledge_source=knowledge_source,
        data_dir=data_dir,
        gamma=gamma,
    )

    async def factscore_node(state: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        response: str = state.get(response_key, "")
        topic: str = state.get(topic_key, "")

        if not response:
            logger.warning("factscore_node_empty_response", key=response_key)
            return state

        if not topic:
            logger.warning(
                "factscore_node_no_topic",
                hint=f"Set state['{topic_key}'] before this node runs.",
            )
            return state

        fs_result = await checker.check(topic=topic, response=response)

        logger.info(
            "factscore_node_complete",
            factscore=round(fs_result.factscore, 3),
            risk=fs_result.hallucination_risk,
        )

        return {
            **state,
            result_key: {
                "factscore": fs_result.factscore,
                "init_score": fs_result.init_score,
                "hallucination_risk": fs_result.hallucination_risk,
                "num_facts": fs_result.num_facts,
                "respond_ratio": fs_result.respond_ratio,
                "knowledge_source": fs_result.knowledge_source,
                "topic": topic,
            },
        }

    factscore_node.__name__ = "factscore_node"
    return factscore_node
