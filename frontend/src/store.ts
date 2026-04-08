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
  tileLimit: number;
  viewState: ViewState;
  setRankMax: (rankMax: number) => void;
  setTileLimit: (tileLimit: number) => void;
  setViewState: (viewState: ViewState) => void;
};

export const useAppStore = create<AppState>((set) => ({
  apiBase: 'http://localhost:8000',
  rankMax: 3,
  tileLimit: 50000,
  viewState: {
    longitude: 10,
    latitude: 50,
    zoom: 4,
    pitch: 0,
    bearing: 0
  },
  setRankMax: (rankMax) => set({ rankMax }),
  setTileLimit: (tileLimit) => set({ tileLimit }),
  setViewState: (viewState) => set({ viewState })
}));

