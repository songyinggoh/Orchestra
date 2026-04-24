import { useBranchLedger } from '../../hooks/useBranchLedger';
import { ledgerTotal } from '../../lib/branchLedger';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

const COST_COLORS = [
  'bg-sky-500', 'bg-teal-500', 'bg-emerald-500',
  'bg-yellow-500', 'bg-orange-500', 'bg-red-500',
];

function costColor(cost: number, total: number): string {
  if (total === 0) return COST_COLORS[0];
  const ratio = cost / total;
  const idx = Math.min(Math.floor(ratio * COST_COLORS.length), COST_COLORS.length - 1);
  return COST_COLORS[idx];
}

export function BranchCostBar({ runId }: { runId: string }) {
  const ledger = useBranchLedger(runId);
  const branches = Object.values(ledger);
  if (branches.length === 0) return null;

  const total = ledgerTotal(ledger);

  return (
    <div
      className="flex h-4 w-full overflow-hidden border-b border-zinc-800"
      role="img"
      aria-label={`Branch cost breakdown — total $${total.toFixed(4)}`}
    >
      {branches.map((b) => {
        const pct = total > 0 ? (b.cost_usd / total) * 100 : 100 / branches.length;
        const color = costColor(b.cost_usd, total);
        return (
          <Tooltip key={b.branch_id}>
            <TooltipTrigger asChild>
              <div
                className={`${color} flex items-center justify-center overflow-hidden text-[9px] font-mono text-white/80`}
                style={{ width: `${pct}%`, minWidth: pct > 5 ? undefined : 0 }}
                aria-label={`Branch ${b.branch_id}: $${b.cost_usd.toFixed(4)}`}
              >
                {pct >= 8 && `$${b.cost_usd.toFixed(3)}`}
              </div>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="max-w-xs text-xs">
              <p className="font-mono font-semibold">{b.branch_id}</p>
              <p>Nodes: {b.nodes.join(' → ')}</p>
              <p>Cost: ${b.cost_usd.toFixed(6)}</p>
            </TooltipContent>
          </Tooltip>
        );
      })}
    </div>
  );
}
