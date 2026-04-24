import { ShieldAlert } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import type { AnyEvent } from '../../types/events';

interface SecurityChipProps {
  event: AnyEvent;
}

function getChipLabel(event: AnyEvent): string {
  switch (event.event_type) {
    case 'security.violation':           return event.violation_type;
    case 'security.restricted_mode_entered': return 'restricted';
    case 'input.rejected':               return event.guardrail;
    case 'output.rejected':              return event.contract_name;
    default:                             return 'security';
  }
}

function getTooltipContent(event: AnyEvent): string {
  switch (event.event_type) {
    case 'security.violation':
      return `${event.violation_type}: ${event.details}`;
    case 'security.restricted_mode_entered':
      return `Risk ${event.risk_score.toFixed(2)} · ${event.trigger}`;
    case 'input.rejected':
      return `${event.guardrail}: ${event.violation_messages.join('; ')}`;
    case 'output.rejected':
      return `${event.contract_name}: ${event.validation_errors.join('; ')}`;
    default:
      return '';
  }
}

export function SecurityChip({ event }: SecurityChipProps) {
  const label = getChipLabel(event);
  const tooltip = getTooltipContent(event);

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge
          variant="outline"
          className="gap-1 border-pink-500/50 bg-pink-500/10 px-1.5 py-0 text-[10px] text-pink-400 hover:bg-pink-500/20"
        >
          <ShieldAlert size={10} />
          {label}
        </Badge>
      </TooltipTrigger>
      {tooltip && (
        <TooltipContent side="left" className="max-w-xs text-xs">
          {tooltip}
        </TooltipContent>
      )}
    </Tooltip>
  );
}
