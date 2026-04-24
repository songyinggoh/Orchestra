import { useState } from 'react';
import { useSearchParams } from 'react-router';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

const STORAGE_KEY = 'orchestra.savedViews';

interface SavedView { name: string; params: string }

function load(): SavedView[] {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]'); } catch { return []; }
}
function save(views: SavedView[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(views));
}

export function SavedViews() {
  const [params, setParams] = useSearchParams();
  const [views, setViews] = useState<SavedView[]>(load);

  function saveCurrentView() {
    const name = window.prompt('View name:');
    if (!name?.trim()) return;
    const updated = [...views.filter((v) => v.name !== name.trim()), { name: name.trim(), params: params.toString() }];
    save(updated);
    setViews(updated);
  }

  function applyView(v: SavedView) {
    setParams(new URLSearchParams(v.params), { replace: true });
  }

  function deleteView(name: string) {
    const updated = views.filter((v) => v.name !== name);
    save(updated);
    setViews(updated);
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="h-7 text-xs">
          Saved views {views.length > 0 && `(${views.length})`}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        <DropdownMenuItem onClick={saveCurrentView} className="text-xs">
          Save current view…
        </DropdownMenuItem>
        {views.length > 0 && <DropdownMenuSeparator />}
        {views.map((v) => (
          <div key={v.name} className="flex items-center justify-between px-2 py-1">
            <button className="flex-1 text-left text-xs hover:text-violet-400" onClick={() => applyView(v)}>
              {v.name}
            </button>
            <button className="ml-2 text-[10px] text-zinc-500 hover:text-red-400" onClick={() => deleteView(v.name)}>
              ✕
            </button>
          </div>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
