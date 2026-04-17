import { Outlet, useLocation } from 'react-router';
import { TooltipProvider } from '@/components/ui/tooltip';
import { Toaster } from '@/components/ui/sonner';
import { NavRail } from './NavRail';
import { RunsSidebar } from './RunsSidebar';

/** Routes that show the runs sidebar in the left pane. */
const SIDEBAR_ROUTES = ['/runs', '/'];

export function AppShell() {
  const { pathname } = useLocation();
  const showSidebar = SIDEBAR_ROUTES.some((r) => pathname === r || pathname.startsWith('/runs'));

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex h-screen w-screen overflow-hidden bg-zinc-950 text-zinc-100">
        {/* Skip link for keyboard/screen-reader users */}
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-violet-600 focus:px-3 focus:py-1 focus:text-white"
        >
          Skip to main content
        </a>

        <NavRail />

        {showSidebar && <RunsSidebar />}

        <main
          id="main-content"
          className="flex min-w-0 flex-1 flex-col overflow-hidden"
          tabIndex={-1}
        >
          <Outlet />
        </main>
      </div>

      <Toaster position="bottom-right" theme="dark" />
    </TooltipProvider>
  );
}
