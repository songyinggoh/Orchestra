---
status: resolved
trigger: "fix-8-unit-test-failures"
created: 2026-03-21T00:00:00Z
updated: 2026-03-21T00:02:00Z
---

## Current Focus

hypothesis: CONFIRMED — test_load_uses_provided_builder (test 9) is contradictory with tests 4 and 8 which both use prefix ["orchestra.core."] and expect refs starting with "orchestra.core." to PASS the allowlist. No prefix-matching rule can simultaneously allow orchestra.core.types.NonExistentClass AND block orchestra.core.dynamic.dump_graph_yaml under the same prefix.
test: Exhaustive logical proof — checked all string-prefix matching strategies; none can distinguish these refs under prefix ["orchestra.core."]
expecting: 7 of 8 originally-failing tests fixed; test_load_uses_provided_builder has contradictory assertion and cannot be fixed without modifying the test itself
next_action: Report to user — test_load_uses_provided_builder assertion conflicts with test_resolve_nonexistent_module_raises_import_error and test_resolve_bad_attribute_raises_import_error. The test's YAML ref should use a ref that starts with a DIFFERENT prefix (e.g. "orchestra.tools." or "os.") to actually test custom builder rejection.

## Symptoms

expected: All 8 tests pass
actual: 8 tests fail across 2 test files
errors:
  - test_context_distill.py::TestInternalHelpers::test_get_content_none
      assert _get_content({"role": "user"}) == "None"
      AssertionError: assert '' == 'None'
  - test_context_distill.py::TestDistillContextEdgeCases::test_keep_last_n_zero_drops_everything
      assert result == []
      Left contains one more item: {'content': '[Context summary: a b]', 'role': 'assistant'}
  - test_dynamic_graphs.py::TestLoadGraphYaml::* (6 tests)
      GraphCompileError: Edge target '__end__' not found in nodes.
reproduction: python -m pytest tests/unit/test_context_distill.py tests/unit/test_dynamic_graphs.py -v --tb=short
started: Tests are new (untracked), written against existing source files

## Eliminated

- hypothesis: tests are written incorrectly
  evidence: tests are read-only spec; source must match them
  timestamp: 2026-03-21T00:00:00Z

- hypothesis: a prefix-matching rule change could resolve all 8 tests simultaneously
  evidence: Tests 4, 8, and 9 all use prefix ["orchestra.core."] with refs starting with "orchestra.core." — tests 4 and 8 expect PASS, test 9 expects BLOCK. No string-based matching rule can distinguish between these three refs under the same prefix. Exhaustively checked: startswith(prefix), exact module matching, dot-boundary matching, module-exact matching. All produce the same result for all three refs.
  timestamp: 2026-03-21T00:02:00Z

## Evidence

- timestamp: 2026-03-21T00:00:00Z
  checked: context_distill.py _get_content()
  found: returns str(msg.get("content", "")) — when key is absent, msg.get returns None, str(None) == "None" BUT for dict case it returns str("") == "" because default is ""
  implication: Bug 1a — default should be None not "", so str(None) == "None" as test expects

- timestamp: 2026-03-21T00:00:00Z
  checked: context_distill.py distill_context() with keep_last_n_turns=0
  found: suffix = [] (correct), middleware = rest[: max(0, len(rest)-0)] = rest[:len(rest)] = all of rest
  found: middleware is non-empty so code falls through to summary generation and emits a summary message
  implication: Bug 1b — when keep_last_n_turns==0, middleware content should still be dropped (no suffix to anchor context to); test expects empty list

- timestamp: 2026-03-21T00:00:00Z
  checked: dynamic.py load_graph_yaml() edge handling
  found: graph.add_edge(source, target) called with target="__end__" (raw string)
  found: graph validation requires END sentinel from orchestra.core.types, not raw string
  implication: Bug 2 — must import END and substitute it when target == "__end__"

- timestamp: 2026-03-21T00:01:00Z
  checked: test_load_uses_provided_builder vs test_resolve_nonexistent_module_raises_import_error vs test_resolve_bad_attribute_raises_import_error
  found: All three use prefix ["orchestra.core."]; tests 4 and 8 expect allowlist to PASS for orchestra.core.* refs; test 9 expects allowlist to BLOCK orchestra.core.dynamic.dump_graph_yaml
  implication: CONTRADICTION — no prefix-matching rule can produce different outcomes for refs that all start with the same prefix string. Test 9 has an authorship error in its assertion.

## Resolution

root_cause: |
  Bug 1a: context_distill._get_content() — dict branch uses default "" so str(missing) == "" but test expects "None"
  Bug 1b: context_distill.distill_context() — when keep_last_n_turns=0, suffix is empty but middleware is the full rest list; code falls through to summary generation and emits a summary message instead of returning []
  Bug 2: dynamic.load_graph_yaml() — passes raw string "__end__" to graph.add_edge; graph validation requires the END sentinel from orchestra.core.types
  Test authorship error: test_load_uses_provided_builder asserts that prefix ["orchestra.core."] blocks orchestra.core.dynamic.dump_graph_yaml — this is contradicted by test_resolve_nonexistent_module_raises_import_error and test_resolve_bad_attribute_raises_import_error which both expect orchestra.core.* refs to PASS the same prefix. No source change can reconcile this without modifying the test.

fix: |
  Applied to src/orchestra/core/context_distill.py:
  1. _get_content dict branch: changed default from "" to None → str(None) == "None" as expected
  2. distill_context: changed guard from "if not middleware" to "if not middleware or not suffix" → when suffix is empty, skip summary and return prefix + [] == []
  Applied to src/orchestra/core/dynamic.py:
  3. Added "from orchestra.core.types import END" import
  4. Edge addition: graph.add_edge(source, END if target == "__end__" else target)

verification: |
  7 of 8 originally-failing tests now pass (43/44 in test files, 1011/1012 total).
  test_load_uses_provided_builder remains failing due to contradictory assertion.
  Suggested test fix: change the YAML ref from orchestra.core.dynamic.dump_graph_yaml to a ref outside the allowed prefix, e.g. orchestra.tools.some_func, to properly test that custom builder rejects out-of-prefix refs.

files_changed:
  - src/orchestra/core/context_distill.py
  - src/orchestra/core/dynamic.py
