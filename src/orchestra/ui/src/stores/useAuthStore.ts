/**
 * Auth store — persists API key in localStorage under the same key used
 * by the legacy auth.ts helper ('orchestra_api_key') so existing tokens
 * survive the migration.
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

interface AuthState {
  apiKey: string | null;
  setApiKey: (key: string | null) => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      apiKey: null,
      setApiKey: (key) => set({ apiKey: key }),
    }),
    {
      name: 'orchestra_api_key',
      storage: createJSONStorage(() => localStorage),
      // Only persist the key, not derived state.
      partialize: (state) => ({ apiKey: state.apiKey }),
    },
  ),
);
