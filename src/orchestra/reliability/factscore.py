"""FActScore integration for Orchestra.

FActScore evaluates factual precision in long-form text by decomposing it into
atomic facts and verifying each against a knowledge source.
Reference: https://github.com/shmsw25/FActScore

Unlike SelfCheckGPT (which is self-contained), FActScore requires:
  1. A knowledge source (Wikipedia dump or custom JSONL)
  2. An OpenAI API key OR a local retrieval+LLM pipeline
  3. pip install factscore && python -m spacy download en_core_web_sm

Scoring convention:
  FActScore = fraction of atomic facts supported by the knowledge source.
  Range: 0.0 (all facts unsupported) to 1.0 (all facts supported).

Usage:
    checker = FactScoreChecker(openai_key="sk-...", knowledge_source="enwiki-20230401")
    result = await checker.check(
        topic="Paris",
        response="Paris is the capital of France and has a population of 2 million.",
    )
    print(result.factscore)         # e.g. 0.85
    print(result.hallucination_risk) # "low" | "medium" | "high"
    print(result.num_facts)          # number of atomic facts found
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


class FactScoreResult(BaseModel):
    """Result of a FActScore evaluation."""

    topic: str
    response: str
    factscore: float             # 0.0–1.0, fraction of supported atomic facts
    init_score: float            # FActScore without length penalty
    hallucination_risk: str      # "low" | "medium" | "high"
    num_facts: float             # average atomic facts per response
    respond_ratio: float         # fraction of responses that were not abstentions
    knowledge_source: str = ""

    model_config = {"arbitrary_types_allowed": True}

    def summary(self) -> str:
        lines = [
            f"FActScore          : {self.factscore:.2%}",
            f"Init Score         : {self.init_score:.2%}",
            f"Hallucination Risk : {self.hallucination_risk.upper()}",
            f"Avg Atomic Facts   : {self.num_facts:.1f}",
            f"Respond Ratio      : {self.respond_ratio:.2%}",
            f"Knowledge Source   : {self.knowledge_source}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# FactScoreChecker
# ---------------------------------------------------------------------------


class FactScoreChecker:
    """FActScore-based factual precision checker.

    Wraps the FActScore Python API:
        fs = FactScorer(openai_key="...")
        out = fs.get_score(topics, generations, gamma=10)

    Parameters:
        openai_key:        OpenAI API key (required for retrieval+ChatGPT pipeline).
        model_name:        FActScore model pipeline.
                           "retrieval+ChatGPT" — best accuracy, uses OpenAI.
                           "retrieval+llama+npm" — local, requires Inst-LLAMA weights.
        knowledge_source:  Name of the registered knowledge source.
                           Default: "enwiki-20230401" (Wikipedia, must be downloaded).
        data_dir:          Path to FActScore data cache (default: .cache/factscore).
        gamma:             Length penalty hyperparameter (default: 10, set 0 to disable).
        low_risk_threshold:   factscore >= this → "low" risk (default: 0.7).
        high_risk_threshold:  factscore <  this → "high" risk (default: 0.3).
    """

    _fs_instance: Any = None  # cached FactScorer (heavy to init)

    def __init__(
        self,
        openai_key: str = "",
        model_name: str = "retrieval+ChatGPT",
        knowledge_source: str = "enwiki-20230401",
        data_dir: str = ".cache/factscore",
        gamma: int = 10,
        low_risk_threshold: float = 0.7,
        high_risk_threshold: float = 0.3,
    ) -> None:
        self.openai_key = openai_key
        self.model_name = model_name
        self.knowledge_source = knowledge_source
        self.data_dir = data_dir
        self.gamma = gamma
        self.low_risk_threshold = low_risk_threshold
        self.high_risk_threshold = high_risk_threshold

    def _get_scorer(self) -> Any:
        """Lazily load and cache the FactScorer instance."""
        if FactScoreChecker._fs_instance is None:
            try:
                from factscore.factscorer import FactScorer
            except ImportError as e:
                raise ImportError(
                    "factscore is not installed.\n"
                    "  Fix: pip install factscore && python -m spacy download en_core_web_sm\n"
                    "  Then download data: "
                    "python -m factscore.download_data --llama_7B_HF_path <path>"
                ) from e

            logger.info(
                "factscore_loading_scorer",
                model=self.model_name,
                knowledge_source=self.knowledge_source,
            )
            kwargs: dict[str, Any] = {
                "data_dir": self.data_dir,
            }
            if self.openai_key:
                kwargs["openai_key"] = self.openai_key

            FactScoreChecker._fs_instance = FactScorer(**kwargs)

        return FactScoreChecker._fs_instance

    async def check(
        self,
        topic: str,
        response: str,
        *,
        knowledge_source: str | None = None,
    ) -> FactScoreResult:
        """Check a single response for factual precision.

        Args:
            topic:            The entity/subject the response is about (e.g. "Paris").
            response:         The generated text to evaluate.
            knowledge_source: Override the default knowledge source for this call.

        Returns:
            FactScoreResult with factscore and hallucination risk.
        """
        return (
            await self.check_batch(
                topics=[topic],
                responses=[response],
                knowledge_source=knowledge_source,
            )
        )[0]

    async def check_batch(
        self,
        topics: list[str],
        responses: list[str],
        *,
        knowledge_source: str | None = None,
    ) -> list[FactScoreResult]:
        """Check multiple responses in one FActScore call (more efficient).

        Args:
            topics:           List of entity names (one per response).
            responses:        List of generated texts to evaluate.
            knowledge_source: Override the default knowledge source.

        Returns:
            List of FactScoreResult, one per (topic, response) pair.
        """
        if len(topics) != len(responses):
            raise ValueError(
                f"topics and responses must have the same length, "
                f"got {len(topics)} topics and {len(responses)} responses."
            )

        ks = knowledge_source or self.knowledge_source
        loop = asyncio.get_event_loop()

        def _run_sync() -> dict[str, Any]:
            fs = self._get_scorer()
            out: dict[str, Any] = fs.get_score(
                topics=topics,
                generations=responses,
                gamma=self.gamma,
                knowledge_source=ks,
            )
            return out

        logger.info(
            "factscore_checking",
            num_responses=len(responses),
            model=self.model_name,
            knowledge_source=ks,
        )

        raw = await loop.run_in_executor(None, _run_sync)

        # FActScore returns aggregate metrics; per-item scores come via
        # raw["decisions"] when available, otherwise use aggregate for all.
        aggregate_score = float(raw.get("score", 0.0))
        init_score = float(raw.get("init_score", aggregate_score))
        respond_ratio = float(raw.get("respond_ratio", 1.0))
        num_facts = float(raw.get("num_facts_per_response", 0.0))

        # Per-item scores (if available in decisions)
        decisions = raw.get("decisions", [])

        results: list[FactScoreResult] = []
        for i, (topic, response) in enumerate(zip(topics, responses)):
            if decisions and i < len(decisions) and decisions[i] is not None:
                item_facts = decisions[i]
                supported = sum(1 for f in item_facts if f.get("is_supported", False))
                item_score = supported / len(item_facts) if item_facts else 1.0
            else:
                item_score = aggregate_score

            results.append(
                FactScoreResult(
                    topic=topic,
                    response=response,
                    factscore=item_score,
                    init_score=init_score,
                    hallucination_risk=self._risk_level(item_score),
                    num_facts=num_facts,
                    respond_ratio=respond_ratio,
                    knowledge_source=ks,
                )
            )

        logger.info(
            "factscore_complete",
            num_results=len(results),
            avg_score=round(aggregate_score, 3),
        )

        return results

    def register_knowledge_source(
        self,
        name: str,
        data_path: str,
        db_path: str,
    ) -> None:
        """Register a custom knowledge source for use with check().

        Args:
            name:       Identifier to use in knowledge_source= parameter.
            data_path:  Path to JSONL file with {"title": ..., "text": ...} records.
            db_path:    Path to SQLite database file (created if not exists).
        """
        fs = self._get_scorer()
        fs.register_knowledge_source(name, data_path=data_path, db_path=db_path)
        logger.info(
            "factscore_knowledge_source_registered",
            name=name,
            data_path=data_path,
        )

    def _risk_level(self, factscore: float) -> str:
        if factscore >= self.low_risk_threshold:
            return "low"
        elif factscore >= self.high_risk_threshold:
            return "medium"
        return "high"
