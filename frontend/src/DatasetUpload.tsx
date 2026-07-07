import { useState, type CSSProperties } from 'react';
import type { DatasetInfo } from './types';

function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 64);
}

type DatasetUploadProps = {
  apiBase: string;
  onUploaded: (dataset: DatasetInfo) => void;
};

export function DatasetUpload({ apiBase, onUploaded }: DatasetUploadProps) {
  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [slugTouched, setSlugTouched] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const fieldStyle = {
    display: 'flex' as const,
    flexDirection: 'column' as const,
    gap: 6
  };

  const labelStyle = { fontSize: 13, fontWeight: 600, color: '#333' };

  const inputStyle: CSSProperties = {
    padding: '10px 12px',
    fontSize: 14,
    border: '1px solid #ccc',
    borderRadius: 6,
    background: '#fff'
  };

  const canUpload = Boolean(name.trim() && slug.trim() && file && !uploading);

  async function handleUpload() {
    if (!file) return;
    setUploading(true);
    setError(null);
    setSuccess(null);

    const form = new FormData();
    form.append('file', file);
    form.append('slug', slug.trim());
    form.append('name', name.trim());
    form.append('embedding_method', 'maccs');

    try {
      const res = await fetch(`${apiBase}/datasets`, { method: 'POST', body: form });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = (body as { detail?: string | { msg: string }[] }).detail;
        const message =
          typeof detail === 'string'
            ? detail
            : Array.isArray(detail)
              ? detail.map((d) => d.msg).join('; ')
              : `Upload failed (${res.status})`;
        throw new Error(message);
      }
      const dataset = body as DatasetInfo;
      setSuccess(`Imported ${dataset.molecule_count.toLocaleString()} molecules`);
      setName('');
      setSlug('');
      setSlugTouched(false);
      setFile(null);
      onUploaded(dataset);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  }

  return (
    <div
      style={{
        marginTop: 24,
        paddingTop: 24,
        borderTop: '1px solid #eee'
      }}
    >
      <h2 style={{ margin: '0 0 8px', fontSize: 16, fontWeight: 700 }}>Upload dataset</h2>
      <p style={{ margin: '0 0 16px', fontSize: 13, color: '#666', lineHeight: 1.5 }}>
        CSV columns: <code>smiles, rank, lng, lat, embedding</code> (same format as the
        pipeline export).
      </p>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div style={fieldStyle}>
          <label htmlFor="upload-name" style={labelStyle}>
            Name
          </label>
          <input
            id="upload-name"
            type="text"
            value={name}
            onChange={(e) => {
              const next = e.target.value;
              setName(next);
              if (!slugTouched) setSlug(slugify(next));
            }}
            placeholder="ZINC 10k sample"
            style={inputStyle}
          />
        </div>

        <div style={fieldStyle}>
          <label htmlFor="upload-slug" style={labelStyle}>
            Slug
          </label>
          <input
            id="upload-slug"
            type="text"
            value={slug}
            onChange={(e) => {
              setSlugTouched(true);
              setSlug(e.target.value);
            }}
            placeholder="zinc10k"
            style={inputStyle}
          />
        </div>

        <div style={fieldStyle}>
          <label htmlFor="upload-file" style={labelStyle}>
            CSV file
          </label>
          <input
            id="upload-file"
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </div>

        {error && <div style={{ fontSize: 13, color: '#c5221f' }}>{error}</div>}
        {success && <div style={{ fontSize: 13, color: '#137333' }}>{success}</div>}

        <button
          type="button"
          disabled={!canUpload}
          onClick={handleUpload}
          style={{
            padding: '10px 16px',
            fontSize: 14,
            fontWeight: 600,
            border: '1px solid #ccc',
            borderRadius: 6,
            background: '#f8f8f8',
            cursor: canUpload ? 'pointer' : 'not-allowed',
            opacity: canUpload ? 1 : 0.6
          }}
        >
          {uploading ? 'Uploading…' : 'Upload to database'}
        </button>
      </div>
    </div>
  );
}
