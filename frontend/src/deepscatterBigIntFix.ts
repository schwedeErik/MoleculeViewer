import type Scatterplot from 'deepscatter';

/** Turn Arrow / Deepscatter row values into plain JSON-safe numbers. */
function coerceValue(value: unknown): unknown {
  if (typeof value === 'bigint') return Number(value);
  if (typeof value === 'object' && value !== null && typeof (value as { valueOf?: () => unknown }).valueOf === 'function') {
    const prim = (value as { valueOf: () => unknown }).valueOf();
    if (typeof prim === 'bigint') return Number(prim);
    if (typeof prim === 'number' && Number.isFinite(prim)) return prim;
  }
  return value;
}

/** Materialize an Arrow StructRow (or similar) into a plain object without BigInts. */
export function materializeDeepscatterPoint(row: unknown): Record<string, unknown> {
  if (row == null || typeof row !== 'object') return {};
  const withJson = row as { toJSON?: () => Record<string, unknown> };
  const src =
    typeof withJson.toJSON === 'function' ? withJson.toJSON() : (row as Record<string, unknown>);
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(src)) {
    out[key] = coerceValue(src[key]);
  }
  return out;
}

type ZoomWithHighlight = {
  set_highlit_points: (data: unknown[]) => void;
  __bigintPatched?: boolean;
};

type AestheticLike = {
  value_for?: (point: unknown) => unknown;
  apply?: (point: unknown) => unknown;
  __bigintPatched?: boolean;
};

/**
 * Deepscatter hover uses d3-scales on Arrow row fields. int64 (and some Arrow
 * proxies) surface as BigInt; ``+bigint`` throws in d3. Coerce before highlight.
 */
export function installDeepscatterBigIntFix(plot: InstanceType<typeof Scatterplot>): void {
  const zoom = (plot as unknown as { _zoom?: ZoomWithHighlight })._zoom;
  if (zoom && !zoom.__bigintPatched) {
    const original = zoom.set_highlit_points.bind(zoom);
    zoom.set_highlit_points = (data: unknown[]) => {
      const rows = Array.isArray(data) ? data.map(materializeDeepscatterPoint) : [];
      return original(rows);
    };
    zoom.__bigintPatched = true;
  }

  const dims = ['x', 'y', 'color', 'size', 'jitter_radius', 'filter'] as const;
  for (const name of dims) {
    let aesthetic: AestheticLike | undefined;
    try {
      aesthetic = (
        plot as unknown as { dim?: (d: string) => AestheticLike }
      ).dim?.(name);
    } catch {
      aesthetic = undefined;
    }
    if (!aesthetic || aesthetic.__bigintPatched) continue;
    if (typeof aesthetic.value_for === 'function') {
      const originalValueFor = aesthetic.value_for.bind(aesthetic);
      aesthetic.value_for = (point: unknown) => coerceValue(originalValueFor(point));
    }
    if (typeof aesthetic.apply === 'function') {
      const originalApply = aesthetic.apply.bind(aesthetic);
      aesthetic.apply = (point: unknown) => {
        try {
          return originalApply(point);
        } catch (err) {
          if (err instanceof TypeError && String(err.message).includes('BigInt')) {
            return originalApply(materializeDeepscatterPoint(point));
          }
          throw err;
        }
      };
    }
    aesthetic.__bigintPatched = true;
  }
}
