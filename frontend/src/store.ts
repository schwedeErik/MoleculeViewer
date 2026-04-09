import { create } from 'zustand';

type ViewState = {
  longitude: number;
  latitude: number;
  zoom: number;
  pitch: number;
  bearing: number;
};

type AppState = {
  apiBase: string;
  rankMax: number;
  viewLimit: number;
  viewState: ViewState;
  setRankMax: (rankMax: number) => void;
  setViewLimit: (viewLimit: number) => void;
  setViewState: (viewState: ViewState) => void;
};

export const useAppStore = create<AppState>((set) => ({
  apiBase: 'http://localhost:8000',
  rankMax: 3,
  viewLimit: 50000,
  viewState: {
    longitude: 10,
    latitude: 50,
    zoom: 4,
    pitch: 0,
    bearing: 0
  },
  setRankMax: (rankMax) => set({ rankMax }),
  setViewLimit: (viewLimit) => set({ viewLimit }),
  setViewState: (viewState) => set({ viewState })
}));

