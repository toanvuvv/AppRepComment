import { create } from "zustand";

interface ViewAsState {
  viewAsUserId: number | null;
  setViewAsUserId: (id: number | null) => void;
}

export const useViewAsStore = create<ViewAsState>((set) => ({
  viewAsUserId: null,
  setViewAsUserId: (id) => set({ viewAsUserId: id }),
}));

// Module-level mirror so non-React code (axios interceptors, SSE URL builder)
// can read the value synchronously without subscribing.
let _viewAsUserId: number | null = null;
useViewAsStore.subscribe((state) => {
  _viewAsUserId = state.viewAsUserId;
});

export function getViewAsUserId(): number | null {
  return _viewAsUserId;
}
