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
  viewLimit: number;
  viewState: ViewState;
  setViewLimit: (viewLimit: number) => void;
  setViewState: (viewState: ViewState) => void;
};

export const useAppStore = create<AppState>((set) => ({
  apiBase: 'http://localhost:8000',
  viewLimit: 1000,
  viewState: {
    longitude: -3.9,
    latitude: -2.8,
    zoom: 3,
    pitch: 0,
    bearing: 0
  },
  setViewLimit: (viewLimit) => set({ viewLimit }),
  setViewState: (viewState) => set({ viewState })
}));
