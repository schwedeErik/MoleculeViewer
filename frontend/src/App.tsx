import { useState, type CSSProperties } from 'react';
import { ScatterplotView } from './ScatterplotView';

const PLACEHOLDER_DATASETS = [
  { value: 'zinc15-sample', label: 'ZINC15 (sample)' },
  { value: 'chembl-lite', label: 'ChEMBL (placeholder)' }
];

const PLACEHOLDER_EMBEDDINGS = [
  { value: 'umap-default', label: 'UMAP (default)' },
  { value: 'pca-2d', label: 'PCA 2D (placeholder)' }
];

export function App() {
  const [screen, setScreen] = useState<'setup' | 'scatterplot'>('setup');
  const [dataset, setDataset] = useState(PLACEHOLDER_DATASETS[0].value);
  const [embeddingStyle, setEmbeddingStyle] = useState(
    PLACEHOLDER_EMBEDDINGS[0].value
  );

  if (screen === 'scatterplot') {
    return <ScatterplotView onBack={() => setScreen('setup')} />;
  }

  const fieldStyle = {
    display: 'flex' as const,
    flexDirection: 'column' as const,
    gap: 6,
    minWidth: 280
  };

  const labelStyle = { fontSize: 13, fontWeight: 600, color: '#333' };

  const selectStyle: CSSProperties = {
    padding: '10px 12px',
    fontSize: 14,
    border: '1px solid #ccc',
    borderRadius: 6,
    background: '#fff'
  };

  const primaryBtn: CSSProperties = {
    marginTop: 8,
    padding: '10px 20px',
    fontSize: 15,
    fontWeight: 600,
    border: 'none',
    borderRadius: 6,
    background: '#1a73e8',
    color: '#fff',
    cursor: 'pointer'
  };

  return (
    <div
      style={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
        background: 'linear-gradient(180deg, #f5f7fa 0%, #e8ecf1 100%)'
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: 420,
          padding: 28,
          borderRadius: 12,
          background: '#fff',
          boxShadow: '0 4px 24px rgba(0,0,0,0.08)',
          border: '1px solid #e8e8e8'
        }}
      >
        <h1 style={{ margin: '0 0 8px', fontSize: 22, fontWeight: 700, color: '#1a1a1a' }}>
          Molecule Map
        </h1>
        <p style={{ margin: '0 0 24px', fontSize: 14, color: '#666', lineHeight: 1.5 }}>
          Choose a dataset and embedding style (placeholders for now), then open the
          scatterplot view.
        </p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <div style={fieldStyle}>
            <label htmlFor="dataset" style={labelStyle}>
              Dataset
            </label>
            <select
              id="dataset"
              value={dataset}
              onChange={(e) => setDataset(e.target.value)}
              style={selectStyle}
            >
              {PLACEHOLDER_DATASETS.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </select>
          </div>

          <div style={fieldStyle}>
            <label htmlFor="embedding" style={labelStyle}>
              Embedding style
            </label>
            <select
              id="embedding"
              value={embeddingStyle}
              onChange={(e) => setEmbeddingStyle(e.target.value)}
              style={selectStyle}
            >
              {PLACEHOLDER_EMBEDDINGS.map((e) => (
                <option key={e.value} value={e.value}>
                  {e.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <button
          type="button"
          style={primaryBtn}
          onClick={() => setScreen('scatterplot')}
        >
          Open scatterplot
        </button>
      </div>
    </div>
  );
}
