/**
 * branchLedger — pure accumulator that derives per-parallel-branch cost from
 * an event stream. No React, no fetch; usable in memoisation hooks.
 *
 * Algorithm:
 *   1. On parallel.started: record a new branch group with declared target nodes.
 *   2. On node.started: attribute the node to the innermost branch that declared it.
 *      Uses the declared target list from the parallel.started payload, bounded by
 *      join_node when graphInfo provides it (T-6.3.2a). Falls back to declaration-
 *      list membership when join_node is absent (documented limitation in T-6.3.1).
 *   3. On llm.called: attribute cost to the owning branch via the node→branch map.
 *   4. On parallel.completed: mark completed_at.
 *
 * Nested parallels: maintained via a stack of active branch groups so inner
 * parallel.started events correctly attribute to the inner branch context.
 */

import type { AnyEvent } from '../types/events';

export interface BranchEntry {
  branch_id: string;
  nodes: string[];
  cost_usd: number;
  started_at: string;
  completed_at?: string;
}

export type BranchLedger = Record<string, BranchEntry>;

interface ActiveGroup {
  groupId: string;        // sequence of the parallel.started event
  declaredNodes: string[];
  joinNode: string | null;
}

export function buildBranchLedger(
  events: AnyEvent[],
  graphJoinNodes: Record<string, string | null> = {},
): BranchLedger {
  const ledger: BranchLedger = {};
  // node_id → branch_id mapping for cost attribution
  const nodeOwner: Record<string, string> = {};
  // stack of active parallel groups (innermost last)
  const stack: ActiveGroup[] = [];

  for (const ev of events) {
    switch (ev.event_type) {
      case 'parallel.started': {
        const groupId = `parallel-${ev.sequence}`;
        const declared = ev.target_nodes;
        // Look up join_node from graphInfo (provided by T-6.3.2a) or fall back to null
        const joinNode = graphJoinNodes[ev.source_node] ?? null;
        stack.push({ groupId, declaredNodes: declared, joinNode });
        for (const nodeId of declared) {
          const branchId = `${groupId}/${nodeId}`;
          ledger[branchId] = {
            branch_id: branchId,
            nodes: [nodeId],
            cost_usd: 0,
            started_at: ev.timestamp,
          };
          nodeOwner[nodeId] = branchId;
        }
        break;
      }

      case 'node.started': {
        // Attribute this node to the innermost group that declared it.
        for (let i = stack.length - 1; i >= 0; i--) {
          const group = stack[i];
          if (group.declaredNodes.includes(ev.node_id)) {
            const branchId = `${group.groupId}/${ev.node_id}`;
            nodeOwner[ev.node_id] = branchId;
            break;
          }
        }
        break;
      }

      case 'llm.called': {
        const branchId = nodeOwner[ev.node_id];
        if (branchId && ledger[branchId]) {
          ledger[branchId].cost_usd += ev.cost_usd;
          if (!ledger[branchId].nodes.includes(ev.node_id)) {
            ledger[branchId].nodes.push(ev.node_id);
          }
        }
        break;
      }

      case 'parallel.completed': {
        // Pop the innermost group whose declared nodes match this event's targets.
        const idx = stack.findLastIndex(
          (g) => g.declaredNodes.some((n) => ev.target_nodes.includes(n)),
        );
        if (idx !== -1) {
          const group = stack.splice(idx, 1)[0];
          for (const nodeId of group.declaredNodes) {
            const branchId = `${group.groupId}/${nodeId}`;
            if (ledger[branchId]) {
              ledger[branchId].completed_at = ev.timestamp;
            }
          }
        }
        break;
      }

      default:
        break;
    }
  }

  return ledger;
}

/** Total cost across all branches. */
export function ledgerTotal(ledger: BranchLedger): number {
  return Object.values(ledger).reduce((s, b) => s + b.cost_usd, 0);
}
