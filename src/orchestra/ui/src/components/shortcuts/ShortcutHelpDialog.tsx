import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { getRegistry } from '../../lib/shortcuts';
import type { ShortcutScope } from '../../lib/shortcuts';

const SCOPE_LABELS: Record<ShortcutScope, string> = {
  global: 'Global',
  'run-detail': 'Run detail',
  'run-list': 'Run list',
};

interface Props { open: boolean; onOpenChange: (v: boolean) => void }

export function ShortcutHelpDialog({ open, onOpenChange }: Props) {
  const shortcuts = getRegistry();
  const scopes: ShortcutScope[] = ['global', 'run-detail', 'run-list'];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" aria-describedby="shortcut-help-desc">
        <DialogHeader>
          <DialogTitle>Keyboard shortcuts</DialogTitle>
        </DialogHeader>
        <p id="shortcut-help-desc" className="sr-only">All available keyboard shortcuts grouped by scope.</p>
        <div className="space-y-4 text-sm">
          {scopes.map((scope) => {
            const items = shortcuts.filter((s) => s.scope === scope);
            if (items.length === 0) return null;
            return (
              <section key={scope} aria-labelledby={`scope-${scope}`}>
                <h3 id={`scope-${scope}`} className="mb-2 text-[10px] uppercase tracking-wide text-zinc-500">
                  {SCOPE_LABELS[scope]}
                </h3>
                <ul className="space-y-1">
                  {items.map((s) => (
                    <li key={s.id} className="flex items-center justify-between">
                      <span className="text-zinc-300">{s.label}</span>
                      <kbd className="rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-[11px] text-zinc-400">
                        {s.keys.join(' ')}
                      </kbd>
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      </DialogContent>
    </Dialog>
  );
}
