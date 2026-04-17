import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider } from 'react-router';
import { ReactFlowProvider } from '@xyflow/react';
import { QueryClientProvider } from '@tanstack/react-query';

// Fonts — load before styles so @theme font-family resolves cleanly.
import '@fontsource-variable/inter/index.css';
import '@fontsource/jetbrains-mono/400.css';
import '@fontsource/jetbrains-mono/600.css';

import './styles/tokens.css';
import { router } from './router';
import { queryClient } from './lib/queryClient';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ReactFlowProvider>
        <RouterProvider router={router} />
      </ReactFlowProvider>
    </QueryClientProvider>
  </StrictMode>,
);
