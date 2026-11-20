import Scatterplot from 'deepscatter';
import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import {
  DEFAULT_LOD_LEVEL,
  LOD_STEP_COUNT,
  clampLodLevel,
  labelForLodLevel,
  maxPointsForLodLevel
} from './deepscatterLod';
import { useAppStore } from './store';
import type { DatasetInfo } from './types';

export type DeepscatterViewProps = {
  onBack: () => void;
  /** Switch to legacy deck.gl MVT viewer (kept for comparison). */
  onOpenLegacyMvt?: () => void;
};

type MoleculeDetail = {
  id: number;
  rank: number;
  lng: number;
  lat: number;
  smiles: string | null;
  name: string | null;
};

type TileOrder = 'ranked' | 'shuffled';

/** Point under the cursor; x / y are pixels relative to the map area. */
type HoverInfo = {
  id: number;
  rank: number;
  x: number;
  y: number;
};

/** The pointer must rest on a point this long before its structure is requested. */
const HOVER_DELAY_MS = 120;
/** Mouse movement below this (px) counts as a click, not a pan. */
const CLICK_MOVE_PX = 6;
const TOOLTIP_IMG_W = 220;
const TOOLTIP_IMG_H = 165;
const TOOLTIP_W = TOOLTIP_IMG_W + 18;
const TOOLTIP_H = TOOLTIP_IMG_H + 44;
const TOOLTIP_OFFSET = 16;
const DETAIL_IMG_W = 280;
const DETAIL_IMG_H = 210;

/** Hover tooltip with the 2D structure drawn by the backend (RDKit SVG). */
function MoleculeTooltip({
  hover,
  structureUrl,
  areaWidth,
  areaHeight
}: {
  hover: HoverInfo;
  structureUrl: string;
  areaWidth: number;
  areaHeight: number;
}) {
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');

  // Place the tooltip beside the cursor and flip it at the right / bottom edges.
  let left = hover.x + TOOLTIP_OFFSET;
  if (left + TOOLTIP_W > areaWidth) left = hover.x - TOOLTIP_OFFSET - TOOLTIP_W;
  let top = hover.y + TOOLTIP_OFFSET;
  if (top + TOOLTIP_H > areaHeight) top = hover.y - TOOLTIP_OFFSET - TOOLTIP_H;

  return (
    <div
      style={{
        position: 'absolute',
        left: Math.max(4, left),
        top: Math.max(4, top),
        width: TOOLTIP_W,
        boxSizing: 'border-box',
        padding: 8,
        background: '#fff',
        border: '1px solid #d0d0d0',
        borderRadius: 8,
        boxShadow: '0 4px 16px rgba(0,0,0,0.2)',
        fontSize: 12,
        color: '#333',
        zIndex: 5,
        pointerEvents: 'none'
      }}
    >
      <div
        style={{
          width: TOOLTIP_IMG_W,
          height: TOOLTIP_IMG_H,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#888'
        }}
      >
        {state === 'error' ? (
          <span>No structure available</span>
        ) : (
          <img
            src={structureUrl}
            width={TOOLTIP_IMG_W}
            height={TOOLTIP_IMG_H}
            alt={`Structure of molecule ${hover.id}`}
            style={{ display: 'block', opacity: state === 'ready' ? 1 : 0 }}
            onLoad={() => setState('ready')}
            onError={() => setState('error')}
          />
        )}
      </div>
      <div style={{ marginTop: 4, display: 'flex', justifyContent: 'space-between', gap: 8 }}>
        <span>
          <strong>rank</strong> {hover.rank.toLocaleString()}
        </span>
        <span style={{ color: '#888' }}>id {hover.id}</span>
      </div>
    </div>
  );
}

function tilesBaseUrl(apiBase: string, slug: string, order: TileOrder): string {
  const path = `${apiBase}/deepscatter/${encodeURIComponent(slug)}/${order}`;
  if (path.startsWith('http://') || path.startsWith('https://')) return path;
  return `${window.location.origin}${path.startsWith('/') ? '' : '/'}${path}`;
}

export function DeepscatterView({ onBack, onOpenLegacyMvt }: DeepscatterViewProps) {
  const apiBase = useAppStore((s) => s.apiBase);
  const datasetSlug = useAppStore((s) => s.datasetSlug);
  const setDatasetSlug = useAppStore((s) => s.setDatasetSlug);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapAreaRef = useRef<HTMLDivElement | null>(null);
  const plotRef = useRef<InstanceType<typeof Scatterplot> | null>(null);
  const readyRef = useRef(false);

  // Hover / click state. The refs are read inside deepscatter callbacks, which
  // fire on every mouse move and must not depend on React re-renders.
  const [hover, setHover] = useState<HoverInfo | null>(null);
  const pointerRef = useRef({ x: 0, y: 0, buttons: 0 });
  const hoverIdRef = useRef<number | null>(null);
  const hoverTimerRef = useRef<number | null>(null);
  /** Point currently under the cursor (Deepscatter highlight), used for click. */
  const highlitRef = useRef<{ id: number; rank: number; x: number; y: number; smiles: string | null } | null>(
    null
  );
  /**
   * Snapshot taken on pointerdown. Deepscatter's d3-zoom registers a capturing
   * window ``mouseup`` that calls stopPropagation, so React ``onMouseUp`` on the
   * map never runs — we finish the click from a window ``pointerup`` listener
   * instead, using this snapshot.
   */
  const pendingClickRef = useRef<{
    x: number;
    y: number;
    point: { id: number; rank: number; x: number; y: number; smiles: string | null } | null;
  } | null>(null);
  const datasetSlugRef = useRef(datasetSlug);
  datasetSlugRef.current = datasetSlug;
  const apiBaseRef = useRef(apiBase);
  apiBaseRef.current = apiBase;

  const clearHover = useCallback(() => {
    if (hoverTimerRef.current !== null) {
      window.clearTimeout(hoverTimerRef.current);
      hoverTimerRef.current = null;
    }
    hoverIdRef.current = null;
    setHover(null);
  }, []);

  const selectMolecule = useCallback(
    async (datum: {
      id: number;
      rank: number;
      x: number;
      y: number;
      smiles?: string | null;
    }) => {
      const slug = datasetSlugRef.current;
      const base = apiBaseRef.current;
      if (!slug || !Number.isFinite(datum.id) || datum.id < 0) {
        setSelected({
          id: -1,
          rank: datum.rank,
          lng: datum.x,
          lat: datum.y,
          smiles: datum.smiles ?? null,
          name: null
        });
        return;
      }
      try {
        const res = await fetch(
          `${base}/molecules/${datum.id}?dataset=${encodeURIComponent(slug)}`
        );
        if (res.ok) {
          setSelected(await res.json());
          return;
        }
      } catch {
        /* tile fields fallback */
      }
      setSelected({
        id: datum.id,
        rank: datum.rank,
        lng: datum.x,
        lat: datum.y,
        smiles: datum.smiles ?? null,
        name: null
      });
    },
    []
  );
  const selectMoleculeRef = useRef(selectMolecule);
  selectMoleculeRef.current = selectMolecule;

  // Finish clicks on window pointerup. Deepscatter's d3-zoom attaches a
  // capturing window mouseup that stopPropagation's, so map-area mouseup never
  // runs; pointer events are not intercepted the same way.
  useEffect(() => {
    const onPointerUp = (e: PointerEvent) => {
      if (e.button !== 0) return;
      const pending = pendingClickRef.current;
      pendingClickRef.current = null;
      if (!pending?.point) return;
      const dx = e.clientX - pending.x;
      const dy = e.clientY - pending.y;
      if (dx * dx + dy * dy > CLICK_MOVE_PX * CLICK_MOVE_PX) return;
      void selectMoleculeRef.current(pending.point);
    };
    window.addEventListener('pointerup', onPointerUp, true);
    return () => window.removeEventListener('pointerup', onPointerUp, true);
  }, []);

  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [lodLevel, setLodLevel] = useState(DEFAULT_LOD_LEVEL);
  const [order, setOrder] = useState<TileOrder>('ranked');
  /** Base marker size in screen pixels (Deepscatter scales it with zoom via zoom_balance). */
  const [pointSize, setPointSize] = useState(1);
  const [status, setStatus] = useState<string>('Loading…');
  const [error, setError] = useState<string | null>(null);
  const [plotReady, setPlotReady] = useState(false);
  const [selected, setSelected] = useState<MoleculeDetail | null>(null);
  const [bounds, setBounds] = useState<{
    min_x: number;
    max_x: number;
    min_y: number;
    max_y: number;
    max_rank: number;
  } | null>(null);

  const activeDataset = datasets.find((d) => d.slug === datasetSlug);
  const ordersAvailable = activeDataset?.deepscatter_orders ?? [];
  const tilesReady = Boolean(datasetSlug && ordersAvailable.includes(order));
  const lodLabel = labelForLodLevel(lodLevel);
  const maxPoints = maxPointsForLodLevel(lodLevel);

  useEffect(() => {
    const ac = new AbortController();
    (async () => {
      try {
        const res = await fetch(`${apiBase}/datasets`, { signal: ac.signal });
        if (!res.ok) return;
        setDatasets(await res.json());
      } catch (e) {
        if ((e as Error).name === 'AbortError') return;
      }
    })();
    return () => ac.abort();
  }, [apiBase]);

  useEffect(() => {
    if (!activeDataset) return;
    const available = activeDataset.deepscatter_orders ?? [];
    if (available.length === 0) return;
    if (!available.includes(order)) {
      setOrder(available.includes('ranked') ? 'ranked' : (available[0] as TileOrder));
    }
  }, [activeDataset, order]);

  // Initial Deepscatter load (dataset / tile order).
  useEffect(() => {
    if (!datasetSlug || !tilesReady) {
      readyRef.current = false;
      setPlotReady(false);
      plotRef.current = null;
      return;
    }

    const el = containerRef.current;
    if (!el) return;

    let cancelled = false;
    let plot: InstanceType<typeof Scatterplot> | null = null;

    const run = async () => {
      setError(null);
      setPlotReady(false);
      readyRef.current = false;
      setStatus(`Loading Deepscatter tiles (${order})…`);

      // Wait for layout so the container has non-zero size (Deepscatter needs width/height).
      await new Promise<void>((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())));
      if (cancelled) return;

      const rect = el.getBoundingClientRect();
      const width = Math.max(Math.floor(rect.width), 320);
      const height = Math.max(Math.floor(rect.height), 240);

      try {
        const [boundsRes, manifestRes] = await Promise.all([
          fetch(`${apiBase}/bounds?dataset=${encodeURIComponent(datasetSlug)}`),
          fetch(
            `${apiBase}/deepscatter/${encodeURIComponent(datasetSlug)}/${order}/manifest.json`
          )
        ]);
        if (cancelled) return;

        let zoomBbox: { x: [number, number]; y: [number, number] } | undefined;
        let maxRank = 1;

        if (manifestRes.ok) {
          const manifest = await manifestRes.json();
          if (manifest.bounds) {
            zoomBbox = {
              x: [manifest.bounds.min_x, manifest.bounds.max_x],
              y: [manifest.bounds.min_y, manifest.bounds.max_y]
            };
            setBounds({
              min_x: manifest.bounds.min_x,
              max_x: manifest.bounds.max_x,
              min_y: manifest.bounds.min_y,
              max_y: manifest.bounds.max_y,
              max_rank: manifest.max_rank ?? 1
            });
            maxRank = manifest.max_rank ?? 1;
          }
        }

        if (boundsRes.ok) {
          const b = await boundsRes.json();
          maxRank = b.max_rank ?? maxRank;
          if (!zoomBbox && b.count) {
            zoomBbox = {
              x: [b.min_lng, b.max_lng],
              y: [b.min_lat, b.max_lat]
            };
            setBounds({
              min_x: b.min_lng,
              max_x: b.max_lng,
              min_y: b.min_lat,
              max_y: b.max_lat,
              max_rank: maxRank
            });
          }
        }

        if (cancelled) return;

        el.replaceChildren();
        plot = new Scatterplot(el, width, height);
        plotRef.current = plot;

        const sourceUrl = tilesBaseUrl(apiBase, datasetSlug, order);

        // Do NOT pass click_function into plotAPI: deepscatter wraps it with
        // `Function("datum", prefs.click_function)` and breaks real functions.
        await plot.plotAPI({
          source_url: sourceUrl,
          max_points: maxPoints,
          // Lower alpha keeps dense overviews readable instead of a solid blob.
          alpha: 18,
          // Closer to 0 → more constant screen size; closer to 1 → geographic scaling.
          zoom_balance: 0.2,
          point_size: pointSize,
          background_color: '#ffffff',
          duration: 600,
          ...(zoomBbox ? { zoom: { bbox: zoomBbox } } : {}),
          encoding: {
            x: { field: 'x', transform: 'literal' },
            y: { field: 'y', transform: 'literal' },
            color: {
              field: 'rank',
              domain: [1, Math.max(2, maxRank)],
              range: 'viridis'
            }
          }
        });

        if (cancelled) return;

        // Deepscatter only wires click to its hover circle; we also handle click
        // ourselves on mouseup (see map area handlers) using highlitRef.
        plot.click_function = (datum: Record<string, unknown>) => {
          const id = Number(datum.id ?? datum.molecule_id);
          void selectMolecule({
            id: Number.isFinite(id) ? id : -1,
            rank: Number(datum.rank ?? 0),
            x: Number(datum.x ?? 0),
            y: Number(datum.y ?? 0),
            smiles: typeof datum.smiles === 'string' ? datum.smiles : null
          });
        };

        // Hover: deepscatter picks the point under the cursor on mouse move and
        // reports it here. Its own tooltip (a field dump) is replaced by the
        // React tooltip below, so it gets no content and is hidden by CSS.
        plot.tooltip_html = () => '';
        plot.highlit_point_change = (points: Record<string, unknown>[]) => {
          const point = points?.[0];
          const id = point ? Number(point.id ?? point.molecule_id) : NaN;
          if (!point || !Number.isFinite(id)) {
            highlitRef.current = null;
            clearHover();
            return;
          }
          highlitRef.current = {
            id,
            rank: Number(point.rank ?? 0),
            x: Number(point.x ?? 0),
            y: Number(point.y ?? 0),
            smiles: typeof point.smiles === 'string' ? point.smiles : null
          };
          // No tooltip while a mouse button is down (panning the map).
          if (pointerRef.current.buttons !== 0) {
            clearHover();
            return;
          }
          if (hoverIdRef.current === id) return;
          clearHover();
          hoverIdRef.current = id;
          const { x, y } = pointerRef.current;
          hoverTimerRef.current = window.setTimeout(() => {
            hoverTimerRef.current = null;
            setHover({ id, rank: highlitRef.current?.rank ?? 0, x, y });
          }, HOVER_DELAY_MS);
        };

        readyRef.current = true;
        setPlotReady(true);
        setStatus(
          `${activeDataset?.name ?? datasetSlug} · ${order} · max_points=${maxPoints.toLocaleString()}`
        );
      } catch (e) {
        console.error('Deepscatter load failed', e);
        if (!cancelled) {
          const msg = e instanceof Error ? e.message : String(e);
          setError(msg || 'Unknown Deepscatter error');
          setStatus('Failed to load Deepscatter');
        }
      }
    };

    void run();

    return () => {
      cancelled = true;
      readyRef.current = false;
      setPlotReady(false);
      clearHover();
      try {
        plot?.destroy?.();
      } catch {
        /* ignore */
      }
      if (plotRef.current === plot) plotRef.current = null;
      el.replaceChildren();
    };
    // Intentionally omit maxPoints/pointSize — those update in the next effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBase, datasetSlug, order, tilesReady, selectMolecule, clearHover]);

  // Update draw budget / point size without reloading the tile tree.
  useEffect(() => {
    const plot = plotRef.current;
    if (!plot || !plotReady || !readyRef.current) return;
    void plot
      .plotAPI({
        max_points: maxPoints,
        point_size: pointSize,
        alpha: 18,
        zoom_balance: 0.2,
        duration: 400,
        // deepscatter's start_transformations crashes if encoding is omitted
        encoding: {}
      })
      .then(() => {
        setStatus(
          `${activeDataset?.name ?? datasetSlug} · ${order} · max_points=${maxPoints.toLocaleString()}`
        );
      })
      .catch((e) => {
        console.warn('Deepscatter update failed', e);
      });
  }, [maxPoints, pointSize, plotReady, activeDataset?.name, datasetSlug, order]);

  const selectStyle: CSSProperties = {
    padding: '4px 8px',
    fontSize: 13,
    border: '1px solid #ccc',
    borderRadius: 6,
    background: '#fff'
  };

  const btnStyle: CSSProperties = {
    padding: '6px 12px',
    fontSize: 13,
    fontWeight: 500,
    border: '1px solid #ccc',
    borderRadius: 6,
    background: '#f8f8f8',
    cursor: 'pointer'
  };

  const stopMapGesture: React.DOMAttributes<HTMLInputElement> = {
    onPointerDown: (e) => e.stopPropagation(),
    onPointerMove: (e) => e.stopPropagation(),
    onMouseDown: (e) => e.stopPropagation(),
    onTouchStart: (e) => e.stopPropagation()
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div
        style={{
          padding: '8px 12px',
          display: 'flex',
          gap: 12,
          alignItems: 'center',
          flexWrap: 'wrap',
          borderBottom: '1px solid #eee',
          background: '#fff',
          position: 'relative',
          zIndex: 10,
          flexShrink: 0
        }}
      >
        <button type="button" style={btnStyle} onClick={onBack}>
          ← Dataset & embedding
        </button>
        <div style={{ fontWeight: 600 }}>Molecule Map · Deepscatter</div>

        {datasets.length > 0 && datasetSlug && (
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13 }}>
            <span>dataset</span>
            <select
              value={datasetSlug}
              onChange={(e) => setDatasetSlug(e.target.value)}
              style={selectStyle}
            >
              {datasets.map((d) => (
                <option key={d.slug} value={d.slug}>
                  {d.name}
                  {(d.deepscatter_orders?.length ?? 0) === 0 ? ' (no tiles)' : ''}
                </option>
              ))}
            </select>
          </label>
        )}

        <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13 }}>
          <span>order</span>
          <select
            value={order}
            onChange={(e) => setOrder(e.target.value as TileOrder)}
            style={selectStyle}
            disabled={ordersAvailable.length === 0}
          >
            <option value="ranked" disabled={!ordersAvailable.includes('ranked')}>
              ranked
            </option>
            <option value="shuffled" disabled={!ordersAvailable.includes('shuffled')}>
              shuffled (ablation)
            </option>
          </select>
        </label>

        <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13 }}>
          <span>LOD</span>
          <input
            type="range"
            min={1}
            max={LOD_STEP_COUNT}
            step={1}
            value={lodLevel}
            onChange={(e) => setLodLevel(clampLodLevel(Number(e.target.value)))}
            {...stopMapGesture}
          />
          <span style={{ width: 88, textAlign: 'right' }}>
            {lodLevel}/{LOD_STEP_COUNT} {lodLabel}
          </span>
        </label>

        <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13 }}>
          <span>size</span>
          <input
            type="range"
            min={0.25}
            max={10}
            step={0.25}
            value={pointSize}
            onChange={(e) => setPointSize(Number(e.target.value))}
            {...stopMapGesture}
          />
          <span style={{ width: 28, textAlign: 'right', fontSize: 12, color: '#666' }}>
            {pointSize}
          </span>
        </label>

        {onOpenLegacyMvt && (
          <button type="button" style={btnStyle} onClick={onOpenLegacyMvt}>
            Legacy MVT
          </button>
        )}

        <div style={{ marginLeft: 'auto', color: '#666', fontSize: 12 }}>{status}</div>
      </div>

      <div
        ref={mapAreaRef}
        className="ds-map-area"
        style={{ flex: 1, position: 'relative', background: '#ffffff', minHeight: 0, overflow: 'hidden' }}
        // Capture phase: runs before deepscatter's own mousemove handler, so the
        // pointer position is current when highlit_point_change fires.
        onPointerMoveCapture={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          pointerRef.current = {
            x: e.clientX - rect.left,
            y: e.clientY - rect.top,
            buttons: e.buttons
          };
        }}
        onPointerDownCapture={(e) => {
          if (e.button !== 0) return;
          // Ignore UI overlays inside the map (detail panel, error banner, …).
          if ((e.target as HTMLElement | null)?.closest?.('[data-ds-ui]')) {
            pendingClickRef.current = null;
            return;
          }
          // Snapshot the hovered point now — zoom may clear the highlight before up.
          pendingClickRef.current = {
            x: e.clientX,
            y: e.clientY,
            point: highlitRef.current
          };
          clearHover();
        }}
        onWheelCapture={clearHover}
        onPointerLeave={() => {
          // Don't clear pendingClickRef here: pointer may leave during a click.
          highlitRef.current = null;
          clearHover();
        }}
      >
        {/* Hide deepscatter's built-in tooltip; MoleculeTooltip replaces it. */}
        <style>{'.ds-map-area div.tooltip { display: none !important; }'}</style>

        {!tilesReady && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#333',
              padding: 24,
              textAlign: 'center',
              zIndex: 2,
              background: 'rgba(255,255,255,0.96)'
            }}
          >
            <div style={{ maxWidth: 520, lineHeight: 1.5 }}>
              <div style={{ fontWeight: 600, marginBottom: 8 }}>
                No Deepscatter tiles for this dataset
              </div>
              <div style={{ fontSize: 14, opacity: 0.9 }}>
                From <code>backend/</code> run:
                <pre
                  style={{
                    textAlign: 'left',
                    background: '#f4f4f4',
                    padding: 12,
                    borderRadius: 8,
                    overflow: 'auto',
                    marginTop: 10
                  }}
                >{`python -m scripts.build_deepscatter_tiles --dataset ${datasetSlug ?? 'zinc10k'}
python -m scripts.build_deepscatter_tiles --dataset ${datasetSlug ?? 'zinc10k'} --order shuffled`}</pre>
              </div>
            </div>
          </div>
        )}

        {error && (
          <div
            style={{
              position: 'absolute',
              top: 12,
              left: 12,
              right: 12,
              zIndex: 3,
              background: '#5c1a1a',
              color: '#fff',
              padding: '10px 14px',
              borderRadius: 8,
              fontSize: 13,
              whiteSpace: 'pre-wrap'
            }}
          >
            {error}
          </div>
        )}

        <div
          ref={containerRef}
          style={{ position: 'absolute', inset: 0, overflow: 'hidden' }}
        />

        {hover && datasetSlug && (
          <MoleculeTooltip
            key={hover.id}
            hover={hover}
            structureUrl={
              `${apiBase}/molecules/${hover.id}/structure.svg` +
              `?dataset=${encodeURIComponent(datasetSlug)}` +
              `&width=${TOOLTIP_IMG_W}&height=${TOOLTIP_IMG_H}`
            }
            areaWidth={mapAreaRef.current?.clientWidth ?? 0}
            areaHeight={mapAreaRef.current?.clientHeight ?? 0}
          />
        )}

        {selected && (
          <div
            data-ds-ui
            style={{
              position: 'absolute',
              right: 12,
              bottom: 12,
              width: 320,
              maxHeight: '55%',
              overflow: 'auto',
              background: 'rgba(255,255,255,0.96)',
              borderRadius: 8,
              padding: 12,
              fontSize: 13,
              boxShadow: '0 4px 20px rgba(0,0,0,0.25)',
              zIndex: 4
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <strong>Molecule {selected.id > 0 ? selected.id : ''}</strong>
              <button type="button" style={btnStyle} onClick={() => setSelected(null)}>
                Close
              </button>
            </div>
            {selected.id > 0 && datasetSlug && (
              <img
                key={selected.id}
                src={
                  `${apiBase}/molecules/${selected.id}/structure.svg` +
                  `?dataset=${encodeURIComponent(datasetSlug)}` +
                  `&width=${DETAIL_IMG_W}&height=${DETAIL_IMG_H}`
                }
                width={DETAIL_IMG_W}
                height={DETAIL_IMG_H}
                alt={`Structure of molecule ${selected.id}`}
                style={{
                  display: 'block',
                  width: '100%',
                  height: 'auto',
                  marginTop: 8,
                  background: '#fff',
                  border: '1px solid #eee',
                  borderRadius: 6
                }}
              />
            )}
            <div style={{ marginTop: 8, lineHeight: 1.45 }}>
              <div>
                <strong>rank:</strong> {selected.rank.toLocaleString()}
              </div>
              <div>
                <strong>x / y:</strong> {selected.lng.toFixed(4)} / {selected.lat.toFixed(4)}
              </div>
              {selected.name && (
                <div>
                  <strong>name:</strong> {selected.name}
                </div>
              )}
              {selected.smiles && (
                <div style={{ wordBreak: 'break-all', marginTop: 6 }}>
                  <strong>SMILES:</strong> {selected.smiles}
                </div>
              )}
            </div>
          </div>
        )}

        {bounds && (
          <div
            style={{
              position: 'absolute',
              left: 12,
              bottom: 12,
              color: 'rgba(0,0,0,0.55)',
              fontSize: 11,
              zIndex: 3,
              pointerEvents: 'none'
            }}
          >
            bounds x[{bounds.min_x.toFixed(2)}, {bounds.max_x.toFixed(2)}] y[
            {bounds.min_y.toFixed(2)}, {bounds.max_y.toFixed(2)}] · max rank{' '}
            {bounds.max_rank.toLocaleString()}
          </div>
        )}
      </div>
    </div>
  );
}
