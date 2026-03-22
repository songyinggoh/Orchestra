"""SelfCheckGPT and FActScore as callable Tools.

Any agent can attach these to its tools list and invoke them during its
reasoning loop — no graph wiring or subclassing required.

Usage:
    from orchestra.reliability.tools import selfcheck_tool, factscore_tool
    from orchestra.core.agent import BaseAgent

    agent = BaseAgent(
        name="researcher",
        model="gpt-4o-mini",
        system_prompt="You are a research analyst. Before returning your answer, "
                      "verify it with the selfcheck_tool.",
        tools=[selfcheck_tool()],
    )

    # For FActScore (needs OpenAI key + knowledge source):
    agent = BaseAgent(
        name="biographer",
        tools=[factscore_tool(openai_key="sk-...")],
    )
"""

from __future__ import annotations

from orchestra.core.context import ExecutionContext
from orchestra.reliability.factscore import FactScoreChecker
from orchestra.reliability.selfcheck import SelfChecker, SelfCheckMethod
from orchestra.tools.base import ToolWrapper


def selfcheck_tool(
    method: SelfCheckMethod = SelfCheckMethod.NLI,
    num_samples: int = 3,
    sample_temperature: float = 1.0,
    device: str = "cpu",
) -> ToolWrapper:
    """Return a Tool that checks a response for hallucinations via SelfCheckGPT.

    The agent calls this tool with:
        response  — the text to verify
        prompt    — the original prompt that produced it

    The tool returns a plain-text report the agent can reason over.

    Args:
        method:             SelfCheckGPT scoring method (NLI, BERTSCORE, NGRAM, LLM).
        num_samples:        Number of re-samples to draw.
        sample_temperature: Temperature for re-sampling (default 1.0 for diversity).
        device:             "cpu" or "cuda" for NLI/BERTScore model inference.
    """
    checker = SelfChecker(
        method=method,
        num_samples=num_samples,
        sample_temperature=sample_temperature,
        device=device,
    )

    async def _selfcheck(
        response: str,
        prompt: str,
        context: ExecutionContext,
    ) -> str:
        """Check a response for hallucinations using SelfCheckGPT.

        Call this tool before returning any factual response to verify it is
        consistent across multiple samples. If hallucination_risk is 'high',
        revise your answer.

        Args:
            response: The text you want to verify.
            prompt:   The original user prompt that produced this response.
        """
        from orchestra.core.types import Message, MessageRole

        messages = [Message(role=MessageRole.USER, content=prompt)]
        result = await checker.check(
            response=response,
            messages=messages,
            provider=context.provider,
        )
        return result.summary()

    return ToolWrapper(
        _selfcheck,
        name="selfcheck",
        description=(
            "Check a response for hallucinations using SelfCheckGPT. "
            "Provide the response text and the original prompt. "
            "Returns a risk level (low/medium/high) and flagged sentences."
        ),
    )


def factscore_tool(
    openai_key: str = "",
    model_name: str = "retrieval+ChatGPT",
    knowledge_source: str = "enwiki-20230401",
    data_dir: str = ".cache/factscore",
    gamma: int = 10,
) -> ToolWrapper:
    """Return a Tool that scores factual precision via FActScore.

    The agent calls this tool with:
        topic     — the entity the response is about (e.g. "Marie Curie")
        response  — the generated text to evaluate

    The tool returns a plain-text report with the FActScore and risk level.

    Requires:
        pip install factscore
        python -m spacy download en_core_web_sm
        python -m factscore.download_data  (downloads Wikipedia knowledge source)

    Args:
        openai_key:       OpenAI API key for the retrieval+ChatGPT pipeline.
        model_name:       FActScore pipeline ("retrieval+ChatGPT" or "retrieval+llama+npm").
        knowledge_source: Knowledge base name (default: "enwiki-20230401").
        data_dir:         Path to FActScore cache directory.
        gamma:            Length penalty (default: 10, set 0 to disable).
    """
    checker = FactScoreChecker(
        openai_key=openai_key,
        model_name=model_name,
        knowledge_source=knowledge_source,
        data_dir=data_dir,
        gamma=gamma,
    )

    async def _factscore(
        topic: str,
        response: str,
    ) -> str:
        """Score the factual precision of a response using FActScore.

        Use this tool when writing factual content about a named entity (person,
        place, organization). Provide the topic name and your generated response.
        If hallucination_risk is 'high', revise your answer.

        Args:
            topic:    The entity the response is about (e.g. "Albert Einstein").
            response: The generated text to evaluate for factual accuracy.
        """
        result = await checker.check(topic=topic, response=response)
        return result.summary()

    return ToolWrapper(
        _factscore,
        name="factscore",
        description=(
            "Score the factual precision of a response using FActScore. "
            "Provide the topic (named entity) and the generated response. "
            "Returns a FActScore (0-1) and hallucination risk level."
        ),
    )
