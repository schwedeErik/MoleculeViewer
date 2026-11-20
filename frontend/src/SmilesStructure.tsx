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

  useEffect(() => {
    setError(false);
    const el = svgRef.current;
    if (!el || !smiles.trim()) {
      setError(true);
      return;
    }
    el.replaceChildren();
    const drawer = new SmilesDrawer.SvgDrawer({ width, height });
    SmilesDrawer.parse(
      smiles,
      (tree: unknown) => {
        try {
          drawer.draw(tree, el, 'light');
        } catch {
          setError(true);
        }
      },
      () => setError(true)
    );
  }, [smiles, width, height]);

  if (error) {
    return (
      <div
        style={{
          width,
          height,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#888',
          fontSize: 12
        }}
      >
        No structure available
      </div>
    );
  }

  return (
    <svg
      ref={svgRef}
      id={svgId}
      width={width}
      height={height}
      role="img"
      aria-label={alt ?? 'Molecule structure'}
      style={{ display: 'block', background: '#fff' }}
    />
  );
}
