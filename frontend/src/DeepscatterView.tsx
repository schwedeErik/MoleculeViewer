import Scatterplot from 'deepscatter';
import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import { apiBase, deepscatterTilesUrl, isStatic, loadDatasetsCatalog } from './config';
import {
  DEFAULT_LOD_LEVEL,
  LOD_STEP_COUNT,
  clampLodLevel,
  labelForLodLevel,
  maxPointsForLodLevel
} from './deepscatterLod';
import { SmilesStructure } from './SmilesStructure';
import { useAppStore } from './store';
import type { DatasetInfo } from './types';

export type DeepscatterViewProps = {
  onBack: () => void;
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
  smiles: string | null;
};

/** The pointer must rest on a point this long before the tooltip is shown. */
const HOVER_DELAY_MS = 120;
/** Mouse movement below this (px) counts as a click, not a pan. */
const CLICK_MOVE_PX = 6;
const TOOLTIP_IMG_W = 220;
const TOOLTIP_IMG_H = 165;
const TOOLTIP_W = TOOLTIP_IMG_W + 18;
const TOOLTIP_H = TOOLTIP_IMG_H + 44;
const TOOLTIP_TEXT_H = 48;
const TOOLTIP_OFFSET = 16;
const DETAIL_IMG_W = 280;
const DETAIL_IMG_H = 210;

/** Deepscatter's zoom-scaled index cutoff (not the same as the slider budget). */
function readLiveMaxIx(plot: InstanceType<typeof Scatterplot> | null): number | null {
  const v = plot?._renderer?.max_ix;
  return typeof v === 'number' && Number.isFinite(v) ? Math.round(v) : null;
}

function formatMapStatus(
  name: string,
  tileOrder: string,
  budget: number,
  liveIx: number | null
): string {
  const base = `${name} · ${tileOrder} · budget=${budget.toLocaleString()}`;
  if (liveIx == null) return base;
  return `${base} · live≈${liveIx.toLocaleString()}`;
}

function structureSvgUrl(slug: string, moleculeId: number, width: number, height: number): string | null {
  if (isStatic || !apiBase) return null;
  return (
    `${apiBase}/molecules/${moleculeId}/structure.svg` +
    `?dataset=${encodeURIComponent(slug)}` +
    `&width=${width}&height=${height}`
  );
}

/** Hover tooltip: RDKit SVG from backend, or client-side SmilesDrawer when tiles include SMILES. */
function MoleculeTooltip({
  hover,
  structureUrl,
  areaWidth,
  areaHeight
}: {
  hover: HoverInfo;
  structureUrl: string | null;
  areaWidth: number;
  areaHeight: number;
}) {
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const smiles = hover.smiles?.trim() || null;
  const showStructure = Boolean(structureUrl || smiles);
  const boxH = showStructure ? TOOLTIP_H : TOOLTIP_TEXT_H;
  const boxW = showStructure ? TOOLTIP_W : 160;

  let left = hover.x + TOOLTIP_OFFSET;
  if (left + boxW > areaWidth) left = hover.x - TOOLTIP_OFFSET - boxW;
  let top = hover.y + TOOLTIP_OFFSET;
  if (top + boxH > areaHeight) top = hover.y - TOOLTIP_OFFSET - boxH;

  return (
    <div
      style={{
        position: 'absolute',
        left: Math.max(4, left),
        top: Math.max(4, top),
        width: boxW,
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
      {showStructure && (
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
          {structureUrl ? (
            state === 'error' ? (
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
            )
          ) : smiles ? (
            <SmilesStructure
              smiles={smiles}
              width={TOOLTIP_IMG_W}
              height={TOOLTIP_IMG_H}
              alt={`Structure of molecule ${hover.id}`}
            />
          ) : null}
        </div>
      )}
      <div
        style={{
          marginTop: showStructure ? 4 : 0,
          display: 'flex',
          justifyContent: 'space-between',
          gap: 8
        }}
      >
        <span>
          <strong>rank</strong> {hover.rank.toLocaleString()}
        </span>
        <span style={{ color: '#888' }}>id {hover.id}</span>
      </div>
    </div>
  );
}

export function DeepscatterView({ onBack }: DeepscatterViewProps) {
  const datasetSlug = useAppStore((s) => s.datasetSlug);
  const setDatasetSlug = useAppStore((s) => s.setDatasetSlug);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapAreaRef = useRef<HTMLDivElement | null>(null);
  const plotRef = useRef<InstanceType<typeof Scatterplot> | null>(null);
  const readyRef = useRef(false);

  const [hover, setHover] = useState<HoverInfo | null>(null);
  const pointerRef = useRef({ x: 0, y: 0, buttons: 0 });
  const hoverIdRef = useRef<number | null>(null);
  const hoverTimerRef = useRef<number | null>(null);
  const highlitRef = useRef<{ id: number; rank: number; x: number; y: number; smiles: string | null } | null>(
    null
  );
  /**
   * Snapshot taken on pointerdown. Deepscatter's d3-zoom registers a capturing
   * window ``mouseup`` that calls stopPropagation, so React ``onMouseUp`` on the
   * map never runs — we finish the click from a window ``pointerup`` listener.
   */
  const pendingClickRef = useRef<{
    x: number;
    y: number;
    point: { id: number; rank: number; x: number; y: number; smiles: string | null } | null;
  } | null>(null);
  const datasetSlugRef = useRef(datasetSlug);
  datasetSlugRef.current = datasetSlug;

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
      if (!isStatic && apiBase) {
        try {
          const res = await fetch(
            `${apiBase}/molecules/${datum.id}?dataset=${encodeURIComponent(slug)}`
          );
          if (res.ok) {
            setSelected(await res.json());
            return;
          }
        } catch {
          /* tile fields fallback */
        }
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
  const statusName = activeDataset?.name ?? datasetSlug ?? '';
  const statusNameRef = useRef(statusName);
  statusNameRef.current = statusName;
  const orderRef = useRef(order);
  orderRef.current = order;
  const maxPointsRef = useRef(maxPoints);
  maxPointsRef.current = maxPoints;

  const refreshStatus = useCallback(() => {
    setStatus(
      formatMapStatus(
        statusNameRef.current,
        orderRef.current,
        maxPointsRef.current,
        readLiveMaxIx(plotRef.current)
      )
    );
  }, []);

  useEffect(() => {
    const ac = new AbortController();
    (async () => {
      try {
        setDatasets(await loadDatasetsCatalog(ac.signal));
      } catch (e) {
        if ((e as Error).name === 'AbortError') return;
      }
    })();
    return () => ac.abort();
  }, []);

  useEffect(() => {
    if (!activeDataset) return;
    const available = activeDataset.deepscatter_orders ?? [];
    if (available.length === 0) return;
    if (!available.includes(order)) {
      setOrder(available.includes('ranked') ? 'ranked' : (available[0] as TileOrder));
    }
  }, [activeDataset, order]);

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

      await new Promise<void>((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())));
      if (cancelled) return;

      const rect = el.getBoundingClientRect();
      const width = Math.max(Math.floor(rect.width), 320);
      const height = Math.max(Math.floor(rect.height), 240);

      try {
        const manifestUrl = `${deepscatterTilesUrl(datasetSlug, order)}/manifest.json`;
        const fetches: Promise<Response>[] = [fetch(manifestUrl)];
        if (!isStatic && apiBase) {
          fetches.push(fetch(`${apiBase}/bounds?dataset=${encodeURIComponent(datasetSlug)}`));
        }
        const responses = await Promise.all(fetches);
        if (cancelled) return;

        const manifestRes = responses[0];
        const boundsRes = responses[1];

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

        if (boundsRes?.ok) {
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

        const sourceUrl = deepscatterTilesUrl(datasetSlug, order);

        await plot.plotAPI({
          source_url: sourceUrl,
          max_points: maxPoints,
          alpha: 18,
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
            setHover({
              id,
              rank: highlitRef.current?.rank ?? 0,
              x,
              y,
              smiles: highlitRef.current?.smiles ?? null
            });
          }, HOVER_DELAY_MS);
        };

        plot.on_zoom = () => {
          refreshStatus();
        };

        readyRef.current = true;
        setPlotReady(true);
        setStatus(
          formatMapStatus(
            activeDataset?.name ?? datasetSlug,
            order,
            maxPoints,
            readLiveMaxIx(plot)
          )
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
  }, [datasetSlug, order, tilesReady, selectMolecule, clearHover, refreshStatus]);

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
        encoding: {}
      })
      .then(() => {
        refreshStatus();
      })
      .catch((e) => {
        console.warn('Deepscatter update failed', e);
      });
  }, [maxPoints, pointSize, plotReady, activeDataset?.name, datasetSlug, order, refreshStatus]);

  // Keep live≈… current while tiles stream in after zoom / LOD changes.
  useEffect(() => {
    if (!plotReady) return;
    const id = window.setInterval(refreshStatus, 750);
    return () => window.clearInterval(id);
  }, [plotReady, refreshStatus]);

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

  const selectedStructureUrl =
    selected && selected.id > 0 && datasetSlug
      ? structureSvgUrl(datasetSlug, selected.id, DETAIL_IMG_W, DETAIL_IMG_H)
      : null;

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
          ← Dataset
        </button>
        <div style={{ fontWeight: 600 }}>Molecule Map · Deepscatter</div>

        {datasetSlug && (
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13 }}>
            <span>dataset</span>
            <select
              value={datasetSlug}
              onChange={(e) => setDatasetSlug(e.target.value)}
              style={selectStyle}
              disabled={datasets.length === 0}
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
            max={2}
            step={0.25}
            value={pointSize}
            onChange={(e) => setPointSize(Number(e.target.value))}
            {...stopMapGesture}
          />
          <span style={{ width: 28, textAlign: 'right', fontSize: 12, color: '#666' }}>
            {pointSize}
          </span>
        </label>

        <div style={{ marginLeft: 'auto', color: '#666', fontSize: 12 }}>{status}</div>
      </div>

      <div
        ref={mapAreaRef}
        className="ds-map-area"
        style={{ flex: 1, position: 'relative', background: '#ffffff', minHeight: 0, overflow: 'hidden' }}
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
          if ((e.target as HTMLElement | null)?.closest?.('[data-ds-ui]')) {
            pendingClickRef.current = null;
            return;
          }
          pendingClickRef.current = {
            x: e.clientX,
            y: e.clientY,
            point: highlitRef.current
          };
          clearHover();
        }}
        onWheelCapture={clearHover}
        onPointerLeave={() => {
          highlitRef.current = null;
          clearHover();
        }}
      >
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
                {isStatic ? (
                  <>Add tiles under <code>frontend/public/deepscatter/{datasetSlug ?? 'slug'}/</code>.</>
                ) : (
                  <>
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
                  </>
                )}
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

        <div ref={containerRef} style={{ position: 'absolute', inset: 0, overflow: 'hidden' }} />

        {hover && datasetSlug && (
          <MoleculeTooltip
            key={hover.id}
            hover={hover}
            structureUrl={structureSvgUrl(datasetSlug, hover.id, TOOLTIP_IMG_W, TOOLTIP_IMG_H)}
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
            {selectedStructureUrl ? (
              <img
                key={selected.id}
                src={selectedStructureUrl}
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
            ) : selected.smiles ? (
              <div
                style={{
                  marginTop: 8,
                  border: '1px solid #eee',
                  borderRadius: 6,
                  overflow: 'hidden'
                }}
              >
                <SmilesStructure
                  key={selected.id}
                  smiles={selected.smiles}
                  width={DETAIL_IMG_W}
                  height={DETAIL_IMG_H}
                  alt={`Structure of molecule ${selected.id}`}
                />
              </div>
            ) : null}
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
              {!selectedStructureUrl && !selected.smiles && (
                <div style={{ marginTop: 6, color: '#666', fontSize: 12 }}>
                  No SMILES in these tiles — rebuild with --include-smiles for structure hover.
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
