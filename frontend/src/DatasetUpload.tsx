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

type JobStatus = {
  job_id: string;
  status: 'queued' | 'running' | 'done' | 'error';
  phase?: string;
  progress?: number;
  message?: string;
  error?: string | null;
  dataset?: DatasetInfo | null;
};

function xhrFormUpload(
  url: string,
  form: FormData,
  onUploadProgress: (pct: number) => void
): Promise<JobStatus> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', url);
    xhr.responseType = 'json';
    xhr.upload.onprogress = (ev) => {
      if (!ev.lengthComputable) return;
      onUploadProgress(Math.round((100 * ev.loaded) / ev.total));
    };
    xhr.onload = () => {
      const body = xhr.response ?? {};
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as JobStatus);
        return;
      }
      const detail = (body as { detail?: string | { msg: string }[] }).detail;
      const message =
        typeof detail === 'string'
          ? detail
          : Array.isArray(detail)
            ? detail.map((d) => d.msg).join('; ')
            : `Upload failed (${xhr.status})`;
      reject(new Error(message));
    };
    xhr.onerror = () => reject(new Error('Network error during upload'));
    xhr.send(form);
  });
}

async function pollJob(apiBase: string, jobId: string, onProgress: (job: JobStatus) => void) {
  for (;;) {
    const res = await fetch(`${apiBase}/datasets/jobs/${encodeURIComponent(jobId)}`);
    if (!res.ok) throw new Error(`Failed to poll job (${res.status})`);
    const job = (await res.json()) as JobStatus;
    onProgress(job);
    if (job.status === 'done') return job;
    if (job.status === 'error') {
      throw new Error(job.error || job.message || 'Import failed');
    }
    await new Promise((r) => setTimeout(r, 800));
  }
}

export function DatasetUpload({ apiBase, onUploaded }: DatasetUploadProps) {
  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [slugTouched, setSlugTouched] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  /** Deepscatter-only skips Postgres + deck.gl / MVT (recommended for large CSVs). */
  const [deepscatterOnly, setDeepscatterOnly] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [phaseLabel, setPhaseLabel] = useState('');
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
    setProgress(0);
    setPhaseLabel('Uploading CSV…');

    const form = new FormData();
    form.append('file', file);
    form.append('slug', slug.trim());
    form.append('name', name.trim());
    form.append('embedding_method', 'maccs');
    form.append('renderer', deepscatterOnly ? 'deepscatter' : 'full');

    try {
      // Upload = 0–35% of the bar; build job = 35–100%.
      const started = await xhrFormUpload(`${apiBase}/datasets`, form, (pct) => {
        setProgress(Math.round(pct * 0.35));
        setPhaseLabel(`Uploading CSV… ${pct}%`);
      });
      if (!started.job_id) {
        throw new Error('Server did not return a job id');
      }
      setProgress(Math.max(35, started.progress ?? 35));
      setPhaseLabel(started.message || 'Import started…');

      const finished = await pollJob(apiBase, started.job_id, (job) => {
        const buildPct = Math.max(0, Math.min(100, job.progress ?? 0));
        setProgress(35 + Math.round(buildPct * 0.65));
        setPhaseLabel(job.message || job.phase || 'Working…');
      });

      const dataset = finished.dataset;
      if (!dataset) throw new Error('Import finished without a dataset');
      const mode = deepscatterOnly ? 'Deepscatter tiles' : 'Postgres';
      setSuccess(
        `Imported ${dataset.molecule_count.toLocaleString()} molecules (${mode})`
      );
      setProgress(100);
      setPhaseLabel('Done');
      setName('');
      setSlug('');
      setSlugTouched(false);
      setFile(null);
      onUploaded(dataset);
    } catch (e) {
      setError((e as Error).message);
      setPhaseLabel('');
    } finally {
      setUploading(false);
    }
  }

  const buttonLabel = uploading
    ? `${phaseLabel || 'Working…'} ${progress}%`
    : deepscatterOnly
      ? 'Upload for Deepscatter'
      : 'Upload to database (full)';

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
        CSV columns: <code>smiles, rank, lng, lat</code>
        {deepscatterOnly ? '' : ', embedding'} (pipeline export). Large files should use
        Deepscatter only.
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
            placeholder="ZINC 10M"
            style={inputStyle}
            disabled={uploading}
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
            placeholder="zinc10m"
            style={inputStyle}
            disabled={uploading}
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
            disabled={uploading}
          />
        </div>

        <label
          style={{
            display: 'flex',
            gap: 10,
            alignItems: 'flex-start',
            fontSize: 13,
            color: '#333',
            lineHeight: 1.45,
            cursor: uploading ? 'default' : 'pointer',
            opacity: uploading ? 0.7 : 1
          }}
        >
          <input
            type="checkbox"
            checked={deepscatterOnly}
            onChange={(e) => setDeepscatterOnly(e.target.checked)}
            style={{ marginTop: 3 }}
            disabled={uploading}
          />
          <span>
            <strong>Deepscatter only</strong> — skip Postgres / legacy deck.gl MVT. Much
            faster for multi‑million CSVs; map uses quadfeather tiles only.
            Uncheck to also load into the database for Legacy MVT.
          </span>
        </label>

        {error && <div style={{ fontSize: 13, color: '#c5221f' }}>{error}</div>}
        {success && <div style={{ fontSize: 13, color: '#137333' }}>{success}</div>}

        <button
          type="button"
          disabled={!canUpload}
          onClick={() => void handleUpload()}
          style={{
            position: 'relative',
            overflow: 'hidden',
            padding: '10px 16px',
            fontSize: 14,
            fontWeight: 600,
            border: '1px solid #ccc',
            borderRadius: 6,
            background: '#f8f8f8',
            cursor: canUpload ? 'pointer' : 'not-allowed',
            opacity: canUpload || uploading ? 1 : 0.6,
            color: '#1a1a1a',
            textAlign: 'center',
            minHeight: 42
          }}
        >
          {uploading && (
            <span
              aria-hidden
              style={{
                position: 'absolute',
                left: 0,
                top: 0,
                bottom: 0,
                width: `${Math.max(2, progress)}%`,
                background: 'linear-gradient(90deg, #cfe3fc 0%, #1a73e8 100%)',
                transition: 'width 0.25s ease',
                zIndex: 0
              }}
            />
          )}
          <span style={{ position: 'relative', zIndex: 1 }}>{buttonLabel}</span>
        </button>
      </div>
    </div>
  );
}
