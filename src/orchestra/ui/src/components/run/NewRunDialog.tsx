import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { useQuery } from '@tanstack/react-query';
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { api, UnauthorizedError } from '../../hooks/useApi';
import type { GraphInfo } from '../../types/api';

interface NewRunDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Pre-select and lock a workflow name (from GraphDetailPage). */
  workflowName?: string;
}

const DEFAULT_INPUT = '{}';

export function NewRunDialog({ open, onOpenChange, workflowName }: NewRunDialogProps) {
  const navigate = useNavigate();
  const { data: graphs } = useQuery<GraphInfo[]>({
    queryKey: ['graphs'],
    queryFn: () => api.listGraphs(),
    staleTime: 60_000,
  });

  const [selectedWorkflow, setSelectedWorkflow] = useState(workflowName ?? '');
  const [inputText, setInputText] = useState(DEFAULT_INPUT);
  const [inputError, setInputError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setSelectedWorkflow(workflowName ?? '');
      setInputText(DEFAULT_INPUT);
      setInputError(null);
      setSubmitting(false);
    }
  }, [open, workflowName]);

  const canSubmit = selectedWorkflow.trim() !== '' && !submitting;

  const graphNames = useMemo(
    () => (graphs ?? []).map((g) => g.name).sort(),
    [graphs],
  );

  async function handleStart() {
    let initialInput: Record<string, unknown>;
    try {
      const parsed = JSON.parse(inputText);
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        setInputError('Initial input must be a JSON object.');
        return;
      }
      initialInput = parsed as Record<string, unknown>;
    } catch (e) {
      setInputError((e instanceof Error ? e.message : 'Invalid JSON'));
      return;
    }
    setInputError(null);
    setSubmitting(true);
    try {
      const { run_id } = await api.createRun({
        workflow_name: selectedWorkflow,
        initial_input: initialInput,
      });
      toast.success('Run started');
      onOpenChange(false);
      navigate(`/runs/${run_id}`);
    } catch (e) {
      if (e instanceof UnauthorizedError) {
        toast.error('Unauthorized — set an API key in Settings.');
      } else {
        toast.error(`Failed to start run — ${(e as Error).message}`);
      }
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Start a run</DialogTitle>
          <DialogDescription>
            Choose a workflow and provide the initial input to launch a new run.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <label
              htmlFor="new-run-workflow"
              className="mb-1 block text-[11px] uppercase tracking-wide text-zinc-500"
            >
              Workflow
            </label>
            {workflowName ? (
              <p className="rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-300">
                {workflowName}
              </p>
            ) : (
              <Select value={selectedWorkflow} onValueChange={setSelectedWorkflow}>
                <SelectTrigger id="new-run-workflow">
                  <SelectValue placeholder="Select a workflow…" />
                </SelectTrigger>
                <SelectContent>
                  {graphNames.map((name) => (
                    <SelectItem key={name} value={name}>
                      {name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>

          <div>
            <label
              htmlFor="new-run-input"
              className="mb-1 block text-[11px] uppercase tracking-wide text-zinc-500"
            >
              Initial input (JSON)
            </label>
            <Textarea
              id="new-run-input"
              value={inputText}
              onChange={(e) => {
                setInputText(e.target.value);
                if (inputError) setInputError(null);
              }}
              className="min-h-[120px] font-mono text-[12px]"
              spellCheck={false}
              aria-invalid={inputError !== null}
              aria-describedby={inputError ? 'new-run-input-error' : undefined}
            />
            {inputError && (
              <p
                id="new-run-input-error"
                role="alert"
                className="mt-1 text-[11px] text-red-400"
              >
                {inputError}
              </p>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button
            onClick={handleStart}
            disabled={!canSubmit}
            className="bg-violet-500 text-white hover:bg-violet-400"
          >
            {submitting ? 'Starting…' : 'Start a run'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
