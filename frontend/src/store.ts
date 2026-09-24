import { create } from 'zustand';
import { DEFAULT_LOD_LEVEL } from './rankLod';

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
  /** LOD aggressiveness step 1…LOD_STEP_COUNT (1 = sparse, mid = balanced, max = dense). */
  lodLevel: number;
  viewState: ViewState;
  setDatasetSlug: (datasetSlug: string | null) => void;
  setLodLevel: (lodLevel: number) => void;
  setViewState: (viewState: ViewState) => void;
};

export const useAppStore = create<AppState>((set) => ({
  apiBase: import.meta.env.VITE_API_BASE ?? '/api',
  datasetSlug: null,
  lodLevel: DEFAULT_LOD_LEVEL,
  viewState: {
    longitude: -3.9,
    latitude: -2.8,
    zoom: 3,
    pitch: 0,
    bearing: 0
  },
  setDatasetSlug: (datasetSlug) => set({ datasetSlug }),
  setLodLevel: (lodLevel) => set({ lodLevel }),
  setViewState: (viewState) => set({ viewState })
}));
