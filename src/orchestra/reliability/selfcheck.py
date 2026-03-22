"""SelfCheckGPT integration for Orchestra.

Implements hallucination detection via stochastic sampling and consistency scoring.
Reference: https://github.com/potsawee/selfcheckgpt

Methods (from best to fastest):
  LLM       — LLM-as-judge via orchestra provider (93.42 AUC-PR on WikiBio)
  NLI       — DeBERTa-v3-large fine-tuned on MultiNLI (92.50 AUC-PR, no API needed)
  BERTSCORE — Semantic similarity via BERTScore
  NGRAM     — Negative log-probability via n-gram overlap (fastest, no model)

Scoring convention (consistent with the paper):
  sentence score 0.0 = supported by samples  (consistent / not hallucinated)
  sentence score 1.0 = contradicted by samples (likely hallucinated)
  consistency_score  = 1.0 - mean(sentence_scores)  →  higher = more consistent
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Any

import structlog
from pydantic import BaseModel, Field

from orchestra.core.types import Message, MessageRole, TokenUsage

logger = structlog.get_logger(__name__)


class SelfCheckMethod(str, Enum):
    """Available SelfCheckGPT scoring methods."""

    NLI = "nli"  # DeBERTa-v3-large NLI — best offline method
    BERTSCORE = "bertscore"  # Semantic BERTScore similarity
    NGRAM = "ngram"  # N-gram negative log-probability (no model required)
    LLM = "llm"  # LLM-as-judge via orchestra provider — best overall


class SentenceScore(BaseModel):
    """Per-sentence hallucination score."""

    sentence: str
    score: float  # 0.0 = consistent/supported, 1.0 = likely hallucinated


class SelfCheckResult(BaseModel):
    """Full result of a SelfCheckGPT evaluation."""

    response: str
    sentences: list[SentenceScore] = Field(default_factory=list)
    consistency_score: float  # 0.0-1.0, higher = more consistent
    hallucination_risk: str  # "low" | "medium" | "high"
    num_samples: int
    method: str
    sample_token_usage: TokenUsage = Field(default_factory=TokenUsage)

    model_config = {"arbitrary_types_allowed": True}

    def summary(self) -> str:
        """Human-readable summary for logs and agent outputs."""
        risky = [s for s in self.sentences if s.score > 0.5]
        lines = [
            f"Hallucination Risk : {self.hallucination_risk.upper()}",
            f"Consistency Score  : {self.consistency_score:.2%}",
            f"Method             : {self.method}",
            f"Samples Used       : {self.num_samples}",
            f"Sentences Checked  : {len(self.sentences)}",
            f"High-risk Sentences: {len(risky)}",
        ]
        if risky:
            lines.append("\nFlagged sentences:")
            for s in risky:
                lines.append(f"  [{s.score:.2f}] {s.sentence}")
        return "\n".join(lines)


class SelfChecker:
    """SelfCheckGPT-based hallucination detector.

    Samples the same prompt N times at high temperature, then scores
    sentence-level consistency between the primary response and the samples.

    Usage:
        checker = SelfChecker(method=SelfCheckMethod.NLI, num_samples=3)
        result = await checker.check(
            response="The capital of France is Paris.",
            messages=messages,
            provider=provider,
        )
        print(result.hallucination_risk)   # "low" | "medium" | "high"
        print(result.consistency_score)    # 0.0 to 1.0
    """

    # Class-level model cache — loaded once, shared across all instances
    _nli_model: Any = None
    _bertscore_model: Any = None
    _ngram_model: Any = None

    def __init__(
        self,
        method: SelfCheckMethod = SelfCheckMethod.NLI,
        num_samples: int = 3,
        sample_temperature: float = 1.0,
        low_risk_threshold: float = 0.7,  # consistency_score >= this → "low"
        high_risk_threshold: float = 0.3,  # consistency_score <  this → "high"
        device: str = "cpu",
    ) -> None:
        self.method = method
        self.num_samples = num_samples
        self.sample_temperature = sample_temperature
        self.low_risk_threshold = low_risk_threshold
        self.high_risk_threshold = high_risk_threshold
        self.device = device

    async def check(
        self,
        response: str,
        messages: list[Message],
        *,
        provider: Any,
        model: str | None = None,
    ) -> SelfCheckResult:
        """Check a response for hallucinations.

        Args:
            response:  The LLM output text to evaluate.
            messages:  The conversation messages that produced the response.
                       Re-used to sample additional passages for comparison.
            provider:  Orchestra LLM provider (sampling + LLM-judge).
            model:     Model name override (defaults to provider's default).

        Returns:
            SelfCheckResult with per-sentence scores and overall risk level.
        """
        sentences = self._split_sentences(response)
        if not sentences:
            return self._empty_result(response)

        samples, token_usage = await self._sample_passages(messages, provider=provider, model=model)

        if not samples:
            logger.warning(
                "selfcheck_no_samples_collected",
                num_requested=self.num_samples,
            )
            return self._empty_result(response, token_usage=token_usage)

        scores = await self._score(sentences, samples, provider=provider, model=model)

        sentence_scores = [
            SentenceScore(sentence=s, score=sc)
            for s, sc in zip(sentences, scores, strict=False)
        ]
        consistency_score = 1.0 - (sum(scores) / len(scores))

        logger.info(
            "selfcheck_complete",
            method=self.method.value,
            num_sentences=len(sentences),
            num_samples=len(samples),
            consistency_score=round(consistency_score, 3),
            hallucination_risk=self._risk_level(consistency_score),
        )

        return SelfCheckResult(
            response=response,
            sentences=sentence_scores,
            consistency_score=consistency_score,
            hallucination_risk=self._risk_level(consistency_score),
            num_samples=len(samples),
            method=self.method.value,
            sample_token_usage=token_usage,
        )

    # -------------------------------------------------------------------------
    # Sampling
    # -------------------------------------------------------------------------

    async def _sample_passages(
        self,
        messages: list[Message],
        *,
        provider: Any,
        model: str | None,
    ) -> tuple[list[str], TokenUsage]:
        """Call the LLM num_samples times in parallel at high temperature."""
        total_usage = TokenUsage()

        tasks = [
            provider.complete(
                messages=messages,
                model=model,
                temperature=self.sample_temperature,
            )
            for _ in range(self.num_samples)
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        passages: list[str] = []
        for r in responses:
            if isinstance(r, Exception):
                logger.warning("selfcheck_sample_error", error=str(r))
                continue
            if r.content:
                passages.append(r.content)
            if r.usage:
                total_usage.input_tokens += r.usage.input_tokens
                total_usage.output_tokens += r.usage.output_tokens
                total_usage.total_tokens += r.usage.total_tokens
                total_usage.estimated_cost_usd += r.usage.estimated_cost_usd

        return passages, total_usage

    # -------------------------------------------------------------------------
    # Scoring dispatch
    # -------------------------------------------------------------------------

    async def _score(
        self,
        sentences: list[str],
        samples: list[str],
        *,
        provider: Any,
        model: str | None,
    ) -> list[float]:
        loop = asyncio.get_event_loop()

        if self.method == SelfCheckMethod.NLI:
            return await loop.run_in_executor(None, self._score_nli, sentences, samples)
        elif self.method == SelfCheckMethod.BERTSCORE:
            return await loop.run_in_executor(None, self._score_bertscore, sentences, samples)
        elif self.method == SelfCheckMethod.NGRAM:
            return await loop.run_in_executor(None, self._score_ngram, sentences, samples)
        elif self.method == SelfCheckMethod.LLM:
            return await self._score_llm(sentences, samples, provider=provider, model=model)
        else:
            raise ValueError(f"Unknown SelfCheckMethod: {self.method}")

    def _score_nli(self, sentences: list[str], samples: list[str]) -> list[float]:
        """DeBERTa-v3-large NLI scorer. Loaded once and cached."""
        if SelfChecker._nli_model is None:
            from selfcheckgpt.modeling_selfcheck import SelfCheckNLI

            logger.info("selfcheck_loading_model", model="NLI/DeBERTa-v3-large")
            SelfChecker._nli_model = SelfCheckNLI(device=self.device)

        result = SelfChecker._nli_model.predict(
            sentences=sentences,
            sampled_passages=samples,
        )
        return [float(s) for s in result]

    def _score_bertscore(self, sentences: list[str], samples: list[str]) -> list[float]:
        """BERTScore semantic similarity scorer. Loaded once and cached."""
        if SelfChecker._bertscore_model is None:
            from selfcheckgpt.modeling_selfcheck import SelfCheckBERTScore

            logger.info("selfcheck_loading_model", model="BERTScore")
            SelfChecker._bertscore_model = SelfCheckBERTScore(rescale_with_baseline=True)

        result = SelfChecker._bertscore_model.predict(
            sentences=sentences,
            sampled_passages=samples,
        )
        return [float(s) for s in result]

    def _score_ngram(self, sentences: list[str], samples: list[str]) -> list[float]:
        """N-gram negative log-probability scorer. No model required."""
        if SelfChecker._ngram_model is None:
            from selfcheckgpt.modeling_selfcheck import SelfCheckNgram

            logger.info("selfcheck_loading_model", model="Ngram")
            SelfChecker._ngram_model = SelfCheckNgram()

        passage = " ".join(sentences)
        result = SelfChecker._ngram_model.predict(
            sentences=sentences,
            passage=passage,
            sampled_passages=samples,
        )
        return [float(s) for s in result]

    async def _score_llm(
        self,
        sentences: list[str],
        samples: list[str],
        *,
        provider: Any,
        model: str | None,
    ) -> list[float]:
        """LLM-as-judge scorer.

        Uses the prompt template from the SelfCheckGPT paper:
          "Context: {context}

           Sentence: {sentence}

           Is the sentence supported by the context above? Answer Yes or No.

           Answer: "

        Scoring: Yes = 0.0 (supported), No = 1.0 (not supported), N/A = 0.5
        Average across all samples per sentence.
        """
        sentence_scores: list[float] = []

        for sentence in sentences:
            tasks = [
                provider.complete(
                    messages=[
                        Message(
                            role=MessageRole.USER,
                            content=(
                                f"Context: {sample}\n\n"
                                f"Sentence: {sentence}\n\n"
                                "Is the sentence supported by the context above? "
                                "Answer Yes or No.\n\nAnswer:"
                            ),
                        )
                    ],
                    model=model,
                    temperature=0.0,
                )
                for sample in samples
            ]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            votes: list[float] = []
            for r in responses:
                if isinstance(r, Exception):
                    continue
                text = (r.content or "").strip().lower()
                if text.startswith("yes"):
                    votes.append(0.0)  # supported → not hallucinated
                elif text.startswith("no"):
                    votes.append(1.0)  # not supported → hallucinated
                else:
                    votes.append(0.5)  # ambiguous / N/A

            sentence_scores.append(sum(votes) / len(votes) if votes else 0.5)

        return sentence_scores

    # -------------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------------

    def _split_sentences(self, text: str) -> list[str]:
        """Split text into sentences using NLTK punkt tokenizer."""
        import nltk

        try:
            nltk.data.find("tokenizers/punkt_tab")
        except LookupError:
            nltk.download("punkt_tab", quiet=True)

        from nltk.tokenize import sent_tokenize

        return [s.strip() for s in sent_tokenize(text) if s.strip()]

    def _risk_level(self, consistency_score: float) -> str:
        if consistency_score >= self.low_risk_threshold:
            return "low"
        elif consistency_score >= self.high_risk_threshold:
            return "medium"
        return "high"

    def _empty_result(
        self,
        response: str,
        token_usage: TokenUsage | None = None,
    ) -> SelfCheckResult:
        return SelfCheckResult(
            response=response,
            sentences=[],
            consistency_score=1.0,
            hallucination_risk="low",
            num_samples=0,
            method=self.method.value,
            sample_token_usage=token_usage or TokenUsage(),
        )
