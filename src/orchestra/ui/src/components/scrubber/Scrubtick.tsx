/**
 * Single tick on the scrubber track — colored per event type, with a few
 * special-case glyphs:
 *  - checkpoint.created       → rotated square (diamond)
 *  - security.* / *.rejected  → 2x-height pink bar
 *  - everything else          → thin vertical bar using the event-icon color
 */

import type { EventType } from '../../types/events';
import { getEventIconConfig } from '../events/EventIcon';

interface ScrubtickProps {
  eventType: EventType;
  sequence: number;
  xPercent: number;
  isSelected: boolean;
}

const SECURITY_TYPES: ReadonlySet<EventType> = new Set<EventType>([
  'security.violation',
  'security.restricted_mode_entered',
  'input.rejected',
  'output.rejected',
]);

export function Scrubtick({
  eventType,
  sequence,
  xPercent,
  isSelected,
}: ScrubtickProps) {
  const { colorClass } = getEventIconConfig(eventType);
  const isCheckpoint = eventType === 'checkpoint.created';
  const isSecurity = SECURITY_TYPES.has(eventType);

  const ringClass = isSelected ? 'ring-1 ring-[var(--accent)]' : '';

  if (isCheckpoint) {
    return (
      <div
        aria-label={`event ${sequence} checkpoint`}
        className={`pointer-events-none absolute top-1/2 ${colorClass} ${ringClass}`}
        style={{
          left: `calc(${xPercent}% - 4px)`,
          width: 8,
          height: 8,
          transform: 'translateY(-50%) rotate(45deg)',
          backgroundColor: 'currentColor',
        }}
      />
    );
  }

  const height = isSecurity ? 16 : 8;

  return (
    <div
      aria-label={`event ${sequence} ${eventType}`}
      className={`pointer-events-none absolute top-1/2 ${colorClass} ${ringClass}`}
      style={{
        left: `calc(${xPercent}% - 1px)`,
        width: 2,
        height,
        transform: 'translateY(-50%)',
        backgroundColor: 'currentColor',
        opacity: isSelected ? 1 : 0.8,
      }}
    />
  );
}
