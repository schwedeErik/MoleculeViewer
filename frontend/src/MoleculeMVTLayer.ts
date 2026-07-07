import { MVTLayer } from '@deck.gl/geo-layers';
import { effectiveRankMax } from './rankLod';

type MoleculeMVTLayerProps = {
  moleculeApiBase: string;
  datasetSlug: string;
  rankCap: number;
  datasetRankMax: number;
  zoomLodAggressiveness: number;
};

/**
 * MVT tiles with server-side rank filtering per tile zoom level.
 * The `data` template stays stable while panning/zooming so deck.gl keeps its cache;
 * each tile requests `rank_max` from the LOD curve at that tile's z.
 */
export class MoleculeMVTLayer extends MVTLayer {
  static layerName = 'MoleculeMVTLayer';

  static defaultProps = {
    ...MVTLayer.defaultProps,
    moleculeApiBase: '',
    datasetSlug: '',
    rankCap: 1,
    datasetRankMax: 1,
    zoomLodAggressiveness: 50
  };

  getTileData(loadProps: { index: { z: number; x: number; y: number }; signal?: AbortSignal }) {
    const { index, signal } = loadProps;
    const { z, x, y } = index;
    const { moleculeApiBase, datasetSlug, rankCap, datasetRankMax, zoomLodAggressiveness, fetch } =
      this.props as typeof this.props & MoleculeMVTLayerProps;
    const rank_max = effectiveRankMax(
      z,
      datasetRankMax,
      rankCap,
      zoomLodAggressiveness
    );
    const url =
      `${moleculeApiBase}/tiles/${z}/${x}/${y}.mvt` +
      `?dataset=${encodeURIComponent(datasetSlug)}&rank_max=${rank_max}`;

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
    return fetch!(url, { propName: 'data', layer: this, loadOptions, signal });
  }
}

export type { MoleculeMVTLayerProps };
