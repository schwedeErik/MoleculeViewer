import { MVTLayer } from '@deck.gl/geo-layers';
import { load } from '@loaders.gl/core';
import { MVTLoader } from '@loaders.gl/mvt';
import { PMTiles } from 'pmtiles';
import { DEFAULT_LOD_LEVEL, rankMaxForZoom } from './rankLod';

type MoleculeMVTLayerProps = {
  moleculeApiBase: string;
  datasetSlug: string;
  datasetRankMax: number;
  lodLevel: number;
  /** When set, tiles are read from this PMTiles archive instead of live PostGIS. */
  pmtilesUrl: string | null;
};

const pmtilesCache = new Map<string, PMTiles>();

function getPmtiles(url: string): PMTiles {
  let archive = pmtilesCache.get(url);
  if (!archive) {
    archive = new PMTiles(url);
    pmtilesCache.set(url, archive);
  }
  return archive;
}

/**
 * MVT tiles with server-side rank filtering per tile zoom level.
 * Uses a precomputed PMTiles archive when ``pmtilesUrl`` is set; otherwise hits
 * the live ``/tiles`` endpoint with ``rank_max`` from the LOD curve.
 */
export class MoleculeMVTLayer extends MVTLayer {
  static layerName = 'MoleculeMVTLayer';

  static defaultProps = {
    ...MVTLayer.defaultProps,
    moleculeApiBase: '',
    datasetSlug: '',
    datasetRankMax: 1,
    lodLevel: DEFAULT_LOD_LEVEL,
    pmtilesUrl: null
  };

  getTileData(loadProps: {
    index: { z: number; x: number; y: number };
    signal?: AbortSignal;
  }) {
    const { index, signal } = loadProps;
    const { z, x, y } = index;
    const {
      moleculeApiBase,
      datasetSlug,
      datasetRankMax,
      lodLevel,
      pmtilesUrl,
      fetch
    } = this.props as typeof this.props & MoleculeMVTLayerProps;

    const { binary } = this.state;
    let loadOptions = this.getLoadOptions();
    loadOptions = {
      ...loadOptions,
      mimeType: 'application/x-protobuf',
      mvt: {
        ...loadOptions?.mvt,
        coordinates: this.context.viewport.resolution ? 'wgs84' : 'local',
        tileIndex: index
      },
      gis: binary ? { format: 'binary' } : {}
    };

    if (pmtilesUrl) {
      return getPmtiles(pmtilesUrl)
        .getZxy(z, x, y, signal)
        .then((entry) => {
          if (!entry?.data || signal?.aborted) {
            return null;
          }
          return load(entry.data, MVTLoader, loadOptions);
        });
    }

    const rank_max = rankMaxForZoom(z, datasetRankMax, lodLevel);
    const url =
      `${moleculeApiBase}/tiles/${z}/${x}/${y}.mvt` +
      `?dataset=${encodeURIComponent(datasetSlug)}&rank_max=${rank_max}`;
    return fetch!(url, { propName: 'data', layer: this, loadOptions, signal });
  }
}

export type { MoleculeMVTLayerProps };
