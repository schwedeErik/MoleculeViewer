import { useCallback, useEffect, useState, type CSSProperties } from 'react';
import { isStatic, loadDatasetsCatalog } from './config';
import { DatasetUpload } from './DatasetUpload';
import { DeepscatterView } from './DeepscatterView';
import { ScatterplotView } from './ScatterplotView';
import { useAppStore } from './store';
import { embeddingMethodLabel, type DatasetInfo } from './types';

export function App() {
  const apiBase = useAppStore((s) => s.apiBase);
  const datasetSlug = useAppStore((s) => s.datasetSlug);
  const setDatasetSlug = useAppStore((s) => s.setDatasetSlug);

  const [screen, setScreen] = useState<'setup' | 'deepscatter' | 'mvt'>('setup');
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [selectedSlug, setSelectedSlug] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadDatasets = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data: DatasetInfo[] = await loadDatasetsCatalog();
      setDatasets(data);
      setSelectedSlug((prev) => {
        if (prev && data.some((d) => d.slug === prev)) return prev;
        if (datasetSlug && data.some((d) => d.slug === datasetSlug)) return datasetSlug;
        const preferred = data.find((d) => d.slug === 'chembl13m');
        return preferred?.slug ?? data[0]?.slug ?? '';
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

  if (screen === 'deepscatter' && datasetSlug) {
    const active = datasets.find((d) => d.slug === datasetSlug);
    const allowLegacy = !isStatic && !active?.deepscatter_only;
    return (
      <DeepscatterView
        onBack={() => setScreen('setup')}
        onOpenLegacyMvt={allowLegacy ? () => setScreen('mvt') : undefined}
      />
    );
  }

  if (screen === 'mvt' && datasetSlug) {
    return <ScatterplotView onBack={() => setScreen('deepscatter')} />;
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
    ((selectedDataset?.molecule_count ?? 0) > 0 ||
      (selectedDataset?.deepscatter_orders?.length ?? 0) > 0);

  async function handleDelete() {
    if (!selectedDataset) return;
    const msg = `Delete "${selectedDataset.name}" and its ${selectedDataset.molecule_count.toLocaleString()} molecules? This cannot be undone.`;
    if (!window.confirm(msg)) return;

    setDeleting(true);
    setError(null);
    try {
      const res = await fetch(
        `${apiBase}/datasets/${encodeURIComponent(selectedDataset.slug)}`,
        { method: 'DELETE' }
      );
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = (body as { detail?: string }).detail;
        throw new Error(detail ?? `Delete failed (${res.status})`);
      }
      if (datasetSlug === selectedDataset.slug) {
        setDatasetSlug(null);
      }
      await loadDatasets();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setDeleting(false);
    }
  }

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
            ? 'Static ChemMaps demo: choose a dataset and open the Deepscatter map. Uploads and the legacy MVT viewer need the full app with a backend.'
            : 'Choose a dataset loaded in PostgreSQL, or upload a new CSV export from the pipeline. The main viewer uses Deepscatter (quadfeather tiles); legacy MVT remains available from the map toolbar.'}
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
              <div style={{ fontSize: 14, color: '#666' }}>
                {isStatic ? 'No datasets available.' : 'No datasets yet — upload a CSV below.'}
              </div>
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
              {!isStatic && (
                <div>
                  <strong>Mode:</strong>{' '}
                  {selectedDataset.deepscatter_only
                    ? 'Deepscatter only (no Postgres / deck.gl)'
                    : 'Full (Postgres + optional Legacy MVT)'}
                </div>
              )}
              {!isStatic && (
                <button
                  type="button"
                  disabled={deleting}
                  onClick={() => void handleDelete()}
                  style={{
                    marginTop: 10,
                    padding: '6px 12px',
                    fontSize: 13,
                    border: '1px solid #e0b4b4',
                    borderRadius: 6,
                    background: '#fff',
                    color: '#c5221f',
                    cursor: deleting ? 'not-allowed' : 'pointer',
                    opacity: deleting ? 0.6 : 1
                  }}
                >
                  {deleting ? 'Deleting…' : 'Delete dataset'}
                </button>
              )}
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
            setScreen('deepscatter');
          }}
        >
          Open Deepscatter map
        </button>

        {!isStatic && (
          <DatasetUpload
            apiBase={apiBase}
            onUploaded={(dataset) => {
              void loadDatasets();
              setSelectedSlug(dataset.slug);
            }}
          />
        )}
      </div>
    </div>
  );
}
