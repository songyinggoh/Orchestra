import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

// Fonts — load before styles so @theme font-family resolves cleanly.
import '@fontsource-variable/inter/index.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/600.css'

import './styles/tokens.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
