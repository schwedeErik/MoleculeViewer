/** Map LOD aggressiveness slider → Deepscatter `max_points`.
 *
 * Deepscatter does not filter by `rank` at request time; importance is encoded
 * in quadfeather file order. The slider only changes how many points the client
 * tries to draw (coarser overview vs denser).
 */

export const LOD_STEP_COUNT = 8;
/** Default = Balanced (75k budget). */
export const DEFAULT_LOD_LEVEL = 5;

const MAX_POINTS_BY_LEVEL: readonly number[] = [
  500, // 1 Tiny
  1_500, // 2 Minimal
  5_000, // 3 Sparse
  20_000, // 4 Lean
  75_000, // 5 Balanced
  200_000, // 6 Fuller
  500_000, // 7 Dense
  2_000_000 // 8 All (practical cap)
];

const LABELS = [
  'Tiny',
  'Minimal',
  'Sparse',
  'Lean',
  'Balanced',
  'Fuller',
  'Dense',
  'All'
] as const;

export function clampLodLevel(level: number): number {
  if (!Number.isFinite(level)) return DEFAULT_LOD_LEVEL;
  return Math.min(LOD_STEP_COUNT, Math.max(1, Math.round(level)));
}

export function labelForLodLevel(level: number): string {
  return LABELS[clampLodLevel(level) - 1] ?? 'Balanced';
}

export function maxPointsForLodLevel(level: number): number {
  return MAX_POINTS_BY_LEVEL[clampLodLevel(level) - 1] ?? MAX_POINTS_BY_LEVEL[4];
}
