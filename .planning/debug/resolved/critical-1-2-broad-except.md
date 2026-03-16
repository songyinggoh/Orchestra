---
status: resolved
trigger: "Fix CRITICAL-1.2: overly broad except (ImportError, Exception) in compiled.py:266"
created: 2026-03-15T00:00:00Z
updated: 2026-03-15T00:00:00Z
---

## Current Focus

hypothesis: Line 265-266 catches all exceptions including SystemExit/KeyboardInterrupt masking fatal signals
test: Replace with narrow exception list covering only what initialize() actually raises
expecting: Fatal exceptions propagate; recoverable ones become AgentError
next_action: Apply fix and add regression tests

## Symptoms

expected: Only expected I/O and DB exceptions caught; fatal signals propagate
actual: except (ImportError, Exception) swallows everything including SystemExit, KeyboardInterrupt, RuntimeError
errors: No error — silent masking; any fatal condition becomes AgentError
reproduction: Raise RuntimeError inside SQLiteEventStore.initialize() — it becomes AgentError instead of propagating
started: Present since the code was written

## Eliminated

- hypothesis: The broad catch might be intentional fallback for all store backends
  evidence: The comment says "Try to auto-load SQLite if no store provided" — only covers SQLite import + init
  timestamp: 2026-03-15T00:00:00Z

## Evidence

- timestamp: 2026-03-15T00:00:00Z
  checked: compiled.py lines 261-266
  found: try block does exactly 2 things: (1) import SQLiteEventStore, (2) SQLiteEventStore() + initialize()
  implication: Only ImportError (missing aiosqlite), OSError (makedirs), sqlite3.Error (DB ops) are expected

- timestamp: 2026-03-15T00:00:00Z
  checked: sqlite.py initialize() method
  found: os.makedirs (OSError), aiosqlite.connect + DDL execute/commit (sqlite3.Error subclass)
  implication: aiosqlite.Error IS-A sqlite3.Error confirmed by runtime check

## Resolution

root_cause: except (ImportError, Exception) is too broad — Exception is a superclass of all non-system exceptions, making the ImportError redundant and swallowing RuntimeError, AssertionError, etc.
fix: Replace with except (ImportError, OSError, sqlite3.Error) — exactly the three error categories the try block can produce
verification: 550 unit tests pass (4 skipped), 4 new regression tests all green
files_changed:
  - src/orchestra/core/compiled.py
  - tests/unit/test_core.py
