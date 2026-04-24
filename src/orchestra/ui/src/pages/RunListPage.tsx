import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { NewRunDialog } from '../components/run/NewRunDialog';

export function RunListPage() {
  const [newRunOpen, setNewRunOpen] = useState(false);

  return (
    <>
      <div className="flex h-full flex-col">
        <header className="flex items-center justify-between border-b border-zinc-800 px-6 py-4">
          <h1 className="text-base font-semibold text-zinc-100">Runs</h1>
          <Button
            size="sm"
            className="bg-violet-500 text-white hover:bg-violet-400"
            onClick={() => setNewRunOpen(true)}
          >
            Start a run
          </Button>
        </header>
        <div className="flex flex-1 items-center justify-center">
          <p className="text-sm text-zinc-500">Select a run from the sidebar</p>
        </div>
      </div>
      <NewRunDialog open={newRunOpen} onOpenChange={setNewRunOpen} />
    </>
  );
}
