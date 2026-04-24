import { useEffect, useState } from 'react';
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
import type { InterruptRequested } from '../../types/events';

interface ResumeDialogProps {
  runId: string;
  interrupt: InterruptRequested;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const APPROVE_REJECT_TYPES = new Set(['approval', 'approve_reject', 'human_approval']);

export function ResumeDialog({ runId, interrupt, open, onOpenChange }: ResumeDialogProps) {
  const isApproveReject = APPROVE_REJECT_TYPES.has(interrupt.interrupt_type);
  const [decision, setDecision] = useState(isApproveReject ? 'approve' : '');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setDecision(isApproveReject ? 'approve' : '');
      setSubmitting(false);
    }
  }, [open, isApproveReject]);

  const prompt =
    typeof interrupt.payload?.question === 'string'
      ? interrupt.payload.question
      : typeof interrupt.payload?.prompt === 'string'
        ? interrupt.payload.prompt
        : JSON.stringify(interrupt.payload, null, 2);

  async function handleSubmit() {
    if (!decision.trim()) return;
    setSubmitting(true);
    try {
      await api.resumeRun(runId, { state_updates: { decision } });
      toast.success('Run resumed');
      onOpenChange(false);
    } catch (e) {
      if (e instanceof UnauthorizedError) {
        toast.error('Unauthorized — set an API key in Settings.');
      } else {
        toast.error(`Resume failed — ${(e as Error).message}`);
      }
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Resume run</DialogTitle>
          <DialogDescription>
            This run is paused awaiting a human decision.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <p className="mb-1 text-[11px] uppercase tracking-wide text-zinc-500">
              Interrupt type
            </p>
            <p className="text-sm text-zinc-300">{interrupt.interrupt_type}</p>
          </div>

          {prompt && (
            <div>
              <p className="mb-1 text-[11px] uppercase tracking-wide text-zinc-500">
                Prompt
              </p>
              <p className="whitespace-pre-wrap rounded-md bg-zinc-800 px-3 py-2 text-sm text-zinc-200">
                {prompt}
              </p>
            </div>
          )}

          <div>
            <label
              htmlFor="resume-decision"
              className="mb-1 block text-[11px] uppercase tracking-wide text-zinc-500"
            >
              Decision
            </label>
            {isApproveReject ? (
              <Select value={decision} onValueChange={setDecision}>
                <SelectTrigger id="resume-decision">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="approve">Approve</SelectItem>
                  <SelectItem value="reject">Reject</SelectItem>
                </SelectContent>
              </Select>
            ) : (
              <Textarea
                id="resume-decision"
                value={decision}
                onChange={(e) => setDecision(e.target.value)}
                placeholder="Enter your response…"
                className="min-h-[80px] text-sm"
              />
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
            onClick={handleSubmit}
            disabled={submitting || !decision.trim()}
            className="bg-violet-500 text-white hover:bg-violet-400"
          >
            {submitting ? 'Resuming…' : 'Resume run'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
