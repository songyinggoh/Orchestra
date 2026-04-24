import { NavLink } from 'react-router';
import { List, Share2, Coins, Settings } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

const NAV_ITEMS = [
  { to: '/runs', icon: List, label: 'Runs' },
  { to: '/graphs', icon: Share2, label: 'Graphs' },
  { to: '/cost', icon: Coins, label: 'Cost' },
  { to: '/settings', icon: Settings, label: 'Settings' },
] as const;

export function NavRail() {
  return (
    <nav
      className="flex h-full w-14 flex-col items-center border-r border-zinc-800 bg-zinc-950 py-3"
      aria-label="Main navigation"
    >
      {/* Wordmark */}
      <div className="mb-4 flex h-8 w-8 items-center justify-center rounded-md bg-violet-600 text-xs font-bold text-white select-none">
        O
      </div>

      <div className="flex flex-1 flex-col items-center gap-1">
        {NAV_ITEMS.map(({ to, icon: Icon, label }) => (
          <Tooltip key={to}>
            <TooltipTrigger asChild>
              <NavLink
                to={to}
                className={({ isActive }) =>
                  cn(
                    'relative flex h-10 w-10 items-center justify-center rounded-md text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500',
                    isActive && 'text-zinc-100 before:absolute before:left-0 before:-ml-2 before:h-6 before:w-0.5 before:rounded-r-full before:bg-violet-500',
                  )
                }
                aria-label={label}
              >
                <Icon size={18} />
              </NavLink>
            </TooltipTrigger>
            <TooltipContent side="right">{label}</TooltipContent>
          </Tooltip>
        ))}
      </div>
    </nav>
  );
}
