"""Tree of Thoughts (ToT) reasoning for Orchestra.

Implements the ToT framework (Yao et al., 2023) which prevents overplanning by:
  - Generating small, scoped thoughts at each step (not full plans upfront)
  - Evaluating each thought before expanding it ("sure / maybe / impossible")
  - Pruning unpromising branches early via BFS beam search or DFS backtracking
  - Only committing depth proportional to validated progress

Reference: https://arxiv.org/abs/2305.10601

Two search strategies:
  BFS (default) — generate k thoughts at each level, keep top b, advance all survivors.
                  Best for problems where many partial paths look promising.
  DFS           — go deep on the best thought, backtrack if stuck.
                  Best for problems with clear dead-ends (e.g. constraint satisfaction).

Usage:
    from orchestra.reasoning import TreeOfThoughtsAgent, ToTSearchStrategy

    agent = TreeOfThoughtsAgent(
        name="planner",
        model="gpt-4o-mini",
        system_prompt="You are a strategic planner.",
        tot_breadth=3,       # k — thoughts generated per node
        tot_beam=2,          # b — thoughts kept per BFS level
        tot_max_depth=4,     # maximum planning depth
        tot_strategy=ToTSearchStrategy.BFS,
    )

    result = await agent.run("Plan a 3-day product launch.", context)
    print(result.output)                          # final answer
    print(result.state_updates["thought_tree"])   # full tree for observability
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog
from pydantic import Field

from orchestra.core.agent import BaseAgent
from orchestra.core.context import ExecutionContext
from orchestra.core.types import AgentResult, Message, MessageRole, TokenUsage

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FINAL_PREFIX = "FINAL ANSWER:"
_IMPOSSIBLE_THRESHOLD = 0.2   # value <= this → prune immediately


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ThoughtNode:
    """A single node in the thought tree."""

    thought: str
    value: float           # 0.0 = impossible, 0.5 = maybe, 1.0 = sure
    depth: int
    parent: "ThoughtNode | None" = field(default=None, repr=False)
    children: list["ThoughtNode"] = field(default_factory=list, repr=False)
    is_terminal: bool = False   # True when thought contains FINAL ANSWER

    def chain(self) -> list[str]:
        """Full thought path from root to this node."""
        nodes: list[ThoughtNode] = []
        node: ThoughtNode | None = self
        while node is not None:
            nodes.append(node)
            node = node.parent
        return [n.thought for n in reversed(nodes)]

    def final_answer(self) -> str:
        """Extract the answer text from a terminal thought."""
        if _FINAL_PREFIX in self.thought:
            return self.thought.split(_FINAL_PREFIX, 1)[1].strip()
        return self.thought

    def to_dict(self) -> dict[str, Any]:
        return {
            "thought": self.thought,
            "value": round(self.value, 3),
            "depth": self.depth,
            "is_terminal": self.is_terminal,
            "children": [c.to_dict() for c in self.children],
        }


class ToTSearchStrategy(str, Enum):
    BFS = "bfs"   # breadth-first beam search (default)
    DFS = "dfs"   # depth-first with backtracking


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

_GENERATE_PROMPT = """\
Problem:
{problem}

Thought chain so far:
{chain}

Generate exactly {k} distinct next steps or partial solutions.
Rules:
- Each thought must be concise (1-3 sentences) and build on the chain above.
- If a thought completes the problem, prefix it with "{final_prefix}".
- Output exactly {k} thoughts, each on its own line, prefixed with "Thought N:" (N=1,2,...).
- Do NOT include explanations outside the thoughts themselves.

Thoughts:"""

_EVALUATE_PROMPT = """\
Problem:
{problem}

Thought chain so far:
{chain}

Proposed next thought:
{thought}

Does this thought make meaningful progress toward solving the problem?
Answer with exactly one word: "sure", "maybe", or "impossible".

Reasoning (1 sentence max):
Answer:"""

_VALUE_MAP = {"sure": 1.0, "maybe": 0.5, "impossible": 0.0}


# ---------------------------------------------------------------------------
# TreeOfThoughtsAgent
# ---------------------------------------------------------------------------


class TreeOfThoughtsAgent(BaseAgent):
    """A BaseAgent that reasons via Tree of Thoughts search.

    Prevents overplanning by keeping each thought unit small and evaluating
    it before expanding further. The final answer is only produced after the
    search confirms the path is sound.

    Attributes:
        tot_breadth:    k — number of candidate thoughts to generate per node.
        tot_beam:       b — number of thoughts to keep per BFS level (beam width).
        tot_max_depth:  Maximum depth of the thought tree.
        tot_strategy:   Search strategy: BFS (default) or DFS.
        tot_temperature: Sampling temperature for thought generation (default 0.7).
        eval_temperature: Temperature for the evaluator (default 0.0 for consistency).
    """

    tot_breadth: int = 3
    tot_beam: int = 2
    tot_max_depth: int = 4
    tot_strategy: ToTSearchStrategy = ToTSearchStrategy.BFS
    tot_temperature: float = 0.7
    eval_temperature: float = 0.0

    model_config = {"arbitrary_types_allowed": True}

    async def run(
        self,
        input: str | list[Message],
        context: ExecutionContext,
    ) -> AgentResult:
        llm = context.provider
        if not llm:
            raise RuntimeError(
                f"Agent '{self.name}' has no LLM provider. "
                "Pass provider= when calling compiled.run()."
            )

        problem = self._resolve_problem(input)
        total_usage = TokenUsage()

        logger.info(
            "tot_search_start",
            agent=self.name,
            strategy=self.tot_strategy.value,
            breadth=self.tot_breadth,
            beam=self.tot_beam,
            max_depth=self.tot_max_depth,
        )

        if self.tot_strategy == ToTSearchStrategy.BFS:
            best_node, usage = await self._bfs(problem, llm)
        else:
            best_node, usage = await self._dfs(problem, llm)

        total_usage.input_tokens += usage.input_tokens
        total_usage.output_tokens += usage.output_tokens
        total_usage.total_tokens += usage.total_tokens
        total_usage.estimated_cost_usd += usage.estimated_cost_usd

        if best_node is None:
            output = "Tree of Thoughts search exhausted without finding a solution."
            root_dict: dict[str, Any] = {}
        else:
            output = best_node.final_answer()
            root_dict = best_node.to_dict()
            logger.info(
                "tot_search_complete",
                agent=self.name,
                depth=best_node.depth,
                value=round(best_node.value, 3),
                chain_length=len(best_node.chain()),
            )

        return AgentResult(
            agent_name=self.name,
            output=output,
            messages=[Message(role=MessageRole.ASSISTANT, content=output, name=self.name)],
            token_usage=total_usage,
            state_updates={
                "thought_tree": root_dict,
                "thought_chain": best_node.chain() if best_node else [],
                "tot_strategy": self.tot_strategy.value,
            },
        )

    # -------------------------------------------------------------------------
    # BFS search
    # -------------------------------------------------------------------------

    async def _bfs(
        self, problem: str, llm: Any
    ) -> tuple[ThoughtNode | None, TokenUsage]:
        """Breadth-first beam search through the thought tree."""
        total_usage = TokenUsage()
        root = ThoughtNode(thought=problem, value=1.0, depth=0)

        # frontier holds the current beam of ThoughtNodes to expand
        frontier: list[ThoughtNode] = [root]
        best_terminal: ThoughtNode | None = None

        for depth in range(1, self.tot_max_depth + 1):
            # Generate k children for every node in the frontier (parallel)
            gen_tasks = [
                self._generate_thoughts(problem, node, llm)
                for node in frontier
            ]
            gen_results = await asyncio.gather(*gen_tasks, return_exceptions=True)

            candidates: list[ThoughtNode] = []
            for node, result in zip(frontier, gen_results):
                if isinstance(result, Exception):
                    logger.warning("tot_generate_error", error=str(result))
                    continue
                thoughts, usage = result
                _accumulate(total_usage, usage)
                for t in thoughts:
                    child = ThoughtNode(thought=t, value=0.5, depth=depth, parent=node)
                    node.children.append(child)
                    candidates.append(child)

            if not candidates:
                break

            # Evaluate all candidates in parallel
            eval_tasks = [
                self._evaluate_thought(problem, node, llm)
                for node in candidates
            ]
            eval_results = await asyncio.gather(*eval_tasks, return_exceptions=True)

            scored: list[ThoughtNode] = []
            for node, result in zip(candidates, eval_results):
                if isinstance(result, Exception):
                    logger.warning("tot_evaluate_error", error=str(result))
                    node.value = 0.5
                else:
                    value, usage = result
                    node.value = value
                    _accumulate(total_usage, usage)

                if node.is_terminal:
                    if best_terminal is None or node.value > best_terminal.value:
                        best_terminal = node
                elif node.value > _IMPOSSIBLE_THRESHOLD:
                    scored.append(node)

            if best_terminal:
                break

            # Keep top-b survivors as the new frontier
            scored.sort(key=lambda n: n.value, reverse=True)
            frontier = scored[: self.tot_beam]

            logger.debug(
                "tot_bfs_level",
                depth=depth,
                candidates=len(candidates),
                survivors=len(frontier),
            )

            if not frontier:
                break

        # If no terminal found, return the highest-value frontier node
        if best_terminal:
            return best_terminal, total_usage

        all_leaves = frontier
        if not all_leaves:
            return None, total_usage

        best_leaf = max(all_leaves, key=lambda n: n.value)
        # Mark it terminal so final_answer() is called correctly
        best_leaf.is_terminal = True
        return best_leaf, total_usage

    # -------------------------------------------------------------------------
    # DFS search
    # -------------------------------------------------------------------------

    async def _dfs(
        self, problem: str, llm: Any
    ) -> tuple[ThoughtNode | None, TokenUsage]:
        """Depth-first search with backtracking through the thought tree."""
        total_usage = TokenUsage()
        root = ThoughtNode(thought=problem, value=1.0, depth=0)

        best_terminal: ThoughtNode | None = None

        # Stack entries: (node, already_expanded)
        stack: list[ThoughtNode] = [root]

        while stack:
            node = stack.pop()

            if node.depth >= self.tot_max_depth or node.is_terminal:
                if best_terminal is None or node.value > (best_terminal.value if best_terminal else -1):
                    node.is_terminal = True
                    best_terminal = node
                continue

            thoughts, usage = await self._generate_thoughts(problem, node, llm)
            _accumulate(total_usage, usage)

            children: list[ThoughtNode] = []
            for t in thoughts:
                child = ThoughtNode(
                    thought=t,
                    value=0.5,
                    depth=node.depth + 1,
                    parent=node,
                )
                node.children.append(child)
                children.append(child)

            # Evaluate children
            eval_tasks = [self._evaluate_thought(problem, c, llm) for c in children]
            eval_results = await asyncio.gather(*eval_tasks, return_exceptions=True)

            viable: list[ThoughtNode] = []
            for child, result in zip(children, eval_results):
                if isinstance(result, Exception):
                    child.value = 0.5
                    viable.append(child)
                else:
                    value, usage = result
                    child.value = value
                    _accumulate(total_usage, usage)
                    if child.is_terminal:
                        if best_terminal is None or child.value > best_terminal.value:
                            best_terminal = child
                    elif child.value > _IMPOSSIBLE_THRESHOLD:
                        viable.append(child)

            if best_terminal:
                break

            # Push viable children sorted ascending so highest-value is popped first
            viable.sort(key=lambda n: n.value)
            stack.extend(viable)

            logger.debug(
                "tot_dfs_step",
                depth=node.depth,
                viable=len(viable),
                stack_size=len(stack),
            )

        return best_terminal, total_usage

    # -------------------------------------------------------------------------
    # LLM calls
    # -------------------------------------------------------------------------

    async def _generate_thoughts(
        self, problem: str, node: ThoughtNode, llm: Any
    ) -> tuple[list[str], TokenUsage]:
        """Ask the LLM to generate k next thoughts from this node."""
        chain_text = "\n".join(
            f"Step {i + 1}: {t}" for i, t in enumerate(node.chain())
        ) or "(none yet)"

        prompt = _GENERATE_PROMPT.format(
            problem=problem,
            chain=chain_text,
            k=self.tot_breadth,
            final_prefix=_FINAL_PREFIX,
        )

        response = await llm.complete(
            messages=[
                Message(role=MessageRole.SYSTEM, content=self.system_prompt),
                Message(role=MessageRole.USER, content=prompt),
            ],
            model=self.model,
            temperature=self.tot_temperature,
        )

        usage = response.usage or TokenUsage()
        thoughts = _parse_thoughts(response.content or "", self.tot_breadth)
        return thoughts, usage

    async def _evaluate_thought(
        self, problem: str, node: ThoughtNode, llm: Any
    ) -> tuple[float, TokenUsage]:
        """Ask the LLM to evaluate a thought and return (value, usage)."""
        # Terminal thoughts skip evaluation
        if _FINAL_PREFIX in node.thought:
            node.is_terminal = True
            return 1.0, TokenUsage()

        chain = node.chain()
        chain_text = "\n".join(
            f"Step {i + 1}: {t}" for i, t in enumerate(chain[:-1])
        ) or "(none yet)"

        prompt = _EVALUATE_PROMPT.format(
            problem=problem,
            chain=chain_text,
            thought=node.thought,
        )

        response = await llm.complete(
            messages=[
                Message(role=MessageRole.SYSTEM, content=self.system_prompt),
                Message(role=MessageRole.USER, content=prompt),
            ],
            model=self.model,
            temperature=self.eval_temperature,
        )

        usage = response.usage or TokenUsage()
        raw = (response.content or "").strip().lower()

        # Extract the rating word — handle "Answer: sure" etc.
        value = 0.5  # default to maybe
        for word, score in _VALUE_MAP.items():
            if word in raw:
                value = score
                break

        logger.debug(
            "tot_eval",
            depth=node.depth,
            value=value,
            raw=raw[:60],
        )
        return value, usage

    # -------------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------------

    def _resolve_problem(self, input: str | list[Message]) -> str:
        if isinstance(input, str):
            return input
        for msg in input:
            if msg.role == MessageRole.USER and msg.content:
                return msg.content
        return ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_thoughts(text: str, k: int) -> list[str]:
    """Parse 'Thought N: ...' lines from LLM output."""
    thoughts: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Accept "Thought N:", "Step N:", bare numbered lines, or FINAL ANSWER
        if _FINAL_PREFIX in line:
            thoughts.append(line)
        elif line[0].isdigit() and "." in line[:4]:
            thoughts.append(line.split(".", 1)[1].strip())
        elif ":" in line and line.split(":")[0].strip().lower().startswith(("thought", "step")):
            thoughts.append(line.split(":", 1)[1].strip())
        else:
            thoughts.append(line)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for t in thoughts:
        if t and t not in seen:
            seen.add(t)
            unique.append(t)

    return unique[:k]


def _accumulate(total: TokenUsage, usage: TokenUsage) -> None:
    total.input_tokens += usage.input_tokens
    total.output_tokens += usage.output_tokens
    total.total_tokens += usage.total_tokens
    total.estimated_cost_usd += usage.estimated_cost_usd
