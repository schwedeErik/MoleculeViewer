import DeckGL from '@deck.gl/react';
import { MapView, WebMercatorViewport } from '@deck.gl/core';
import { ScatterplotLayer } from '@deck.gl/layers';
import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { useAppStore } from './store';
import { decodePointsPb, type DecodedPoint } from './proto';

const PREFETCH_PAD_FACTOR = 0.5;
const PREFETCH_LIMIT_FACTOR = 3;

/** Radius in map coordinate units (degrees here); scales with zoom automatically. */
function pointRadiusFromBounds(bounds: {
  min_lng: number;
  max_lng: number;
  min_lat: number;
  max_lat: number;
}): number {
  const spanDeg = Math.max(
    bounds.max_lng - bounds.min_lng,
    bounds.max_lat - bounds.min_lat,
    1e-6
  );
  return spanDeg * 0.0015;
}

type LngLatBbox = {
  minLng: number;
  maxLng: number;
  minLat: number;
  maxLat: number;
};

function visibleBbox(vp: WebMercatorViewport, width: number, height: number): LngLatBbox {
  const nw = vp.unproject([0, 0]);
  const se = vp.unproject([width, height]);
  return {
    minLng: Math.min(nw[0], se[0]),
    maxLng: Math.max(nw[0], se[0]),
    minLat: Math.min(nw[1], se[1]),
    maxLat: Math.max(nw[1], se[1])
  };
}

/** Padded bbox for prefetching points beyond the visible viewport. */
function paddedFetchBbox(
  vp: WebMercatorViewport,
  width: number,
  height: number,
  padFactor = PREFETCH_PAD_FACTOR
): LngLatBbox {
  const padX = width * padFactor;
  const padY = height * padFactor;
  const nw = vp.unproject([-padX, -padY]);
  const se = vp.unproject([width + padX, height + padY]);
  return {
    minLng: Math.min(nw[0], se[0]),
    maxLng: Math.max(nw[0], se[0]),
    minLat: Math.min(nw[1], se[1]),
    maxLat: Math.max(nw[1], se[1])
  };
}

function inBbox(p: DecodedPoint, bbox: LngLatBbox): boolean {
  return (
    p.lng >= bbox.minLng &&
    p.lng <= bbox.maxLng &&
    p.lat >= bbox.minLat &&
    p.lat <= bbox.maxLat
  );
}

/** Top-N by rank among points inside the visible viewport. */
function topInViewport(
  points: Iterable<DecodedPoint>,
  bbox: LngLatBbox,
  limit: number
): DecodedPoint[] {
  const inView: DecodedPoint[] = [];
  for (const p of points) {
    if (inBbox(p, bbox)) inView.push(p);
  }
  inView.sort((a, b) => (a.rank !== b.rank ? a.rank - b.rank : a.id.localeCompare(b.id)));
  return inView.slice(0, limit);
}

/** Rank 1 → red; highest rank in the dataset → blue. */
function rankColor(rank: number, datasetRankMax: number): [number, number, number, number] {
  const t =
    datasetRankMax <= 1 ? 0 : Math.min(1, Math.max(0, (rank - 1) / (datasetRankMax - 1)));
  return [Math.round(255 * (1 - t)), 0, Math.round(255 * t), 210];
}

export type ScatterplotViewProps = {
  onBack: () => void;
};

export function ScatterplotView({ onBack }: ScatterplotViewProps) {
  const apiBase = useAppStore((s) => s.apiBase);
  const viewLimit = useAppStore((s) => s.viewLimit);
  const viewState = useAppStore((s) => s.viewState);
  const setViewState = useAppStore((s) => s.setViewState);
  const setViewLimit = useAppStore((s) => s.setViewLimit);

  const [viewPoints, setViewPoints] = useState<DecodedPoint[]>([]);
  const [datasetRankMax, setDatasetRankMax] = useState(1);
  const [pointRadius, setPointRadius] = useState(0.01);
  const pointsCacheRef = useRef<Map<string, DecodedPoint>>(new Map());

  useEffect(() => {
    const ac = new AbortController();
    (async () => {
      try {
        const res = await fetch(`${apiBase}/bounds`, { signal: ac.signal });
        if (!res.ok) return;
        const b = await res.json();
        if (!b.count) return;

        setDatasetRankMax(b.max_rank ?? b.count ?? 1);
        setPointRadius(
          pointRadiusFromBounds({
            min_lng: b.min_lng,
            max_lng: b.max_lng,
            min_lat: b.min_lat,
            max_lat: b.max_lat
          })
        );

        const width = window.innerWidth;
        const height = Math.max(window.innerHeight - 48, 1);
        const vp = new WebMercatorViewport({ width, height });
        const fitted = vp.fitBounds(
          [
            [b.min_lng, b.min_lat],
            [b.max_lng, b.max_lat]
          ],
          { padding: 48 }
        );
        setViewState({
          longitude: fitted.longitude,
          latitude: fitted.latitude,
          zoom: fitted.zoom,
          pitch: 0,
          bearing: 0
        });
      } catch (e) {
        if ((e as Error).name === 'AbortError') return;
      }
    })();
    return () => ac.abort();
  }, [apiBase, setViewState]);

  useEffect(() => {
    pointsCacheRef.current.clear();
    setViewPoints([]);
  }, [apiBase, viewLimit]);

  useEffect(() => {
    const ac = new AbortController();
    const t = window.setTimeout(async () => {
      try {
        const width = window.innerWidth;
        const height = window.innerHeight;
        const vp = new WebMercatorViewport({
          width,
          height,
          longitude: viewState.longitude,
          latitude: viewState.latitude,
          zoom: viewState.zoom,
          pitch: viewState.pitch,
          bearing: viewState.bearing
        });

        const visible = visibleBbox(vp, width, height);
        const fetchBox = paddedFetchBbox(vp, width, height);
        const fetchLimit = Math.min(200_000, viewLimit * PREFETCH_LIMIT_FACTOR);

        const qs = new URLSearchParams({
          minLng: String(fetchBox.minLng),
          minLat: String(fetchBox.minLat),
          maxLng: String(fetchBox.maxLng),
          maxLat: String(fetchBox.maxLat),
          limit: String(fetchLimit)
        });

        const res = await fetch(`${apiBase}/points.pb?${qs.toString()}`, {
          signal: ac.signal
        });
        if (!res.ok) throw new Error(`points.pb ${res.status}`);
        const buf = await res.arrayBuffer();
        const fetched = decodePointsPb(buf);

        const cache = pointsCacheRef.current;
        for (const p of fetched) cache.set(p.id, p);

        for (const id of [...cache.keys()]) {
          const p = cache.get(id)!;
          if (!inBbox(p, fetchBox)) cache.delete(id);
        }

        setViewPoints(topInViewport(cache.values(), visible, viewLimit));
      } catch (e) {
        if ((e as Error).name === 'AbortError') return;
        setViewPoints([]);
      }
    }, 150);

    return () => {
      ac.abort();
      window.clearTimeout(t);
    };
  }, [apiBase, viewLimit, viewState]);

  const layers = useMemo(() => {
    return [
      new ScatterplotLayer({
        id: `molecules-view-${viewLimit}`,
        data: viewPoints,
        getPosition: (d) => [d.lng, d.lat],
        getRadius: pointRadius,
        radiusUnits: 'common',
        radiusMinPixels: 0.35,
        radiusMaxPixels: 1.5,
        getFillColor: (d) => rankColor(d.rank, datasetRankMax),
        opacity: 1,
        pickable: false,
        updateTriggers: {
          data: viewPoints,
          getFillColor: datasetRankMax,
          getRadius: pointRadius
        }
      })
    ];
  }, [viewLimit, viewPoints, datasetRankMax, pointRadius]);

  const btnStyle: CSSProperties = {
    padding: '6px 12px',
    fontSize: 13,
    fontWeight: 500,
    border: '1px solid #ccc',
    borderRadius: 6,
    background: '#f8f8f8',
    cursor: 'pointer'
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div
        style={{
          padding: '8px 12px',
          display: 'flex',
          gap: 12,
          alignItems: 'center',
          borderBottom: '1px solid #eee',
          background: '#fff',
          position: 'relative',
          zIndex: 10
        }}
      >
        <button type="button" style={btnStyle} onClick={onBack}>
          ← Dataset & embedding
        </button>
        <div style={{ fontWeight: 600 }}>Molecule Map</div>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span>top in view</span>
          <input
            type="range"
            min={100}
            max={100_000}
            step={100}
            value={viewLimit}
            onChange={(e) => setViewLimit(Number(e.target.value))}
            onPointerDown={(e) => e.stopPropagation()}
            onPointerMove={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
            onMouseMove={(e) => e.stopPropagation()}
            onTouchStart={(e) => e.stopPropagation()}
            onTouchMove={(e) => e.stopPropagation()}
          />
          <span style={{ width: 64, textAlign: 'right' }}>{viewLimit.toLocaleString()}</span>
        </label>
        <div style={{ marginLeft: 'auto', color: '#666', fontSize: 12 }}>
          Showing top {viewPoints.length.toLocaleString()} of {viewLimit.toLocaleString()} · {apiBase}
        </div>
      </div>

      <div style={{ flex: 1, position: 'relative' }}>
        <DeckGL
          views={new MapView({ repeat: true })}
          controller={true}
          initialViewState={viewState}
          viewState={viewState}
          onViewStateChange={(e) => setViewState(e.viewState as any)}
          layers={layers}
        />
      </div>
    </div>
  );
}
