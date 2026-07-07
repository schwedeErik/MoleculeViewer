/** WebMercator slippy-map helpers for drawing tile outlines. */

export type TileIndex = { z: number; x: number; y: number };

export type TileOutline = TileIndex & {
  path: [number, number][];
  label: string;
};

/** Tile bbox as [west, south, east, north] in WGS84 degrees. */
export function tileToBBox(x: number, y: number, z: number): [number, number, number, number] {
  const n = 2 ** z;
  const west = (x / n) * 360 - 180;
  const east = ((x + 1) / n) * 360 - 180;
  const north =
    (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / n))) * 180) / Math.PI;
  const south =
    (Math.atan(Math.sinh(Math.PI * (1 - (2 * (y + 1)) / n))) * 180) / Math.PI;
  return [west, south, east, north];
}

function lngLatToTile(lng: number, lat: number, z: number): { x: number; y: number } {
  const n = 2 ** z;
  const x = Math.floor(((lng + 180) / 360) * n);
  const latRad = (lat * Math.PI) / 180;
  const y = Math.floor(
    ((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) * n
  );
  return {
    x: Math.max(0, Math.min(n - 1, x)),
    y: Math.max(0, Math.min(n - 1, y))
  };
}

export function tileOutline(x: number, y: number, z: number): [number, number][] {
  const [west, south, east, north] = tileToBBox(x, y, z);
  return [
    [west, south],
    [east, south],
    [east, north],
    [west, north],
    [west, south]
  ];
}

/** Tiles intersecting a lng/lat bounding box at integer zoom z. */
export function tilesInBBox(
  minLng: number,
  minLat: number,
  maxLng: number,
  maxLat: number,
  z: number
): TileIndex[] {
  const n = 2 ** z;
  const nw = lngLatToTile(minLng, maxLat, z);
  const se = lngLatToTile(maxLng, minLat, z);
  const tiles: TileIndex[] = [];
  for (let x = nw.x; x <= se.x; x++) {
    for (let y = nw.y; y <= se.y; y++) {
      tiles.push({ z, x, y });
    }
  }
  // Fallback if viewport is degenerate
  if (tiles.length === 0) {
    tiles.push({ z, x: Math.min(n - 1, nw.x), y: Math.min(n - 1, nw.y) });
  }
  return tiles;
}

export function visibleTileOutlines(
  bounds: [number, number, number, number],
  zoom: number
): TileOutline[] {
  const z = Math.max(0, Math.min(23, Math.floor(zoom)));
  const [minLng, minLat, maxLng, maxLat] = bounds;
  return tilesInBBox(minLng, minLat, maxLng, maxLat, z).map(({ z, x, y }) => ({
    z,
    x,
    y,
    path: tileOutline(x, y, z),
    label: `${z}/${x}/${y}`
  }));
}
