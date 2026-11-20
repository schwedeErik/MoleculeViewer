/** Map LOD aggressiveness slider → Deepscatter `max_points`.
 *
 * Deepscatter does not filter by `rank` at request time; importance is encoded
 * in quadfeather file order. The slider only changes how many points the client
 * tries to draw (coarser overview vs denser).
 *
 * 100 log-spaced steps from {@link MIN_MAX_POINTS} to {@link MAX_MAX_POINTS}.
 */

export const LOD_STEP_COUNT = 100;
export const MIN_MAX_POINTS = 10;
export const MAX_MAX_POINTS = 2_000_000;

function lodLevelFromBudget(budget: number): number {
  const b = Math.min(MAX_MAX_POINTS, Math.max(MIN_MAX_POINTS, budget));
  const t =
    (Math.log(b) - Math.log(MIN_MAX_POINTS)) /
    (Math.log(MAX_MAX_POINTS) - Math.log(MIN_MAX_POINTS));
  return clampLodLevel(1 + t * (LOD_STEP_COUNT - 1));
}

/** Default ≈ Balanced (75k budget). */
export const DEFAULT_LOD_LEVEL = lodLevelFromBudget(75_000);

export function clampLodLevel(level: number): number {
  if (!Number.isFinite(level)) return DEFAULT_LOD_LEVEL;
  return Math.min(LOD_STEP_COUNT, Math.max(1, Math.round(level)));
}

/** Coarse label for the current third of the slider. */
export function labelForLodLevel(level: number): string {
  const t = (clampLodLevel(level) - 1) / (LOD_STEP_COUNT - 1);
  if (t < 0.2) return 'Tiny';
  if (t < 0.4) return 'Sparse';
  if (t < 0.6) return 'Balanced';
  if (t < 0.8) return 'Dense';
  return 'All';
}

export function maxPointsForLodLevel(level: number): number {
  const t = (clampLodLevel(level) - 1) / (LOD_STEP_COUNT - 1);
  const logMin = Math.log(MIN_MAX_POINTS);
  const logMax = Math.log(MAX_MAX_POINTS);
  return Math.max(MIN_MAX_POINTS, Math.round(Math.exp(logMin + t * (logMax - logMin))));
}
