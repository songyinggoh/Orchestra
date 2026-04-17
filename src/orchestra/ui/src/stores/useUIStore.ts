/**
 * Global UI state — router-independent, shared across pages.
 * Timeline filter, panel visibility, command-palette toggle.
 */

import { create } from 'zustand';

export type TimelineFilter =
  | { type: 'all' }
  | { type: 'security' }
  | { type: 'node'; nodeId: string };

export interface PanelVisibility {
  sidebar: boolean;
  stateViewer: boolean;
}

interface UIState {
  /** Sequence number pinned by the scrubber (null = live / latest). W2 consumes this. */
  selectedSequence: number | null;
  panelVisibility: PanelVisibility;
  timelineFilter: TimelineFilter;
  /** Right-pane tab in RunDetailShell */
  rightPaneTab: 'timeline' | 'state' | 'cost' | 'security';
  cmdKOpen: boolean;

  // Actions
  setSelectedSequence: (seq: number | null) => void;
  setPanelVisibility: (patch: Partial<PanelVisibility>) => void;
  setTimelineFilter: (filter: TimelineFilter) => void;
  setRightPaneTab: (tab: UIState['rightPaneTab']) => void;
  setCmdKOpen: (open: boolean) => void;
}

export const useUIStore = create<UIState>()((set) => ({
  selectedSequence: null,
  panelVisibility: { sidebar: true, stateViewer: false },
  timelineFilter: { type: 'all' },
  rightPaneTab: 'timeline',
  cmdKOpen: false,

  setSelectedSequence: (seq) => set({ selectedSequence: seq }),
  setPanelVisibility: (patch) =>
    set((s) => ({ panelVisibility: { ...s.panelVisibility, ...patch } })),
  setTimelineFilter: (filter) => set({ timelineFilter: filter }),
  setRightPaneTab: (tab) => set({ rightPaneTab: tab }),
  setCmdKOpen: (open) => set({ cmdKOpen: open }),
}));
