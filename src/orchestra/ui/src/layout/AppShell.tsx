import { useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router';
import { TooltipProvider } from '@/components/ui/tooltip';
import { Toaster } from '@/components/ui/sonner';
import { NavRail } from './NavRail';
import { RunsSidebar } from './RunsSidebar';
import { ShortcutHelpDialog } from '../components/shortcuts/ShortcutHelpDialog';
import { registerShortcut, useGlobalShortcutListener } from '../lib/shortcuts';

/** Routes that show the runs sidebar in the left pane. */
const SIDEBAR_ROUTES = ['/runs', '/'];

function GlobalShortcuts({ onHelp }: { onHelp: () => void }) {
  const navigate = useNavigate();
  // Register all 10 UI-SPEC §11 shortcuts once on mount.
  registerShortcut({ id: 'help', keys: ['?'], scope: 'global', label: 'Show keyboard shortcuts', handler: onHelp });
  registerShortcut({ id: 'nav-runs', keys: ['g', 'r'], sequence: true, scope: 'global', label: 'Go to Runs', handler: () => navigate('/runs') });
  registerShortcut({ id: 'nav-cost', keys: ['g', 'c'], sequence: true, scope: 'global', label: 'Go to Cost', handler: () => navigate('/cost') });
  registerShortcut({ id: 'nav-settings', keys: ['g', 's'], sequence: true, scope: 'global', label: 'Go to Settings', handler: () => navigate('/settings') });
  registerShortcut({ id: 'search', keys: ['/'], scope: 'run-list', label: 'Focus search', handler: () => { (document.querySelector('[aria-label="Search runs"]') as HTMLElement)?.focus(); } });
  registerShortcut({ id: 'prev-event', keys: ['['], scope: 'run-detail', label: 'Previous event', handler: () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true })) });
  registerShortcut({ id: 'next-event', keys: [']'], scope: 'run-detail', label: 'Next event', handler: () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })) });
  registerShortcut({ id: 'jump-latest', keys: ['.'], scope: 'run-detail', label: 'Jump to latest', handler: () => {} });
  registerShortcut({ id: 'time-travel', keys: [','], scope: 'run-detail', label: 'Enter time-travel mode', handler: () => {} });
  registerShortcut({ id: 'fork', keys: ['f'], scope: 'run-detail', label: 'Fork from here', handler: () => {} });
  useGlobalShortcutListener();
  return null;
}

export function AppShell() {
  const { pathname } = useLocation();
  const showSidebar = SIDEBAR_ROUTES.some((r) => pathname === r || pathname.startsWith('/runs'));
  const [helpOpen, setHelpOpen] = useState(false);

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex h-screen w-screen overflow-hidden bg-zinc-950 text-zinc-100">
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-violet-600 focus:px-3 focus:py-1 focus:text-white"
        >
          Skip to main content
        </a>

        <GlobalShortcuts onHelp={() => setHelpOpen(true)} />
        <NavRail />
        {showSidebar && <RunsSidebar />}

        <main id="main-content" className="flex min-w-0 flex-1 flex-col overflow-hidden" tabIndex={-1}>
          <Outlet />
        </main>
      </div>

      <ShortcutHelpDialog open={helpOpen} onOpenChange={setHelpOpen} />
      <Toaster position="bottom-right" theme="dark" />
    </TooltipProvider>
  );
}
