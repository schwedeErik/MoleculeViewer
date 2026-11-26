import { useEffect, useId, useRef, useState } from 'react';
import SmilesDrawer from 'smiles-drawer';

type SmilesStructureProps = {
  smiles: string;
  width: number;
  height: number;
  alt?: string;
};

/** Client-side 2D structure from SMILES (no backend / RDKit). */
export function SmilesStructure({ smiles, width, height, alt }: SmilesStructureProps) {
  const reactId = useId();
  const svgId = `smiles-${reactId.replace(/:/g, '')}`;
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [error, setError] = useState(false);

  // Tile SMILES can carry trailing whitespace (e.g. a newline from the CSV export),
  // which smiles-drawer rejects; trim before parsing.
  const cleaned = smiles.trim();

  useEffect(() => {
    setError(false);
    const el = svgRef.current;
    if (!el || !cleaned) {
      setError(true);
      return;
    }
    el.replaceChildren();
    const drawer = new SmilesDrawer.SvgDrawer({ width, height });
    SmilesDrawer.parse(
      cleaned,
      (tree: unknown) => {
        try {
          drawer.draw(tree, el, 'light');
        } catch {
          setError(true);
        }
      },
      () => setError(true)
    );
  }, [cleaned, width, height]);

  return (
    <div style={{ position: 'relative', width, height }}>
      <svg
        ref={svgRef}
        id={svgId}
        width={width}
        height={height}
        role="img"
        aria-label={alt ?? 'Molecule structure'}
        style={{ display: 'block', background: '#fff', visibility: error ? 'hidden' : 'visible' }}
      />
      {error && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#888',
            fontSize: 12
          }}
        >
          No structure available
        </div>
      )}
    </div>
  );
}
