/** First zoom level where rank budget starts growing (z=2 → base, z=3 → base×growth, …). */
const LOD_START_ZOOM = 2;

/**
 * LOD slider steps: 1…(N-1) are zoom-based aggressiveness curves;
 * step N is "All" (always show every molecule, ignore zoom).
 */
export const LOD_STEP_COUNT = 6;

/** Last step: show the full dataset at every zoom. */
export const LOD_ALL_LEVEL = LOD_STEP_COUNT;

/** Default mid curve step (Balanced-equivalent among 1…5). */
export const DEFAULT_LOD_LEVEL = 3;

/** Highest zoom-based step before "All". */
const LOD_CURVE_STEP_COUNT = LOD_STEP_COUNT - 1;

export type LodStep = {
  level: number;
  label: string;
  /** Internal aggressiveness on the 0–100 scale; unused for the "All" step. */
  aggressiveness: number | null;
};

/** Steps 1–5: aggressiveness 0, 25, 50, 75, 100. Step 6: All. */
export const LOD_STEPS: readonly LodStep[] = [
  ...Array.from({ length: LOD_CURVE_STEP_COUNT }, (_, i) => {
    const level = i + 1;
    const aggressiveness = Math.round((i / (LOD_CURVE_STEP_COUNT - 1)) * 100);
    const label =
      level === 1
        ? 'Sparse'
        : level === DEFAULT_LOD_LEVEL
          ? 'Balanced'
          : level === LOD_CURVE_STEP_COUNT
            ? 'Dense'
            : `Level ${level}`;
    return { level, label, aggressiveness };
  }),
  { level: LOD_ALL_LEVEL, label: 'All', aggressiveness: null }
];

export function clampLodLevel(level: number): number {
  return Math.min(LOD_STEP_COUNT, Math.max(1, Math.round(level)));
}

export function isShowAllLod(level: number): boolean {
  return clampLodLevel(level) === LOD_ALL_LEVEL;
}

export function aggressivenessForLodLevel(level: number): number {
  if (isShowAllLod(level)) return 100;
  const step = LOD_STEPS.find((s) => s.level === clampLodLevel(level));
  return step?.aggressiveness ?? 50;
}

export function labelForLodLevel(level: number): string {
  const step = LOD_STEPS.find((s) => s.level === clampLodLevel(level));
  return step?.label ?? `Level ${level}`;
}

/** Map 0–100 aggressiveness to LOD base + per-zoom growth (50 = 1k × 4^…). */
export function lodParamsForAggressiveness(aggressiveness: number): {
  base: number;
  growth: number;
} {
  const a = Math.min(100, Math.max(0, aggressiveness));
  if (a <= 50) {
    const t = a / 50;
    return {
      base: Math.round(250 + t * (1_000 - 250)),
      growth: 1.5 + t * (4 - 1.5)
    };
  }
  const t = (a - 50) / 50;
  return {
    base: Math.round(1_000 + t * (4_000 - 1_000)),
    growth: 4 + t * (8 - 4)
  };
}

/**
 * Global rank budget from zoom: zoomed out → fewer ranks; zoomed in → more.
 * LOD level 6 ("All") always returns the full dataset size.
 */
export function rankMaxForZoom(
  zoom: number,
  datasetRankMax: number,
  lodLevel: number = DEFAULT_LOD_LEVEL
): number {
  if (isShowAllLod(lodLevel)) {
    return Math.max(1, datasetRankMax);
  }
  const aggressiveness = aggressivenessForLodLevel(lodLevel);
  const { base, growth } = lodParamsForAggressiveness(aggressiveness);
  const z = Math.floor(zoom);
  const exponent = Math.max(0, z - LOD_START_ZOOM);
  const fromZoom = Math.round(base * growth ** exponent);
  return Math.min(datasetRankMax, Math.max(base, fromZoom));
}
