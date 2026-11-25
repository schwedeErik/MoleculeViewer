import type { DatasetInfo } from './types';
import bundledDatasets from './staticDatasets.json';

/** Static GitHub Pages build has no FastAPI backend. */
export const isStatic = import.meta.env.VITE_STATIC === 'true';

/** Vite base URL, always ends with `/` (e.g. `/` or `/MoleculeViewer/`). */
export const assetBase = import.meta.env.BASE_URL;

/** Backend API prefix (dev/proxy or full URL). Empty in static mode. */
export const apiBase = isStatic
  ? ''
  : ((import.meta.env.VITE_API_BASE as string | undefined) ?? '/api');

/** Absolute URL for a Deepscatter / quadfeather tile tree. */
export function deepscatterTilesUrl(slug: string, order: string): string {
  if (isStatic) {
    return `${window.location.origin}${assetBase}deepscatter/${encodeURIComponent(slug)}/${order}`;
  }
  const path = `${apiBase}/deepscatter/${encodeURIComponent(slug)}/${order}`;
  if (path.startsWith('http://') || path.startsWith('https://')) return path;
  return `${window.location.origin}${path.startsWith('/') ? '' : '/'}${path}`;
}

/** Catalog of datasets (bundled in static mode, otherwise live API). */
export function datasetsUrl(): string {
  if (isStatic) return `${assetBase}datasets.json`;
  return `${apiBase}/datasets`;
}

/** Load dataset catalog; static builds use the bundled list (no stale fetch). */
export async function loadDatasetsCatalog(signal?: AbortSignal): Promise<DatasetInfo[]> {
  if (isStatic) return bundledDatasets as DatasetInfo[];
  const res = await fetch(datasetsUrl(), signal ? { signal } : undefined);
  if (!res.ok) throw new Error(`Failed to load datasets (${res.status})`);
  return res.json();
}
