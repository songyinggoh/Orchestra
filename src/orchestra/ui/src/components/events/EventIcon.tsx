/**
 * Maps every EventType → { icon: LucideIcon, colorClass: string }.
 *
 * The `satisfies` guard ensures a compile error if a new EventType is added
 * to the union but this map is not updated.
 */

import {
  Play,
  CheckCircle2,
  GitBranch,
  Circle,
  Check,
  Save,
  AlertTriangle,
  Sparkles,
  Wrench,
  ArrowRight,
  GitMerge,
  PauseCircle,
  PlayCircle,
  Bookmark,
  ShieldAlert,
  Lock,
  XCircle,
  ArrowRightLeft,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { EventType } from '../../types/events';

export interface EventIconConfig {
  icon: LucideIcon;
  /** Tailwind text-color class — maps to the CSS variable color tokens. */
  colorClass: string;
}

const EVENT_ICON_MAP = {
  'execution.started':               { icon: Play,            colorClass: 'text-[var(--status-info)]' },
  'execution.completed':             { icon: CheckCircle2,    colorClass: 'text-[var(--status-ok)]' },
  'execution.forked':                { icon: GitBranch,       colorClass: 'text-[var(--tag-handoff)]' },
  'node.started':                    { icon: Circle,          colorClass: 'text-[var(--status-run)]' },
  'node.completed':                  { icon: Check,           colorClass: 'text-[var(--status-ok)]' },
  'state.updated':                   { icon: Save,            colorClass: 'text-[var(--text-2)]' },
  'error.occurred':                  { icon: AlertTriangle,   colorClass: 'text-[var(--status-err)]' },
  'llm.called':                      { icon: Sparkles,        colorClass: 'text-[var(--tag-llm)]' },
  'tool.called':                     { icon: Wrench,          colorClass: 'text-[var(--tag-tool)]' },
  'edge.traversed':                  { icon: ArrowRight,      colorClass: 'text-[var(--text-3)]' },
  'parallel.started':                { icon: GitMerge,        colorClass: 'text-[var(--status-info)]' },
  'parallel.completed':              { icon: GitMerge,        colorClass: 'text-[var(--status-info)]' },
  'interrupt.requested':             { icon: PauseCircle,     colorClass: 'text-[var(--status-warn)]' },
  'interrupt.resumed':               { icon: PlayCircle,      colorClass: 'text-[var(--status-info)]' },
  'checkpoint.created':              { icon: Bookmark,        colorClass: 'text-[var(--accent)]' },
  'security.violation':              { icon: ShieldAlert,     colorClass: 'text-[var(--status-sec)]' },
  'security.restricted_mode_entered':{ icon: Lock,            colorClass: 'text-[var(--status-sec)]' },
  'input.rejected':                  { icon: XCircle,         colorClass: 'text-[var(--status-sec)]' },
  'output.rejected':                 { icon: XCircle,         colorClass: 'text-[var(--status-sec)]' },
  'handoff.initiated':               { icon: ArrowRightLeft,  colorClass: 'text-[var(--tag-handoff)]' },
  'handoff.completed':               { icon: Check,           colorClass: 'text-[var(--tag-handoff)]' },
} satisfies Record<EventType, EventIconConfig>;

export function getEventIconConfig(eventType: EventType): EventIconConfig {
  return EVENT_ICON_MAP[eventType];
}

interface EventIconProps {
  eventType: EventType;
  size?: number;
  className?: string;
}

export function EventIcon({ eventType, size = 14, className }: EventIconProps) {
  const { icon: Icon, colorClass } = EVENT_ICON_MAP[eventType];
  return <Icon size={size} className={`${colorClass}${className ? ` ${className}` : ''}`} />;
}
