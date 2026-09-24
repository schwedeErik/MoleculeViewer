export type DatasetInfo = {
  id: number;
  slug: string;
  name: string;
  embedding_method: string;
  embedding_dim: number;
  molecule_count: number;
  /** LOD steps 1–6 that have a precomputed PMTiles archive. */
  precomputed_lods?: number[];
};

export function embeddingMethodLabel(method: string): string {
  switch (method) {
    case 'maccs':
      return 'MACCS fingerprints + UMAP';
    case 'morgan':
      return 'Morgan fingerprints + UMAP';
    case 'chembert':
      return 'ChemBERTa + UMAP';
    default:
      return `${method} + UMAP`;
  }
}
