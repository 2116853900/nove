import { create } from "zustand";

type SaveState = "saving" | "saved" | "offline" | "error";

interface WorkspaceState {
  leftOpen: boolean;
  rightOpen: boolean;
  rightTab: string;
  focusMode: boolean;
  chapterLabel?: string;
  saveState: SaveState;
  setLeftOpen: (open: boolean) => void;
  setRightOpen: (open: boolean) => void;
  setRightTab: (tab: string) => void;
  toggleFocusMode: () => void;
  setChapterLabel: (label?: string) => void;
  setSaveState: (state: SaveState) => void;
  resetChrome: () => void;
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  leftOpen: true,
  rightOpen: true,
  rightTab: "ai",
  focusMode: false,
  chapterLabel: undefined,
  saveState: "saved",
  setLeftOpen: (leftOpen) => set({ leftOpen }),
  setRightOpen: (rightOpen) => set({ rightOpen }),
  setRightTab: (rightTab) => set({ rightTab }),
  toggleFocusMode: () => set((state) => ({ focusMode: !state.focusMode })),
  setChapterLabel: (chapterLabel) => set({ chapterLabel }),
  setSaveState: (saveState) => set({ saveState }),
  resetChrome: () => set({ chapterLabel: undefined, saveState: "saved", focusMode: false }),
}));
