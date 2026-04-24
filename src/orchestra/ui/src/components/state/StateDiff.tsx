/**
 * Two-pane JSON diff for time-travel mode.
 *
 * Left:  state at sequence-1 (or {} for the first event)
 * Right: state at sequence (the selected frame)
 *
 * Above both panes, a compact key-level summary lists every key that
 * differs between the two states:
 *    added     — key exists in `after` but not `before`   (green)
 *    removed   — key exists in `before` but not `after`   (red)
 *    modified  — key exists in both but values differ     (amber)
 *
 * Values are stringified with JSON.stringify for comparison — this matches
 * server-side state-update semantics (state is a plain dict of JSON-able
 * primitives, lists, and dicts).
 */

import { useMemo } from 'react';
import { JsonView, darkStyles, allExpanded } from 'react-json-view-lite';
import 'react-json-view-lite/dist/index.css';

interface StateDiffProps {
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  beforeLabel?: string;
  afterLabel?: string;
}

type ChangeKind = 'added' | 'removed' | 'modified';

interface KeyChange {
  key: string;
  kind: ChangeKind;
}

function diffKeys(
  before: Record<string, unknown>,
  after: Record<string, unknown>,
): KeyChange[] {
  const keys = new Set([...Object.keys(before), ...Object.keys(after)]);
  const changes: KeyChange[] = [];
  for (const key of keys) {
    const hasBefore = key in before;
    const hasAfter = key in after;
    if (!hasBefore && hasAfter) changes.push({ key, kind: 'added' });
    else if (hasBefore && !hasAfter) changes.push({ key, kind: 'removed' });
    else if (JSON.stringify(before[key]) !== JSON.stringify(after[key]))
      changes.push({ key, kind: 'modified' });
  }
  return changes.sort((a, b) => a.key.localeCompare(b.key));
}

const KIND_STYLE: Record<ChangeKind, string> = {
  added:    'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30',
  removed:  'bg-red-500/15 text-red-300 ring-1 ring-red-500/30',
  modified: 'bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30',
};

export function StateDiff({
  before,
  after,
  beforeLabel = 'before',
  afterLabel = 'after',
}: StateDiffProps) {
  const changes = useMemo(() => diffKeys(before, after), [before, after]);
  const beforeKeys = Object.keys(before).length;
  const afterKeys = Object.keys(after).length;

  return (
    <div className="flex h-full flex-col border-t border-zinc-800 bg-zinc-900/50">
      <div className="border-b border-zinc-800 px-3 py-2">
        <div className="text-[11px] font-medium text-zinc-400">
          State diff · {changes.length} change{changes.length === 1 ? '' : 's'}
        </div>
        {changes.length > 0 && (
          <ul className="mt-1.5 flex flex-wrap gap-1">
            {changes.map((c) => (
              <li
                key={`${c.kind}:${c.key}`}
                className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${KIND_STYLE[c.kind]}`}
                title={c.kind}
              >
                {c.kind === 'added' && '+ '}
                {c.kind === 'removed' && '− '}
                {c.kind === 'modified' && '~ '}
                {c.key}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="grid flex-1 grid-cols-2 gap-0 overflow-hidden">
        <section className="flex min-h-0 flex-col border-r border-zinc-800">
          <header className="px-3 py-1 text-[10px] uppercase tracking-wide text-zinc-500">
            {beforeLabel} · {beforeKeys} key{beforeKeys === 1 ? '' : 's'}
          </header>
          <div className="min-h-0 flex-1 overflow-auto px-3 pb-2 font-mono text-[11px]">
            <JsonView
              data={before}
              style={darkStyles}
              shouldExpandNode={allExpanded}
            />
          </div>
        </section>
        <section className="flex min-h-0 flex-col">
          <header className="px-3 py-1 text-[10px] uppercase tracking-wide text-zinc-500">
            {afterLabel} · {afterKeys} key{afterKeys === 1 ? '' : 's'}
          </header>
          <div className="min-h-0 flex-1 overflow-auto px-3 pb-2 font-mono text-[11px]">
            <JsonView
              data={after}
              style={darkStyles}
              shouldExpandNode={allExpanded}
            />
          </div>
        </section>
      </div>
    </div>
  );
}
