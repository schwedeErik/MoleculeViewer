import DeckGL from '@deck.gl/react';
import { MapView, WebMercatorViewport } from '@deck.gl/core';
import { PathLayer, TextLayer } from '@deck.gl/layers';
import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { useAppStore } from './store';
import {
  LOD_STEP_COUNT,
  aggressivenessForLodLevel,
  clampLodLevel,
  labelForLodLevel,
  lodParamsForAggressiveness,
  rankMaxForZoom
} from './rankLod';
import { MoleculeMVTLayer } from './MoleculeMVTLayer';
import { visibleTileOutlines } from './tileGrid';
import type { DatasetInfo } from './types';

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
  const datasetSlug = useAppStore((s) => s.datasetSlug);
  const setDatasetSlug = useAppStore((s) => s.setDatasetSlug);
  const lodLevel = useAppStore((s) => s.lodLevel);
  const setLodLevel = useAppStore((s) => s.setLodLevel);
  const viewState = useAppStore((s) => s.viewState);
  const setViewState = useAppStore((s) => s.setViewState);

  const [datasetRankMax, setDatasetRankMax] = useState(1);
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [pointRadius, setPointRadius] = useState(0.01);
  const [showTileGrid, setShowTileGrid] = useState(false);
  /** Prefer precomputed PMTiles when available; off = live PostGIS MVT. */
  const [preferPmtiles, setPreferPmtiles] = useState(true);

  const tileZ = Math.floor(viewState.zoom);
  const activeRankMax = rankMaxForZoom(viewState.zoom, datasetRankMax, lodLevel);
  const lodParams = lodParamsForAggressiveness(aggressivenessForLodLevel(lodLevel));
  const activeDataset = datasets.find((d) => d.slug === datasetSlug);
  const lodLabel = labelForLodLevel(lodLevel);
  const pmtilesAvailable = Boolean(
    datasetSlug && activeDataset?.precomputed_lods?.includes(lodLevel)
  );
  const usingPrecomputed = preferPmtiles && pmtilesAvailable;
  const pmtilesUrl =
    usingPrecomputed && datasetSlug
      ? `${apiBase}/datasets/${encodeURIComponent(datasetSlug)}/pmtiles/${lodLevel}.pmtiles`
      : null;

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
    if (!datasetSlug) return;
    const ac = new AbortController();
    (async () => {
      try {
        const res = await fetch(
          `${apiBase}/bounds?dataset=${encodeURIComponent(datasetSlug)}`,
          { signal: ac.signal }
        );
        if (!res.ok) return;
        const b = await res.json();
        if (!b.count) return;

        const maxRank = b.max_rank ?? b.count ?? 1;
        setDatasetRankMax(maxRank);
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
  }, [apiBase, datasetSlug, setViewState]);

  const tileOutlines = useMemo(() => {
    if (!showTileGrid) return [];
    const width = window.innerWidth;
    const height = Math.max(window.innerHeight - 48, 1);
    const vp = new WebMercatorViewport({
      width,
      height,
      longitude: viewState.longitude,
      latitude: viewState.latitude,
      zoom: viewState.zoom,
      pitch: viewState.pitch,
      bearing: viewState.bearing
    });
    return visibleTileOutlines(vp.getBounds(), tileZ);
  }, [showTileGrid, viewState, tileZ]);

  const tileParamsKey = `${datasetSlug}:${lodLevel}:${usingPrecomputed ? 'pmtiles' : 'live'}`;

  const moleculeLayer = useMemo(() => {
    if (!datasetSlug) return null;
    // Dummy query param busts cache when LOD/dataset/source change; rank_max is set per tile in getTileData.
    const tileData = `${apiBase}/tiles/{z}/{x}/{y}.mvt?_k=${tileParamsKey}`;

    return new MoleculeMVTLayer({
      id: 'molecules-mvt',
      data: tileData,
      moleculeApiBase: apiBase,
      datasetSlug,
      datasetRankMax,
      lodLevel,
      pmtilesUrl,
      binary: false,
      minZoom: 0,
      maxZoom: 23,
      refinementStrategy: 'best-available',
      maxRequests: 12,
      maxCacheSize: 128,
      pickable: false,
      stroked: false,
      filled: true,
      pointType: 'circle',
      getPointRadius: pointRadius,
      pointRadiusUnits: 'common',
      pointRadiusMinPixels: 0.35,
      pointRadiusMaxPixels: 1.5,
      getFillColor: (f: { properties?: { rank?: number } }) => {
        const rank = Number(f.properties?.rank ?? 1);
        return rankColor(rank, datasetRankMax);
      },
      updateTriggers: {
        getFillColor: datasetRankMax,
        getPointRadius: pointRadius
      }
    } as ConstructorParameters<typeof MoleculeMVTLayer>[0]);
  }, [
    apiBase,
    datasetSlug,
    tileParamsKey,
    datasetRankMax,
    lodLevel,
    pmtilesUrl,
    pointRadius
  ]);

  const layers = useMemo(() => {
    if (!moleculeLayer) return [];
    if (!showTileGrid) return [moleculeLayer];

    const outlineLayer = new PathLayer({
      id: 'tile-outlines',
      data: tileOutlines,
      getPath: (d) => d.path,
      getColor: [0, 0, 0, 220],
      getWidth: 2,
      widthUnits: 'pixels',
      pickable: false
    });

    const labelLayer = new TextLayer({
      id: 'tile-labels',
      data: tileOutlines,
      getPosition: (d) => {
        const lngs = d.path.map((p: [number, number]) => p[0]);
        const lats = d.path.map((p: [number, number]) => p[1]);
        return [
          (Math.min(...lngs) + Math.max(...lngs)) / 2,
          (Math.min(...lats) + Math.max(...lats)) / 2
        ];
      },
      getText: (d) => d.label,
      getSize: 12,
      getColor: [0, 0, 0, 200],
      fontFamily: 'monospace',
      pickable: false
    });

    return [moleculeLayer, outlineLayer, labelLayer];
  }, [moleculeLayer, showTileGrid, tileOutlines]);

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
    onMouseMove: (e) => e.stopPropagation(),
    onTouchStart: (e) => e.stopPropagation(),
    onTouchMove: (e) => e.stopPropagation()
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
                </option>
              ))}
            </select>
          </label>
        )}
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
          <span style={{ width: 72, textAlign: 'right' }}>
            {lodLevel}/{LOD_STEP_COUNT} {lodLabel}
          </span>
        </label>
        <label
          style={{
            display: 'flex',
            gap: 6,
            alignItems: 'center',
            fontSize: 13,
            opacity: pmtilesAvailable ? 1 : 0.5
          }}
          title={
            pmtilesAvailable
              ? 'Use precomputed PMTiles instead of live database MVT tiles'
              : 'No precomputed PMTiles for this dataset/LOD'
          }
        >
          <input
            type="checkbox"
            checked={preferPmtiles && pmtilesAvailable}
            disabled={!pmtilesAvailable}
            onChange={(e) => setPreferPmtiles(e.target.checked)}
          />
          PMTiles
        </label>
        <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 13 }}>
          <input
            type="checkbox"
            checked={showTileGrid}
            onChange={(e) => setShowTileGrid(e.target.checked)}
          />
          tile grid
        </label>
        <div style={{ marginLeft: 'auto', color: '#666', fontSize: 12 }}>
          {activeDataset?.name ?? datasetSlug} · LOD {lodLevel} ({lodLabel}) · rank ≤{' '}
          {activeRankMax.toLocaleString()}
          {lodLevel < LOD_STEP_COUNT
            ? ` (${lodParams.base.toLocaleString()}×${lodParams.growth}^z)`
            : ' (all points)'}{' '}
          · {usingPrecomputed ? 'pmtiles' : 'live'} · z={tileZ}
        </div>
      </div>

      <div style={{ flex: 1, position: 'relative' }}>
        <DeckGL
          views={new MapView({ repeat: true })}
          controller={true}
          initialViewState={viewState}
          viewState={viewState}
          onViewStateChange={(e) => setViewState(e.viewState as typeof viewState)}
          layers={layers}
        />
      </div>
    </div>
  );
}
