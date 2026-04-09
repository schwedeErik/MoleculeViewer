import { parse } from 'protobufjs';

const PROTO = `
syntax = "proto3";
package molecule;
message Point { int64 id = 1; double lng = 2; double lat = 3; int32 rank = 4; }
message Points { repeated Point points = 1; }
`;

const root = parse(PROTO).root;
const PointsType = root.lookupType('molecule.Points');

export type DecodedPoint = { id: string; lng: number; lat: number; rank: number };

export function decodePointsPb(buf: ArrayBuffer): DecodedPoint[] {
  const msg = PointsType.decode(new Uint8Array(buf)) as any;
  const pts = (msg.points ?? []) as any[];
  return pts.map((p) => ({
    // int64 becomes Long-like; stringify for safety
    id: String(p.id),
    lng: Number(p.lng),
    lat: Number(p.lat),
    rank: Number(p.rank ?? 1)
  }));
}

