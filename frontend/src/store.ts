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
  datasetSlug: string | null;
  rankCap: number;
  zoomLodAggressiveness: number;
  viewState: ViewState;
  setDatasetSlug: (datasetSlug: string | null) => void;
  setRankCap: (rankCap: number) => void;
  setZoomLodAggressiveness: (zoomLodAggressiveness: number) => void;
  setViewState: (viewState: ViewState) => void;
};

export const useAppStore = create<AppState>((set) => ({
  apiBase: 'http://localhost:8000',
  datasetSlug: null,
  rankCap: 1_000_000,
  zoomLodAggressiveness: 50,
  viewState: {
    longitude: -3.9,
    latitude: -2.8,
    zoom: 3,
    pitch: 0,
    bearing: 0
  },
  setDatasetSlug: (datasetSlug) => set({ datasetSlug }),
  setRankCap: (rankCap) => set({ rankCap }),
  setZoomLodAggressiveness: (zoomLodAggressiveness) => set({ zoomLodAggressiveness }),
  setViewState: (viewState) => set({ viewState })
}));
