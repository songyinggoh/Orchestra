/**
 * Minimal keyboard-shortcut registry.
 *
 * W2 only uses this for the scrubber 5 keys (← → Space Home/End .).
 * W3 will extend it with Cmd-K palette integration and a user-visible
 * "press ? for help" cheatsheet. Keep the surface small until then.
 *
 * Callers use `useShortcuts` to bind handlers while a component is mounted;
 * the hook attaches a single window keydown listener and dispatches by key.
 * Shortcuts are ignored while focus is inside an editable element (input,
 * textarea, contenteditable) so users can type freely inside dialogs.
 */

import { useEffect } from 'react';

export type ShortcutHandler = (ev: KeyboardEvent) => void;

export interface ShortcutMap {
  /** Map of key tokens → handler. Tokens match `KeyboardEvent.key`
   * ('ArrowLeft', 'ArrowRight', ' ', 'Home', 'End', '.', 'F', 'R'). */
  [key: string]: ShortcutHandler;
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (target.isContentEditable) return true;
  return false;
}

export function useShortcuts(map: ShortcutMap, enabled: boolean = true): void {
  useEffect(() => {
    if (!enabled) return;
    function onKey(ev: KeyboardEvent) {
      if (isEditableTarget(ev.target)) return;
      // Normalize space — some browsers report 'Spacebar'.
      const key = ev.key === 'Spacebar' ? ' ' : ev.key;
      const handler = map[key];
      if (handler) handler(ev);
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [map, enabled]);
}
