import DeckGL from '@deck.gl/react';
import { MapView, WebMercatorViewport } from '@deck.gl/core';
import { ScatterplotLayer } from '@deck.gl/layers';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useAppStore } from './store';
import { decodePointsPb, type DecodedPoint } from './proto';

function rankColor(rank: number): [number, number, number, number] {
  if (rank <= 1) return [0, 200, 255, 220];
  if (rank === 2) return [0, 255, 120, 210];
  if (rank === 3) return [255, 200, 0, 200];
  return [255, 255, 255, 160];
}

export function App() {
  const apiBase = useAppStore((s) => s.apiBase);
  const rankMax = useAppStore((s) => s.rankMax);
  const viewLimit = useAppStore((s) => s.viewLimit);
  const viewState = useAppStore((s) => s.viewState);
  const setViewState = useAppStore((s) => s.setViewState);
  const setRankMax = useAppStore((s) => s.setRankMax);
  const setViewLimit = useAppStore((s) => s.setViewLimit);

  const cacheRef = useRef<Map<string, DecodedPoint>>(new Map());
  const stickyIdsRef = useRef<Set<string>>(new Set());
  const prevZoomRef = useRef<number>(viewState.zoom);
  const [viewPoints, setViewPoints] = useState<DecodedPoint[]>([]);

  useEffect(() => {
    // Fetch points for the *current viewport* with a single global limit.
    // This makes the "limit" apply to the view, not each tile.
    const ac = new AbortController();
    const t = window.setTimeout(async () => {
      try {
        // If the user zooms out, reset stickiness so the set can
        // re-balance for the larger viewport (keeps max/view meaningful).
        if (viewState.zoom < prevZoomRef.current - 0.001) {
          stickyIdsRef.current.clear();
        }
        prevZoomRef.current = viewState.zoom;

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

        // Add a padding so small pans don't immediately churn the set.
        // (We still only *render* points inside the real viewport.)
        const pad = 200;
        const nw = vp.unproject([pad, pad]);
        const se = vp.unproject([width - pad, height - pad]);
        const minLng = Math.min(nw[0], se[0]);
        const maxLng = Math.max(nw[0], se[0]);
        const minLat = Math.min(nw[1], se[1]);
        const maxLat = Math.max(nw[1], se[1]);

        const qs = new URLSearchParams({
          minLng: String(minLng),
          minLat: String(minLat),
          maxLng: String(maxLng),
          maxLat: String(maxLat),
          limit: String(viewLimit),
          rank_max: String(rankMax)
        });

        const res = await fetch(`${apiBase}/points.pb?${qs.toString()}`, {
          signal: ac.signal
        });
        if (!res.ok) throw new Error(`points.pb ${res.status}`);
        const buf = await res.arrayBuffer();
        const fetched = decodePointsPb(buf);
        for (const p of fetched) cacheRef.current.set(p.id, p);

        // Now build a *stable* set for the current visible viewport.
        const vnw = vp.unproject([0, 0]);
        const vse = vp.unproject([width, height]);
        const vMinLng = Math.min(vnw[0], vse[0]);
        const vMaxLng = Math.max(vnw[0], vse[0]);
        const vMinLat = Math.min(vnw[1], vse[1]);
        const vMaxLat = Math.max(vnw[1], vse[1]);

        const inView: DecodedPoint[] = [];
        for (const p of cacheRef.current.values()) {
          if (p.lng < vMinLng || p.lng > vMaxLng || p.lat < vMinLat || p.lat > vMaxLat) continue;
          if (p.rank > rankMax) continue;
          inView.push(p);
        }

        const byRankThenId = (a: DecodedPoint, b: DecodedPoint) =>
          a.rank !== b.rank ? a.rank - b.rank : a.id.localeCompare(b.id);

        const sticky: DecodedPoint[] = [];
        const nonSticky: DecodedPoint[] = [];
        for (const p of inView) {
          (stickyIdsRef.current.has(p.id) ? sticky : nonSticky).push(p);
        }
        sticky.sort(byRankThenId);
        nonSticky.sort(byRankThenId);

        const selected: DecodedPoint[] = [];
        for (const p of sticky) {
          selected.push(p);
          if (selected.length >= viewLimit) break;
        }
        if (selected.length < viewLimit) {
          for (const p of nonSticky) {
            selected.push(p);
            if (selected.length >= viewLimit) break;
          }
        }

        stickyIdsRef.current = new Set(selected.map((p) => p.id));
        setViewPoints(selected);
      } catch (e) {
        if ((e as any)?.name === 'AbortError') return;
        // If backend is down, just clear overlay.
        setViewPoints([]);
      }
    }, 150);

    return () => {
      ac.abort();
      window.clearTimeout(t);
    };
    // When the user changes filters/limits, reset the sticky set so it
    // doesn't "lock in" a previous configuration.
  }, [apiBase, rankMax, viewLimit, viewState]);

  useEffect(() => {
    cacheRef.current.clear();
    stickyIdsRef.current.clear();
    setViewPoints([]);
  }, [apiBase, rankMax, viewLimit]);

  const layers = useMemo(() => {
    return [
      new ScatterplotLayer({
        id: `molecules-view-${rankMax}-${viewLimit}`,
        data: viewPoints,
        getPosition: (d) => [d.lng, d.lat],
        getRadius: 2,
        radiusUnits: 'pixels',
        radiusMinPixels: 1,
        radiusMaxPixels: 4,
        getFillColor: (d) => rankColor(d.rank),
        opacity: 1,
        pickable: false,
        updateTriggers: {
          data: viewPoints
        }
      })
    ];
  }, [rankMax, viewLimit, viewPoints]);

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
        <div style={{ fontWeight: 600 }}>Molecule Map</div>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span>rank ≤</span>
          <input
            type="range"
            min={1}
            max={10}
            value={rankMax}
            onChange={(e) => setRankMax(Number(e.target.value))}
            onPointerDown={(e) => e.stopPropagation()}
            onPointerMove={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
            onMouseMove={(e) => e.stopPropagation()}
            onTouchStart={(e) => e.stopPropagation()}
            onTouchMove={(e) => e.stopPropagation()}
          />
          <span style={{ width: 18, textAlign: 'right' }}>{rankMax}</span>
        </label>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span>max/view</span>
          <input
            type="range"
            min={1000}
            max={200000}
            step={1000}
            value={viewLimit}
            onChange={(e) => setViewLimit(Number(e.target.value))}
            onPointerDown={(e) => e.stopPropagation()}
            onPointerMove={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
            onMouseMove={(e) => e.stopPropagation()}
            onTouchStart={(e) => e.stopPropagation()}
            onTouchMove={(e) => e.stopPropagation()}
          />
          <span style={{ width: 64, textAlign: 'right' }}>
            {viewLimit.toLocaleString()}
          </span>
        </label>
        <div style={{ marginLeft: 'auto', color: '#666', fontSize: 12 }}>
          Rendering points from {apiBase}
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

