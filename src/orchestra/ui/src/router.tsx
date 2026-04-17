import { createBrowserRouter, Navigate } from 'react-router';
import { AppShell } from './layout/AppShell';
import { RunListPage } from './pages/RunListPage';
import { RunDetailPage } from './pages/RunDetailPage';
import { GraphsListPage } from './pages/GraphsListPage';
import { GraphDetailPage } from './pages/GraphDetailPage';
import { CostDashboardPage } from './pages/CostDashboardPage';
import { SettingsPage } from './pages/SettingsPage';
import { NotFoundPage } from './pages/NotFoundPage';

export const router = createBrowserRouter(
  [
    {
      path: '/',
      element: <AppShell />,
      children: [
        { index: true, element: <Navigate to="/runs" replace /> },
        { path: 'runs', element: <RunListPage /> },
        { path: 'runs/:runId', element: <RunDetailPage /> },
        // W2 will consume the sequence param; W1 stubs it via useUIStore.
        { path: 'runs/:runId/@:sequence', element: <RunDetailPage /> },
        { path: 'runs/:runId/security', element: <RunDetailPage securityFilter /> },
        { path: 'runs/:runId/cost', element: <RunDetailPage costTab /> },
        { path: 'graphs', element: <GraphsListPage /> },
        { path: 'graphs/:name', element: <GraphDetailPage /> },
        { path: 'settings', element: <SettingsPage /> },
        { path: '*', element: <NotFoundPage /> },
      ],
    },
  ],
  { basename: '/ui' },
);
