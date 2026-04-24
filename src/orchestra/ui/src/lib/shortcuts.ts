/**
 * Keyboard-shortcut registry with sequence support (e.g. "g r").
 * W3 extends W2's minimal stub with a full registry and help dialog.
 */

import { useEffect, useRef } from 'react';

export type ShortcutHandler = (ev: KeyboardEvent) => void;

export interface ShortcutMap {
  [key: string]: ShortcutHandler;
}

export type ShortcutScope = 'global' | 'run-detail' | 'run-list';

export interface Shortcut {
  id: string;
  keys: string[];
  sequence?: boolean;
  scope: ShortcutScope;
  label: string;
  handler: () => void;
}

const registry = new Map<string, Shortcut>();

export function registerShortcut(s: Shortcut): () => void {
  registry.set(s.id, s);
  return () => registry.delete(s.id);
}

export function getRegistry(): Shortcut[] {
  return Array.from(registry.values());
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (target.isContentEditable) return true;
  return false;
}

/** Legacy simple map hook — used by ScrubberBar and RunDetailPage. */
export function useShortcuts(map: ShortcutMap, enabled: boolean = true): void {
  useEffect(() => {
    if (!enabled) return;
    function onKey(ev: KeyboardEvent) {
      if (isEditableTarget(ev.target)) return;
      const key = ev.key === 'Spacebar' ? ' ' : ev.key;
      const handler = map[key];
      if (handler) handler(ev);
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [map, enabled]);
}

/** Sequence-aware hook that supports "g r" style chords (1s window). */
export function useGlobalShortcutListener(): void {
  const pendingRef = useRef<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    function onKey(ev: KeyboardEvent) {
      if (isEditableTarget(ev.target)) return;
      const key = ev.key === 'Spacebar' ? ' ' : ev.key;

      const shortcuts = getRegistry();

      // Check two-key sequences first.
      if (pendingRef.current !== null) {
        const seq = `${pendingRef.current} ${key}`;
        const match = shortcuts.find((s) => s.sequence && s.keys.join(' ') === seq);
        if (match) {
          ev.preventDefault();
          match.handler();
          pendingRef.current = null;
          if (timerRef.current) clearTimeout(timerRef.current);
          return;
        }
        pendingRef.current = null;
        if (timerRef.current) clearTimeout(timerRef.current);
      }

      // Check if this key starts a sequence.
      const startsSeq = shortcuts.some((s) => s.sequence && s.keys[0] === key);
      if (startsSeq) {
        pendingRef.current = key;
        timerRef.current = setTimeout(() => { pendingRef.current = null; }, 1000);
        return;
      }

      // Single key match.
      const match = shortcuts.find((s) => !s.sequence && s.keys[0] === key);
      if (match) {
        ev.preventDefault();
        match.handler();
      }
    }

    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}
