/** @type {import('tailwindcss').Config} */
// Tailwind v4 primarily reads theme from @theme directives in tokens.css.
// This file exists for shadcn/ui CLI compatibility; runtime theme values
// live in src/styles/tokens.css (see UI-SPEC §4.1-§4.6).
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx,js,jsx}'],
  theme: {
    extend: {
      colors: {
        surface: {
          0: 'var(--surface-0)',
          1: 'var(--surface-1)',
          2: 'var(--surface-2)',
        },
        status: {
          ok: 'var(--status-ok)',
          run: 'var(--status-run)',
          err: 'var(--status-err)',
          warn: 'var(--status-warn)',
          info: 'var(--status-info)',
          sec: 'var(--status-sec)',
        },
        tag: {
          llm: 'var(--tag-llm)',
          tool: 'var(--tag-tool)',
          handoff: 'var(--tag-handoff)',
        },
        text: {
          1: 'var(--text-1)',
          2: 'var(--text-2)',
          3: 'var(--text-3)',
          inv: 'var(--text-inv)',
        },
        accent: {
          DEFAULT: 'var(--accent)',
          hover: 'var(--accent-hover)',
          foreground: 'var(--accent-foreground)',
        },
        cost: {
          0: 'var(--cost-0)',
          1: 'var(--cost-1)',
          2: 'var(--cost-2)',
          3: 'var(--cost-3)',
          4: 'var(--cost-4)',
          5: 'var(--cost-5)',
          6: 'var(--cost-6)',
          7: 'var(--cost-7)',
          8: 'var(--cost-8)',
        },
        // shadcn/ui semantic tokens (mapped to dark-theme values in tokens.css)
        background: 'var(--background)',
        foreground: 'var(--foreground)',
        card: {
          DEFAULT: 'var(--card)',
          foreground: 'var(--card-foreground)',
        },
        popover: {
          DEFAULT: 'var(--popover)',
          foreground: 'var(--popover-foreground)',
        },
        primary: {
          DEFAULT: 'var(--primary)',
          foreground: 'var(--primary-foreground)',
        },
        secondary: {
          DEFAULT: 'var(--secondary)',
          foreground: 'var(--secondary-foreground)',
        },
        muted: {
          DEFAULT: 'var(--muted)',
          foreground: 'var(--muted-foreground)',
        },
        destructive: {
          DEFAULT: 'var(--destructive)',
          foreground: 'var(--destructive-foreground)',
        },
        border: 'var(--border)',
        input: 'var(--input)',
        ring: 'var(--ring)',
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      fontFamily: {
        sans: [
          "'Inter Variable'",
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'BlinkMacSystemFont',
          'sans-serif',
        ],
        mono: [
          "'JetBrains Mono'",
          'ui-monospace',
          'SFMono-Regular',
          'Menlo',
          'Monaco',
          'Consolas',
          'monospace',
        ],
      },
      fontSize: {
        // UI-SPEC §5.1: four-size system (body 14, label 12, heading 20, display 28)
        body: ['14px', { lineHeight: '1.5' }],
        label: ['12px', { lineHeight: '1.4', letterSpacing: '0.02em' }],
        heading: ['20px', { lineHeight: '1.2', letterSpacing: '-0.01em' }],
        display: ['28px', { lineHeight: '1.2', letterSpacing: '-0.015em' }],
      },
    },
  },
  plugins: [],
};
