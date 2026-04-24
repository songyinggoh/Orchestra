import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { SavedViews } from './SavedViews';

const STORAGE_KEY = 'orchestra.savedViews';

function Wrapper({ children }: { children: React.ReactNode }) {
  return <MemoryRouter initialEntries={['/?q=hello']}>{children}</MemoryRouter>;
}

beforeEach(() => {
  localStorage.removeItem(STORAGE_KEY);
});

describe('SavedViews', () => {
  it('renders "Saved views" button', () => {
    render(<SavedViews />, { wrapper: Wrapper });
    expect(screen.getByRole('button', { name: /saved views/i })).toBeInTheDocument();
  });

  it('saves a view to localStorage when prompted with a name', async () => {
    const user = userEvent.setup();
    vi.spyOn(window, 'prompt').mockReturnValue('my-view');

    render(<SavedViews />, { wrapper: Wrapper });
    await user.click(screen.getByRole('button', { name: /saved views/i }));

    await waitFor(() => screen.getByText(/save current view/i));
    await user.click(screen.getByText(/save current view/i));

    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]');
    expect(stored).toHaveLength(1);
    expect(stored[0].name).toBe('my-view');

    vi.restoreAllMocks();
  });

  it('does not save when prompt is cancelled', async () => {
    const user = userEvent.setup();
    vi.spyOn(window, 'prompt').mockReturnValue(null);

    render(<SavedViews />, { wrapper: Wrapper });
    await user.click(screen.getByRole('button', { name: /saved views/i }));
    await waitFor(() => screen.getByText(/save current view/i));
    await user.click(screen.getByText(/save current view/i));

    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]');
    expect(stored).toHaveLength(0);

    vi.restoreAllMocks();
  });

  it('shows count from localStorage on mount (survives reload)', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([{ name: 'persisted', params: 'q=old' }]));
    render(<SavedViews />, { wrapper: Wrapper });
    expect(screen.getByRole('button', { name: /saved views.*1/i })).toBeInTheDocument();
  });

  it('deletes a view and removes it from localStorage', async () => {
    const user = userEvent.setup();
    localStorage.setItem(STORAGE_KEY, JSON.stringify([{ name: 'to-delete', params: '' }]));

    render(<SavedViews />, { wrapper: Wrapper });
    await user.click(screen.getByRole('button', { name: /saved views/i }));

    // Wait for dropdown content (rendered in Radix portal).
    await waitFor(() => screen.getByText('to-delete'));
    await user.click(screen.getByRole('button', { name: '✕' }));

    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]');
    expect(stored).toHaveLength(0);
  });
});
