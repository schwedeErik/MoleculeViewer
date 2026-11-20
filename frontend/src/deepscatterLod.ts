/** Map LOD aggressiveness slider → Deepscatter `max_points`.
 *
 * Deepscatter does not filter by `rank` at request time; importance is encoded
 * in quadfeather file order. The slider only changes how many points the client
 * tries to draw (coarser overview vs denser).
 */

export const LOD_STEP_COUNT = 6;
export const DEFAULT_LOD_LEVEL = 3;

const MAX_POINTS_BY_LEVEL: readonly number[] = [
  5_000, // 1 Sparse
  20_000, // 2
  75_000, // 3 Balanced
  200_000, // 4
  500_000, // 5 Dense
  2_000_000 // 6 All (practical cap)
];

const LABELS = ['Sparse', 'Lean', 'Balanced', 'Fuller', 'Dense', 'All'] as const;

export function clampLodLevel(level: number): number {
  if (!Number.isFinite(level)) return DEFAULT_LOD_LEVEL;
  return Math.min(LOD_STEP_COUNT, Math.max(1, Math.round(level)));
}

export function labelForLodLevel(level: number): string {
  return LABELS[clampLodLevel(level) - 1] ?? 'Balanced';
}

export function maxPointsForLodLevel(level: number): number {
  return MAX_POINTS_BY_LEVEL[clampLodLevel(level) - 1] ?? MAX_POINTS_BY_LEVEL[2];
}
