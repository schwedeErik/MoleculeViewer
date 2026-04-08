import DeckGL from '@deck.gl/react';
import { MapView } from '@deck.gl/core';
import { MVTLayer } from '@deck.gl/geo-layers';
import { useMemo } from 'react';
import { useAppStore } from './store';

export function App() {
  const apiBase = useAppStore((s) => s.apiBase);
  const rankMax = useAppStore((s) => s.rankMax);
  const tileLimit = useAppStore((s) => s.tileLimit);
  const viewState = useAppStore((s) => s.viewState);
  const setViewState = useAppStore((s) => s.setViewState);
  const setRankMax = useAppStore((s) => s.setRankMax);
  const setTileLimit = useAppStore((s) => s.setTileLimit);

  const layers = useMemo(() => {
    return [
      new MVTLayer({
        // Include rankMax in the id so deck.gl drops tile cache
        // and refetches tiles when the slider changes.
        id: `molecules-mvt-${rankMax}-${tileLimit}`,
        data: `${apiBase}/tiles/{z}/{x}/{y}.mvt?rank_max=${rankMax}&limit=${tileLimit}`,
        minZoom: 0,
        maxZoom: 22,
        binary: true,
        getFillColor: (f) => {
          const rank = Number((f as any).properties?.rank ?? 1);
          if (rank <= 1) return [0, 200, 255, 200];
          if (rank === 2) return [0, 255, 120, 180];
          if (rank === 3) return [255, 200, 0, 160];
          return [255, 255, 255, 120];
        },
        pointRadiusMinPixels: 1,
        pointRadiusMaxPixels: 6,
        pointRadiusUnits: 'pixels',
        getPointRadius: 2,
        pickable: true
      })
    ];
  }, [apiBase, rankMax, tileLimit]);

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
          <span>max/tile</span>
          <input
            type="range"
            min={1000}
            max={200000}
            step={1000}
            value={tileLimit}
            onChange={(e) => setTileLimit(Number(e.target.value))}
            onPointerDown={(e) => e.stopPropagation()}
            onPointerMove={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
            onMouseMove={(e) => e.stopPropagation()}
            onTouchStart={(e) => e.stopPropagation()}
            onTouchMove={(e) => e.stopPropagation()}
          />
          <span style={{ width: 64, textAlign: 'right' }}>
            {tileLimit.toLocaleString()}
          </span>
        </label>
        <div style={{ marginLeft: 'auto', color: '#666', fontSize: 12 }}>
          Rendering MVT tiles from {apiBase}
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

