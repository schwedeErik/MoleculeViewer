"""Render 2D structure depictions (SVG) from SMILES with RDKit."""

from __future__ import annotations

from functools import lru_cache

MIN_SIZE = 64
MAX_SIZE = 800


def clamp_size(value: int) -> int:
    return max(MIN_SIZE, min(MAX_SIZE, int(value)))


@lru_cache(maxsize=4096)
def smiles_to_svg(smiles: str, width: int = 240, height: int = 180) -> str | None:
    """Return an SVG depiction of ``smiles``, or ``None`` if RDKit cannot parse it.

    RDKit is imported lazily so the API can start without loading it.
    """
    from rdkit import Chem
    from rdkit.Chem.Draw import rdMolDraw2D

    mol = Chem.MolFromSmiles(smiles.strip())
    if mol is None:
        return None

    drawer = rdMolDraw2D.MolDraw2DSVG(clamp_size(width), clamp_size(height))
    options = drawer.drawOptions()
    options.clearBackground = False  # transparent, so the caller picks the background
    rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol)
    drawer.FinishDrawing()
    return drawer.GetDrawingText()
