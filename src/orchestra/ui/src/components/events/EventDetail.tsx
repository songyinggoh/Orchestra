/**
 * Renders the detail string for a timeline row.
 * Dispatches on event_type — no `any` access, fully typed.
 */

import type { AnyEvent } from '../../types/events';

function fmt(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`;
}

function truncate(s: string, len = 60): string {
  return s.length > len ? `${s.slice(0, len)}…` : s;
}

export function EventDetail({ event }: { event: AnyEvent }) {
  switch (event.event_type) {
    case 'execution.started':
      return <span>{event.workflow_name} · entry: {event.entry_point}</span>;

    case 'execution.completed':
      return (
        <span>
          {event.status} · {fmt(event.duration_ms)} · {event.total_tokens.toLocaleString()} tok ·
          ${event.total_cost_usd.toFixed(4)}
        </span>
      );

    case 'execution.forked':
      return (
        <span>
          from <span className="font-mono">{event.parent_run_id.slice(0, 8)}</span> ·
          seq {event.fork_point_sequence} →{' '}
          <span className="font-mono">{event.new_run_id.slice(0, 8)}</span>
        </span>
      );

    case 'node.started':
      return <span>{event.node_id} · {event.node_type}</span>;

    case 'node.completed':
      return <span>{event.node_id} · {fmt(event.duration_ms)}</span>;

    case 'state.updated': {
      const keys = Object.keys(event.field_updates);
      return <span>{keys.length} field{keys.length !== 1 ? 's' : ''}: {keys.join(', ')}</span>;
    }

    case 'error.occurred':
      return (
        <span>
          {event.node_id} · {event.error_type}: {truncate(event.error_message)}
        </span>
      );

    case 'llm.called':
      return (
        <span>
          {event.model} · {event.input_tokens + event.output_tokens} tok ·
          ${event.cost_usd.toFixed(4)} · {fmt(event.duration_ms)}
        </span>
      );

    case 'tool.called':
      return (
        <span>
          {event.tool_name} · {fmt(event.duration_ms)}
          {event.error && <span className="text-[var(--status-err)]"> · error</span>}
        </span>
      );

    case 'edge.traversed':
      return (
        <span>
          {event.from_node} → {event.to_node}
          {event.condition_result != null && ` · "${event.condition_result}"`}
        </span>
      );

    case 'parallel.started':
      return <span>{event.source_node} → [{event.target_nodes.join(', ')}]</span>;

    case 'parallel.completed':
      return (
        <span>
          {event.target_nodes.length} branches · {fmt(event.duration_ms)}
        </span>
      );

    case 'interrupt.requested':
      return <span>{event.node_id} · {event.interrupt_type}</span>;

    case 'interrupt.resumed':
      return (
        <span>
          {event.node_id} ·{' '}
          {Object.keys(event.state_modifications).length} modification
          {Object.keys(event.state_modifications).length !== 1 ? 's' : ''}
        </span>
      );

    case 'checkpoint.created':
      return (
        <span>
          {event.node_id} · <span className="font-mono">{event.checkpoint_id.slice(0, 8)}</span>
        </span>
      );

    case 'security.violation':
      return (
        <span>
          {event.node_id} · {event.violation_type} · {truncate(event.details, 50)}
        </span>
      );

    case 'security.restricted_mode_entered':
      return (
        <span>
          {event.node_id} · risk {event.risk_score.toFixed(2)} · {event.trigger}
        </span>
      );

    case 'input.rejected':
      return (
        <span>
          {event.node_id} · {event.guardrail} · {event.violation_messages[0] ?? ''}
        </span>
      );

    case 'output.rejected':
      return (
        <span>
          {event.node_id} · {event.contract_name} · {event.validation_errors[0] ?? ''}
        </span>
      );

    case 'handoff.initiated':
      return <span>{event.from_agent} → {event.to_agent} · {event.reason}</span>;

    case 'handoff.completed':
      return <span>{event.from_agent} → {event.to_agent}</span>;

    default: {
      const _: never = event;
      void _;
      return null;
    }
  }
}
