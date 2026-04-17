import { useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useAuthStore } from '../stores/useAuthStore';

export function SettingsPage() {
  const apiKey = useAuthStore((s) => s.apiKey);
  const setApiKey = useAuthStore((s) => s.setApiKey);
  const [draft, setDraft] = useState(apiKey ?? '');

  function handleSave() {
    const trimmed = draft.trim();
    setApiKey(trimmed || null);
    toast.success(trimmed ? 'API key saved' : 'API key cleared');
  }

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-zinc-800 px-6 py-4">
        <h1 className="text-base font-semibold text-zinc-100">Settings</h1>
      </header>
      <div className="flex-1 overflow-y-auto px-6 py-6">
        <section className="max-w-md space-y-4">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-500">
            Authentication
          </h2>
          <div className="space-y-2">
            <Label htmlFor="api-key">Orchestra API key</Label>
            <Input
              id="api-key"
              type="password"
              placeholder="Leave blank for unauthenticated (dev mode)"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="font-mono"
              autoComplete="off"
            />
            <p className="text-xs text-zinc-500">
              Set when <code>ORCHESTRA_SERVER_KEY</code> is configured on the server.
            </p>
          </div>
          <Button onClick={handleSave}>Save</Button>
        </section>
      </div>
    </div>
  );
}
