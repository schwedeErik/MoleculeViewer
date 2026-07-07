/** First zoom level where rank budget starts growing (z=2 → base, z=3 → base×growth, …). */
const LOD_START_ZOOM = 2;

export const ZOOM_LOD_AGGRESSIVENESS_DEFAULT = 50;

/** Map 0–100 aggressiveness to LOD base + per-zoom growth (50 = 1k × 4^…). */
export function lodParamsForAggressiveness(aggressiveness: number): {
  base: number;
  growth: number;
} {
  const a = Math.min(100, Math.max(0, aggressiveness));
  if (a <= ZOOM_LOD_AGGRESSIVENESS_DEFAULT) {
    const t = a / ZOOM_LOD_AGGRESSIVENESS_DEFAULT;
    return {
      base: Math.round(250 + t * (1_000 - 250)),
      growth: 1.5 + t * (4 - 1.5)
    };
  }
  const t = (a - ZOOM_LOD_AGGRESSIVENESS_DEFAULT) / (100 - ZOOM_LOD_AGGRESSIVENESS_DEFAULT);
  return {
    base: Math.round(1_000 + t * (4_000 - 1_000)),
    growth: 4 + t * (8 - 4)
  };
}

/**
 * Global rank cap from zoom level: zoomed out → fewer ranks; zoomed in → more.
 * Higher aggressiveness raises base and growth (more ranks per zoom step).
 */
export function rankMaxForZoom(
  zoom: number,
  datasetRankMax: number,
  aggressiveness = ZOOM_LOD_AGGRESSIVENESS_DEFAULT
): number {
  const { base, growth } = lodParamsForAggressiveness(aggressiveness);
  const z = Math.floor(zoom);
  const exponent = Math.max(0, z - LOD_START_ZOOM);
  const fromZoom = Math.round(base * growth ** exponent);
  return Math.min(datasetRankMax, Math.max(base, fromZoom));
}

/** Zoom LOD capped by the manual rank-max slider. */
export function effectiveRankMax(
  zoom: number,
  datasetRankMax: number,
  userRankCap: number,
  aggressiveness = ZOOM_LOD_AGGRESSIVENESS_DEFAULT
): number {
  return Math.min(userRankCap, rankMaxForZoom(zoom, datasetRankMax, aggressiveness));
}
