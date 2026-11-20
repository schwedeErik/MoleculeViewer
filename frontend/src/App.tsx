import { useCallback, useEffect, useState, type CSSProperties } from 'react';
import { isStatic, loadDatasetsCatalog } from './config';
import { DeepscatterView } from './DeepscatterView';
import { useAppStore } from './store';
import { embeddingMethodLabel, type DatasetInfo } from './types';

export function App() {
  const datasetSlug = useAppStore((s) => s.datasetSlug);
  const setDatasetSlug = useAppStore((s) => s.setDatasetSlug);

  const [screen, setScreen] = useState<'setup' | 'map'>('setup');
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [selectedSlug, setSelectedSlug] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadDatasets = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await loadDatasetsCatalog();
      setDatasets(data);
      setSelectedSlug((prev) => {
        if (prev && data.some((d) => d.slug === prev)) return prev;
        if (datasetSlug && data.some((d) => d.slug === datasetSlug)) return datasetSlug;
        return data[0]?.slug ?? '';
      });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [datasetSlug]);

  useEffect(() => {
    void loadDatasets();
  }, [loadDatasets]);

  const selectedDataset = datasets.find((d) => d.slug === selectedSlug);

  if (screen === 'map' && datasetSlug) {
    return <DeepscatterView onBack={() => setScreen('setup')} />;
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

  const canOpen =
    !loading &&
    !error &&
    selectedSlug &&
    (selectedDataset?.molecule_count ?? 0) > 0 &&
    (selectedDataset?.deepscatter_orders?.length ?? 0) > 0;

  return (
    <div
      style={{
        minHeight: '100%',
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
          {isStatic
            ? 'Static Deepscatter demo (quadfeather tiles). Structure hover needs the full app with a backend.'
            : 'Choose a dataset with Deepscatter tiles and open the map.'}
        </p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <div style={fieldStyle}>
            <label htmlFor="dataset" style={labelStyle}>
              Dataset
            </label>
            {loading ? (
              <div style={{ fontSize: 14, color: '#666' }}>Loading datasets…</div>
            ) : error ? (
              <div style={{ fontSize: 14, color: '#c5221f' }}>{error}</div>
            ) : datasets.length === 0 ? (
              <div style={{ fontSize: 14, color: '#666' }}>No datasets available.</div>
            ) : (
              <select
                id="dataset"
                value={selectedSlug}
                onChange={(e) => setSelectedSlug(e.target.value)}
                style={selectStyle}
              >
                {datasets.map((d) => (
                  <option key={d.slug} value={d.slug}>
                    {d.name} ({d.molecule_count.toLocaleString()} molecules)
                  </option>
                ))}
              </select>
            )}
          </div>

          {selectedDataset && (
            <div style={{ fontSize: 13, color: '#555', lineHeight: 1.5 }}>
              <div>
                <strong>Embedding:</strong>{' '}
                {embeddingMethodLabel(selectedDataset.embedding_method)}
              </div>
              <div>
                <strong>Slug:</strong> {selectedDataset.slug}
              </div>
              <div>
                <strong>Deepscatter tiles:</strong>{' '}
                {(selectedDataset.deepscatter_orders?.length ?? 0) > 0
                  ? selectedDataset.deepscatter_orders!.join(', ')
                  : 'not built yet'}
              </div>
            </div>
          )}
        </div>

        <button
          type="button"
          style={{
            ...primaryBtn,
            opacity: canOpen ? 1 : 0.5,
            cursor: canOpen ? 'pointer' : 'not-allowed'
          }}
          disabled={!canOpen}
          onClick={() => {
            setDatasetSlug(selectedSlug);
            setScreen('map');
          }}
        >
          Open map
        </button>
      </div>
    </div>
  );
}
