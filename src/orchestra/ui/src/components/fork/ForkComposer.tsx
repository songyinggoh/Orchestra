/**
 * ForkComposer — modal for branching a run from a historical sequence.
 *
 * Seeded with the projected state at `fromSequence`. User edits the JSON in
 * a plain Textarea (no Monaco for W2 — `@monaco-editor/react` is an option
 * for W3 if editing ergonomics become a pain point). On submit:
 *   1. Parse JSON — inline error on failure
 *   2. POST /runs/{id}/fork with { from_sequence, state_overrides: parsed }
 *   3. On success: navigate to the new run's detail page + toast
 *
 * Parent controls visibility via `open` / `onOpenChange`. Closing while dirty
 * does NOT prompt — the parent run is untouched by fork, so there's nothing
 * destructive to guard against. (UI-SPEC §7.3's AlertDialog confirmation
 * applies to actions that mutate shared state; forking is append-only.)
 */

import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { toast } from 'sonner';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { api, UnauthorizedError } from '../../hooks/useApi';

interface ForkComposerProps {
  runId: string;
  fromSequence: number;
  seedState: Record<string, unknown>;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ForkComposer({
  runId,
  fromSequence,
  seedState,
  open,
  onOpenChange,
}: ForkComposerProps) {
  const navigate = useNavigate();
  const initialText = useMemo(() => JSON.stringify(seedState, null, 2), [seedState]);
  const [text, setText] = useState(initialText);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Reseed the editor each time the dialog is opened with a new sequence.
  useEffect(() => {
    if (open) {
      setText(initialText);
      setError(null);
      setSubmitting(false);
    }
  }, [open, initialText]);

  async function handleLaunch() {
    let overrides: Record<string, unknown>;
    try {
      const parsed = JSON.parse(text);
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        setError('State must be a JSON object.');
        return;
      }
      overrides = parsed as Record<string, unknown>;
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Invalid JSON';
      setError(msg);
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      const { new_run_id } = await api.forkRun(runId, {
        from_sequence: fromSequence,
        state_overrides: overrides,
      });
      toast.success('Run forked');
      onOpenChange(false);
      navigate(`/runs/${new_run_id}`);
    } catch (e) {
      if (e instanceof UnauthorizedError) {
        toast.error('Unauthorized — set an API key and retry.');
      } else {
        const msg = e instanceof Error ? e.message : 'Fork failed';
        toast.error(`Fork failed — ${msg}`);
      }
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Fork run from sequence {fromSequence}</DialogTitle>
          <DialogDescription>
            Edits to state will create a new run branched from this point. The
            parent run is unaffected.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <label
            htmlFor="fork-state-editor"
            className="text-[11px] uppercase tracking-wide text-zinc-500"
          >
            State overrides (JSON)
          </label>
          <Textarea
            id="fork-state-editor"
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              if (error) setError(null);
            }}
            className="min-h-[260px] font-mono text-[12px]"
            spellCheck={false}
            aria-invalid={error !== null}
            aria-describedby={error ? 'fork-state-error' : undefined}
          />
          {error && (
            <p
              id="fork-state-error"
              role="alert"
              className="text-[11px] text-red-400"
            >
              {error}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            Discard fork
          </Button>
          <Button
            onClick={handleLaunch}
            disabled={submitting}
            className="bg-violet-500 text-white hover:bg-violet-400"
          >
            {submitting ? 'Launching…' : 'Launch fork'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
