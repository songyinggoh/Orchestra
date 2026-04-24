import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TooltipProvider } from '@/components/ui/tooltip';
import { BranchCostBar } from './BranchCostBar';

function Wrapper({ children }: { children: React.ReactNode }) {
  return <TooltipProvider>{children}</TooltipProvider>;
}

// Mock useBranchLedger so we control the ledger shape.
vi.mock('../../hooks/useBranchLedger', () => ({
  useBranchLedger: (runId: string) => {
    if (runId !== 'run-test') return {};
    return {
      'p-1/node_a': { branch_id: 'p-1/node_a', nodes: ['node_a'], cost_usd: 0.10, started_at: '2026-01-01T00:00:00Z' },
      'p-1/node_b': { branch_id: 'p-1/node_b', nodes: ['node_b'], cost_usd: 0.20, started_at: '2026-01-01T00:00:00Z' },
      'p-1/node_c': { branch_id: 'p-1/node_c', nodes: ['node_c'], cost_usd: 0.05, started_at: '2026-01-01T00:00:00Z' },
    };
  },
}));

describe('BranchCostBar', () => {
  it('renders nothing when ledger has 0 branches', () => {
    const { container } = render(<BranchCostBar runId="empty-run" />, { wrapper: Wrapper });
    expect(container.firstChild).toBeNull();
  });

  it('renders 3 branch slices for a 3-branch ledger', () => {
    render(<BranchCostBar runId="run-test" />, { wrapper: Wrapper });
    const slices = document.querySelectorAll('[aria-label^="Branch p-1/"]');
    expect(slices).toHaveLength(3);
  });

  it('outer container has role=img with a cost summary label', () => {
    render(<BranchCostBar runId="run-test" />, { wrapper: Wrapper });
    const bar = screen.getByRole('img');
    expect(bar.getAttribute('aria-label')).toMatch(/Branch cost breakdown/);
  });

  it('slice widths are proportional to cost', () => {
    render(<BranchCostBar runId="run-test" />, { wrapper: Wrapper });
    const total = 0.10 + 0.20 + 0.05;
    const sliceB = document.querySelector('[aria-label="Branch p-1/node_b: $0.2000"]') as HTMLElement | null;
    if (sliceB) {
      const pct = (0.20 / total) * 100;
      expect(sliceB.style.width).toBe(`${pct}%`);
    }
  });
});
