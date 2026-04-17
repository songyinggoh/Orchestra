import { describe, it, expect } from 'vitest';
import { getEventIconConfig } from './EventIcon';
import type { EventType } from '../../types/events';

const ALL_EVENT_TYPES: EventType[] = [
  'execution.started', 'execution.completed', 'execution.forked',
  'node.started', 'node.completed', 'state.updated', 'error.occurred',
  'llm.called', 'tool.called', 'edge.traversed',
  'parallel.started', 'parallel.completed',
  'interrupt.requested', 'interrupt.resumed', 'checkpoint.created',
  'security.violation', 'security.restricted_mode_entered',
  'input.rejected', 'output.rejected',
  'handoff.initiated', 'handoff.completed',
];

describe('EventIcon', () => {
  it('covers all 21 event types with a non-null icon and non-empty colorClass', () => {
    expect(ALL_EVENT_TYPES).toHaveLength(21);
    for (const type of ALL_EVENT_TYPES) {
      const config = getEventIconConfig(type);
      expect(config.icon, `icon missing for ${type}`).toBeTruthy();
      expect(config.colorClass, `colorClass missing for ${type}`).not.toBe('');
    }
  });

  it('returns unique icons for security vs non-security events (spot-check)', () => {
    const violation = getEventIconConfig('security.violation');
    const started = getEventIconConfig('execution.started');
    expect(violation.icon).not.toBe(started.icon);
  });
});
