import { useState, useEffect } from 'react';

export interface ProjectItem {
  project_id: string;
  project_name: string;
}

interface HFUploadModalProps {
  isOpen: boolean;
  activeProjectId: string;
  activeProjectName?: string;
  projects?: ProjectItem[];
  onClose: () => void;
}

interface AuditCheck {
  name: string;
  status: 'ok' | 'warning' | 'error';
  message: string;
}

interface FileToUpload {
  filename: string;
  size_kb: number;
  samples: number;
}

interface HFAuditReport {
  status: 'passed' | 'warning' | 'failed';
  can_proceed: boolean;
  project_id: string;
  repo_id: string;
  duration_ms: number;
  checks: AuditCheck[];
  warnings: string[];
  errors: string[];
  files_to_upload: FileToUpload[];
  total_size_mb: number;
  total_samples: number;
  cli_command: string;
  python_snippet: string;
  dataset_card_preview: string;
}

export const HFUploadModal: React.FC<HFUploadModalProps> = ({
  isOpen,
  activeProjectId,
  activeProjectName,
  projects = [],
  onClose,
}) => {
  const [activeTab, setActiveTab] = useState<'hf' | 'cloud'>('hf');
  const [repoId, setRepoId] = useState<string>(`onkanat/${activeProjectId || 'sdr_engineers'}-dataset`);
  const [hfToken, setHfToken] = useState<string>('');
  const [isPrivate, setIsPrivate] = useState<boolean>(false);

  const [isAuditing, setIsAuditing] = useState<boolean>(false);
  const [auditReport, setAuditReport] = useState<HFAuditReport | null>(null);

  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [uploadResult, setUploadResult] = useState<any | null>(null);

  const [datasetFile, setDatasetFile] = useState<string>('code_sft_dataset.jsonl');
  const [baseModel, setBaseModel] = useState<string>('Qwen/Qwen3.5-2B');
  const [isPreparingCloud, setIsPreparingCloud] = useState<boolean>(false);
  const [cloudResult, setCloudResult] = useState<any | null>(null);

  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Auto-preset repoId whenever activeProjectId changes or modal opens
  useEffect(() => {
    if (isOpen) {
      const pid = activeProjectId || 'sdr_engineers';
      setRepoId(`onkanat/${pid}-dataset`);
      setAuditReport(null);
      setUploadResult(null);
      setErrorMsg(null);
    }
  }, [activeProjectId, isOpen]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    if (isOpen) {
      window.addEventListener('keydown', handleKeyDown);
    }
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleRunAudit = async () => {
    if (!repoId.trim()) {
      setErrorMsg('Lütfen bir Hugging Face Repository ID (örn: onkanat/my-dataset) yazın.');
      return;
    }

    setIsAuditing(true);
    setErrorMsg(null);
    setAuditReport(null);
    setUploadResult(null);

    try {
      const resp = await fetch('/api/hf/audit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: activeProjectId || 'sdr_engineers',
          repo_id: repoId.trim(),
          hf_token: hfToken.trim() || undefined,
          private: isPrivate,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.detail || 'HF denetim hatası');
      }
      setAuditReport(data);
    } catch (err: any) {
      setErrorMsg(err.message || 'Denetim sırasında sunucu hatası oluştu.');
    } finally {
      setIsAuditing(false);
    }
  };

  const handleUploadHF = async () => {
    if (!auditReport || !auditReport.can_proceed) {
      setErrorMsg('Lütfen önce test çalıştırması (Dry-Run Audit) yapın ve hataları giderin.');
      return;
    }

    setIsUploading(true);
    setErrorMsg(null);

    try {
      const resp = await fetch('/api/hf/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: activeProjectId || 'sdr_engineers',
          repo_id: repoId.trim(),
          hf_token: hfToken.trim() || undefined,
          private: isPrivate,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.detail || 'Hugging Face yükleme hatası');
      }
      setUploadResult(data);
    } catch (err: any) {
      setErrorMsg(err.message || 'Yükleme sırasında hata oluştu.');
    } finally {
      setIsUploading(false);
    }
  };

  const handlePrepareCloud = async () => {
    setIsPreparingCloud(true);
    setErrorMsg(null);
    setCloudResult(null);

    try {
      const resp = await fetch('/api/cloud/prepare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: activeProjectId,
          base_model: baseModel,
          hf_dataset: repoId.trim() || '',
          dataset_file: datasetFile,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.detail || 'Bulut GPU paket hazırlık hatası');
      }
      setCloudResult(data);
    } catch (err: any) {
      setErrorMsg(err.message || 'Bulut paketi oluşturulurken hata oluştu.');
    } finally {
      setIsPreparingCloud(false);
    }
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.75)', backdropFilter: 'blur(4px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '0.75rem',
          width: '90%', maxWidth: '850px', maxHeight: '90vh', overflowY: 'auto', padding: '1.5rem',
          boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5)'
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', borderBottom: '1px solid #1e293b', paddingBottom: '0.75rem' }}>
          <div>
            <h2 style={{ margin: 0, fontSize: '1.2rem', color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span>🤗</span> Hugging Face Hub & Bulut GPU Dağıtım Kiti (Phase 4)
            </h2>
            <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Aktif Proje: <strong style={{ color: '#38bdf8' }}>{activeProjectName || activeProjectId}</strong> (ID: <code>{activeProjectId}</code>)</span>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#94a3b8', fontSize: '1.4rem', cursor: 'pointer' }}>×</button>
        </div>

        {/* Tab Buttons */}
        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.25rem', borderBottom: '1px solid #334155', paddingBottom: '0.5rem' }}>
          <button
            onClick={() => setActiveTab('hf')}
            style={{
              backgroundColor: activeTab === 'hf' ? 'rgba(234, 179, 8, 0.15)' : 'transparent',
              border: `1px solid ${activeTab === 'hf' ? '#eab308' : 'transparent'}`,
              color: activeTab === 'hf' ? '#fde047' : '#94a3b8',
              padding: '0.4rem 0.8rem', borderRadius: '0.35rem', cursor: 'pointer', fontWeight: 600, fontSize: '0.85rem'
            }}
          >
            🤗 Hugging Face Dataset Hub
          </button>
          <button
            onClick={() => setActiveTab('cloud')}
            style={{
              backgroundColor: activeTab === 'cloud' ? 'rgba(56, 189, 248, 0.15)' : 'transparent',
              border: `1px solid ${activeTab === 'cloud' ? '#38bdf8' : 'transparent'}`,
              color: activeTab === 'cloud' ? '#38bdf8' : '#94a3b8',
              padding: '0.4rem 0.8rem', borderRadius: '0.35rem', cursor: 'pointer', fontWeight: 600, fontSize: '0.85rem'
            }}
          >
            ⚡ Bulut GPU Fine-Tuning Kiti
          </button>
        </div>

        {errorMsg && (
          <div style={{ backgroundColor: 'rgba(239, 68, 68, 0.15)', border: '1px solid #ef4444', color: '#fca5a5', padding: '0.75rem', borderRadius: '0.5rem', marginBottom: '1rem', fontSize: '0.85rem' }}>
            ⚠️ <strong>Hata:</strong> {errorMsg}
          </div>
        )}

        {/* TAB 1: HUGGING FACE UPLOAD */}
        {activeTab === 'hf' && (
          <div>
            <div style={{ display: 'grid', gridTemplateColumns: '1.3fr 0.7fr', gap: '1rem', marginBottom: '1.25rem' }}>
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.35rem' }}>
                  <label style={{ fontSize: '0.8rem', color: '#cbd5e1', fontWeight: 600 }}>Hugging Face Repository ID</label>
                  <span style={{ fontSize: '0.72rem', color: '#38bdf8' }}>🔍 Projeden Seç:</span>
                </div>
                <div style={{ display: 'flex', gap: '0.4rem' }}>
                  <input
                    type="text"
                    className="form-control"
                    value={repoId}
                    onChange={(e) => { setRepoId(e.target.value); setAuditReport(null); }}
                    placeholder="kullanici_adi/repo_adi"
                    style={{ flex: 1 }}
                  />
                  {projects.length > 0 && (
                    <select
                      className="form-control"
                      style={{ width: 'auto', maxWidth: '170px', fontSize: '0.78rem', backgroundColor: '#1e293b', color: '#38bdf8', borderColor: '#334155' }}
                      onChange={(e) => {
                        const selectedPid = e.target.value;
                        if (selectedPid) {
                          setRepoId(`onkanat/${selectedPid}-dataset`);
                          setAuditReport(null);
                        }
                      }}
                      value={projects.find(p => `onkanat/${p.project_id}-dataset` === repoId)?.project_id || ''}
                    >
                      <option value="">-- Proje Seç --</option>
                      {projects.map((p) => (
                        <option key={p.project_id} value={p.project_id}>
                          {p.project_name} ({p.project_id})
                        </option>
                      ))}
                    </select>
                  )}
                </div>
              </div>

              <div>
                <label style={{ fontSize: '0.8rem', color: '#cbd5e1', fontWeight: 600, display: 'block', marginBottom: '0.35rem' }}>HF Access Token (HF_TOKEN)</label>
                <input
                  type="password"
                  className="form-control"
                  value={hfToken}
                  onChange={(e) => { setHfToken(e.target.value); setAuditReport(null); }}
                  placeholder="hf_..."
                />
              </div>
            </div>

            <div style={{ marginBottom: '1.25rem' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.82rem', cursor: 'pointer', color: '#e2e8f0' }}>
                <input
                  type="checkbox"
                  checked={isPrivate}
                  onChange={(e) => { setIsPrivate(e.target.checked); setAuditReport(null); }}
                />
                <span>🔒 Repository'yi Gizli (Private) olarak oluştur.</span>
              </label>
            </div>

            {/* SPLIT BUTTONS: DRY-RUN (LEFT, ACTIVE) & UPLOAD (RIGHT, DISABLED UNTIL AUDITED) */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginBottom: '1.25rem' }}>
              {/* SOL BUTON: DRY-RUN AUDIT (AKTİF) */}
              <button
                className={`btn ${isAuditing ? 'btn-disabled' : 'btn-secondary'}`}
                style={{ padding: '0.65rem', fontWeight: 600, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.4rem' }}
                disabled={isAuditing}
                onClick={handleRunAudit}
              >
                {isAuditing ? '⌛ Test Çalıştırılıyor...' : '🔍 1. Test Çalıştırması Yap (Dry-Run)'}
              </button>

              {/* SAĞ BUTON: ACTUAL UPLOAD (DEAKTİF - AUDIT GEÇENE KADAR KİLİTLİ) */}
              <button
                className={`btn ${(!auditReport || !auditReport.can_proceed || isUploading) ? 'btn-disabled' : 'btn-emerald'}`}
                style={{ padding: '0.65rem', fontWeight: 600, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.4rem' }}
                disabled={!auditReport || !auditReport.can_proceed || isUploading}
                onClick={handleUploadHF}
              >
                {isUploading ? '🚀 Yükleniyor...' : '🚀 2. Hugging Face Hub\'a Yükle'}
              </button>
            </div>

            {/* HATA AYIKLAMA & ÖN DENETİM KONSOLU (AUDIT & DEBUG CONSOLE) */}
            {auditReport && (
              <div style={{ backgroundColor: '#020617', border: '1px solid #1e293b', borderRadius: '0.5rem', padding: '1rem', marginBottom: '1.25rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem', borderBottom: '1px solid #1e293b', paddingBottom: '0.5rem' }}>
                  <span style={{ fontSize: '0.85rem', fontWeight: 700, color: '#fde047', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                    🛠️ Hugging Face Hata Ayıklama & Ön Denetim Konsolu
                  </span>
                  <span className={`badge ${auditReport.status === 'passed' ? 'online' : auditReport.status === 'warning' ? 'warning' : 'offline'}`}>
                    {auditReport.status === 'passed' ? '✓ %100 UYUMLU PASSED' : auditReport.status === 'warning' ? '⚠️ UYARILI PASSED' : '❌ HATA FAILED'}
                  </span>
                </div>

                {/* Checks */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', marginBottom: '0.75rem' }}>
                  {auditReport.checks.map((chk, idx) => (
                    <div key={idx} style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem', fontSize: '0.78rem', backgroundColor: 'rgba(255,255,255,0.02)', padding: '0.35rem 0.5rem', borderRadius: '0.35rem' }}>
                      <span>{chk.status === 'ok' ? '✅' : chk.status === 'warning' ? '⚠️' : '❌'}</span>
                      <div>
                        <strong style={{ color: chk.status === 'ok' ? '#34d399' : chk.status === 'warning' ? '#fbbf24' : '#f87171' }}>{chk.name}:</strong>
                        <span style={{ color: '#cbd5e1', marginLeft: '0.4rem' }}>{chk.message}</span>
                      </div>
                    </div>
                  ))}
                </div>

                {/* File Details & Commands Preview */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', fontSize: '0.75rem' }}>
                  <div style={{ backgroundColor: 'rgba(234, 179, 8, 0.05)', padding: '0.6rem', borderRadius: '0.35rem', border: '1px solid rgba(234, 179, 8, 0.15)' }}>
                    <strong style={{ color: '#fde047' }}>📦 Yüklenecek Dosyalar ({auditReport.files_to_upload.length}):</strong>
                    <ul style={{ margin: '0.3rem 0 0 1rem', padding: 0, color: '#e2e8f0' }}>
                      {auditReport.files_to_upload.map((f, i) => (
                        <li key={i}><code>{f.filename}</code> ({f.size_kb} KB {f.samples > 0 ? `| ${f.samples} örnek` : ''})</li>
                      ))}
                    </ul>
                  </div>

                  <div style={{ backgroundColor: 'rgba(56, 189, 248, 0.05)', padding: '0.6rem', borderRadius: '0.35rem', border: '1px solid rgba(56, 189, 248, 0.15)' }}>
                    <strong style={{ color: '#38bdf8' }}>🖥️ Çalıştırılacak Komut & Python Yükleme kiti:</strong>
                    <div style={{ color: '#cbd5e1', marginTop: '0.3rem', fontFamily: 'monospace', fontSize: '0.72rem' }}>
                      <code>{auditReport.cli_command}</code><br/><br/>
                      <pre style={{ margin: 0, color: '#34d399' }}>{auditReport.python_snippet}</pre>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* SUCCESS REPORT */}
            {uploadResult && (
              <div style={{ backgroundColor: 'rgba(52, 211, 153, 0.1)', border: '1px solid #34d399', padding: '1rem', borderRadius: '0.5rem', marginTop: '1.25rem', color: '#34d399', fontSize: '0.85rem' }}>
                🎉 <strong>Hugging Face Yüklemesi Başarıyla Tamamlandı!</strong>
                <div style={{ marginTop: '0.5rem', color: '#f1f5f9', fontSize: '0.8rem' }}>
                  Yüklenen Veri Seti: <a href={uploadResult.repo_url} target="_blank" rel="noreferrer" style={{ color: '#38bdf8', textDecoration: 'underline' }}>{uploadResult.repo_url}</a><br/>
                  Yüklenen Dosyalar ({uploadResult.uploaded_files.length}): <code>{uploadResult.uploaded_files.join(', ')}</code>
                </div>
              </div>
            )}
          </div>
        )}

        {/* TAB 2: CLOUD GPU & JUPYTERLAB OFFLOADING */}
        {activeTab === 'cloud' && (
          <div>
            <div style={{ backgroundColor: 'rgba(56, 189, 248, 0.08)', border: '1px solid rgba(56, 189, 248, 0.2)', padding: '0.75rem', borderRadius: '0.5rem', marginBottom: '1.25rem', fontSize: '0.8rem', color: '#e2e8f0' }}>
              🪐 <strong>Yerel GPU Sunucusu & JupyterLab Entegrasyonu:</strong><br/>
              Eğitim paketleri yerel GPU sunucunuz (<code>http://192.168.1.14:8888/lab</code>) ve RunPod / Modal sistemleri için otomatik hazırlanır. Üretilen <code>.ipynb</code> notebook dosyasını doğrudan JupyterLab arayüzüne sürükleyip tek tıkla çalıştırabilirsiniz.
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1.25rem' }}>
              <div>
                <label style={{ fontSize: '0.8rem', color: '#cbd5e1', fontWeight: 600 }}>Hedef Taban Model (Base Model)</label>
                <select
                  className="form-control"
                  value={baseModel}
                  onChange={(e) => setBaseModel(e.target.value)}
                >
                  <option value="Qwen/Qwen3.5-2B">Qwen/Qwen3.5-2B (BF16 LoRA & GGUF Export - Önerilen Hızlı Model)</option>
                  <option value="unsloth/Qwen2.5-Coder-7B-Instruct">unsloth/Qwen2.5-Coder-7B-Instruct (Kod & SFT için 7B)</option>
                  <option value="unsloth/Llama-3.1-8B-Instruct">unsloth/Llama-3.1-8B-Instruct (Genel SFT / DPO)</option>
                  <option value="unsloth/Qwen2.5-14B-Instruct">unsloth/Qwen2.5-14B-Instruct (Büyük Kod Modeli)</option>
                </select>
              </div>

              <div>
                <label style={{ fontSize: '0.8rem', color: '#cbd5e1', fontWeight: 600 }}>Eğitilecek Veri Seti Dosyası (Split)</label>
                <select
                  className="form-control"
                  value={datasetFile}
                  onChange={(e) => setDatasetFile(e.target.value)}
                >
                  <option value="code_sft_dataset.jsonl">code_sft_dataset.jsonl (Kod Tamamlama & SFT - Önerilen)</option>
                  <option value="tr_code_sft_dataset.jsonl">tr_code_sft_dataset.jsonl (Türkçe Kod SFT)</option>
                  <option value="sft_dataset.jsonl">sft_dataset.jsonl (Genel SFT)</option>
                  <option value="dpo_dataset.jsonl">dpo_dataset.jsonl (DPO Tercih Çiftleri)</option>
                  <option value="auto">Otomatik Algıla (Tüm JSONL Dosyaları)</option>
                </select>
              </div>
            </div>

            <button
              className={`btn ${isPreparingCloud ? 'btn-disabled' : 'btn-primary'}`}
              style={{ width: '100%', padding: '0.65rem', fontWeight: 600 }}
              disabled={isPreparingCloud}
              onClick={handlePrepareCloud}
            >
              {isPreparingCloud ? '⌛ Paket Hazırlanıyor...' : '🛠️ JupyterLab & Bulut GPU Paketi Hazırla (.ipynb / .py / .sh)'}
            </button>

            {cloudResult && (
              <div style={{ backgroundColor: 'rgba(56, 189, 248, 0.1)', border: '1px solid #38bdf8', padding: '1rem', borderRadius: '0.5rem', marginTop: '1.25rem', color: '#38bdf8', fontSize: '0.85rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                  <strong>🚀 JupyterLab & Bulut GPU Paketi Oluşturuldu!</strong>
                  <a
                    href={`/api/cloud/download-notebook?project_id=${activeProjectId}`}
                    download={`unsloth_finetune_${activeProjectId}.ipynb`}
                    className="btn btn-emerald"
                    style={{ textDecoration: 'none', padding: '0.35rem 0.75rem', fontSize: '0.78rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.4rem' }}
                  >
                    📥 🪐 Notebook (.ipynb) İndir
                  </a>
                </div>
                <div style={{ color: '#f1f5f9', fontSize: '0.8rem' }}>
                  Paket Dizini: <code>{cloudResult.payload_dir}</code><br/>
                  Üretilen Dosyalar ({cloudResult.generated_files.length}): <code>{cloudResult.generated_files.join(', ')}</code>
                  <div style={{ marginTop: '0.6rem', padding: '0.5rem', background: 'rgba(99, 102, 241, 0.15)', borderRadius: '0.35rem', border: '1px solid rgba(99, 102, 241, 0.3)', color: '#c7d2fe' }}>
                    💎 <strong>Google Vertex AI Gemini Tuning Reçetesi (`vertex_ai_tuning.json`):</strong><br/>
                    Google Developer Program krediniz ile Google Cloud Vertex AI Model Registry üzerinde Gemini Supervised Fine-Tuning başlatmak için hazırlandı.
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', borderTop: '1px solid #1e293b', paddingTop: '1rem', marginTop: '1.5rem' }}>
          <button className="btn btn-secondary" onClick={onClose}>Kapat</button>
        </div>
      </div>
    </div>
  );
};
