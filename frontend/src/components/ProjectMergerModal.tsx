import { useState } from 'react';

interface ProjectItem {
  project_id: string;
  project_name: string;
}

interface ProjectMergerModalProps {
  isOpen: boolean;
  projects: ProjectItem[];
  onClose: () => void;
  onSuccess: () => void;
}

interface AuditCheck {
  name: string;
  status: 'ok' | 'warning' | 'error';
  message: string;
}

interface AuditReport {
  status: 'passed' | 'warning' | 'failed';
  can_proceed: boolean;
  source_projects: string[];
  target_project_id: string;
  duration_ms: number;
  checks: AuditCheck[];
  warnings: string[];
  errors: string[];
  projected_stats: {
    total_articles: number;
    total_enrichments: number;
    total_code_units: number;
    total_synthetic_code_pairs: number;
    total_jsonl_samples: number;
  };
}

export const ProjectMergerModal: React.FC<ProjectMergerModalProps> = ({
  isOpen,
  projects,
  onClose,
  onSuccess,
}) => {
  const [selectedProjectIds, setSelectedProjectIds] = useState<string[]>([]);
  const [targetId, setTargetId] = useState<string>('rendergit_merged_all');
  const [targetName, setTargetName] = useState<string>('RenderGit Consolidated Master Dataset');
  const [isAuditing, setIsAuditing] = useState<boolean>(false);
  const [isMerging, setIsMerging] = useState<boolean>(false);
  const [auditReport, setAuditReport] = useState<AuditReport | null>(null);
  const [mergeSuccessReport, setMergeSuccessReport] = useState<any | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  if (!isOpen) return null;

  const toggleSelectProject = (pid: string) => {
    if (selectedProjectIds.includes(pid)) {
      setSelectedProjectIds(selectedProjectIds.filter(id => id !== pid));
    } else {
      setSelectedProjectIds([...selectedProjectIds, pid]);
    }
    setAuditReport(null);
    setMergeSuccessReport(null);
  };

  const handleRunAudit = async () => {
    if (selectedProjectIds.length < 2) {
      setErrorMsg('Birleştirme için en az 2 kaynak proje seçilmelidir.');
      return;
    }
    if (!targetId || !targetId.trim()) {
      setErrorMsg('Hedef proje ID (kimliği) belirtilmelidir.');
      return;
    }

    setIsAuditing(true);
    setErrorMsg(null);
    setAuditReport(null);
    setMergeSuccessReport(null);

    try {
      const resp = await fetch('/api/projects/merge/audit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_projects: selectedProjectIds,
          target_project_id: targetId,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.detail || 'Denetim hatası');
      }
      setAuditReport(data);
    } catch (err: any) {
      setErrorMsg(err.message || 'Denetim sunucu hatası');
    } finally {
      setIsAuditing(false);
    }
  };

  const handleExecuteMerge = async () => {
    if (!auditReport || !auditReport.can_proceed) {
      setErrorMsg('Lütfen önce test çalıştırması (Dry-Run Audit) yapın ve hataları giderin.');
      return;
    }

    setIsMerging(true);
    setErrorMsg(null);

    try {
      const resp = await fetch('/api/projects/merge/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_projects: selectedProjectIds,
          target_project_id: targetId,
          target_project_name: targetName,
          confirm: true,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.detail || 'Birleştirme hatası');
      }
      setMergeSuccessReport(data);
      setTimeout(() => {
        onSuccess();
      }, 2500);
    } catch (err: any) {
      setErrorMsg(err.message || 'Birleştirme sırasında sunucu hatası');
    } finally {
      setIsMerging(false);
    }
  };

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
      backgroundColor: 'rgba(0, 0, 0, 0.75)', backdropFilter: 'blur(4px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000
    }}>
      <div style={{
        backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '0.75rem',
        width: '90%', maxWidth: '850px', maxHeight: '90vh', overflowY: 'auto', padding: '1.5rem',
        boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5)'
      }}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem', borderBottom: '1px solid #1e293b', paddingBottom: '0.75rem' }}>
          <div>
            <h2 style={{ margin: 0, fontSize: '1.2rem', color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span>🔀</span> Proje & Veri Setleri Birleştirme Motoru (Phase 3)
            </h2>
            <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Farklı projeleri, SQLite veritabanlarını ve JSONL veri setlerini güvenle konsolide eder.</span>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#94a3b8', fontSize: '1.4rem', cursor: 'pointer' }}>×</button>
        </div>

        {errorMsg && (
          <div style={{ backgroundColor: 'rgba(239, 68, 68, 0.15)', border: '1px solid #ef4444', color: '#fca5a5', padding: '0.75rem', borderRadius: '0.5rem', marginBottom: '1rem', fontSize: '0.85rem' }}>
            ⚠️ <strong>Hata:</strong> {errorMsg}
          </div>
        )}

        {/* Proje Seçim Paneli */}
        <div style={{ marginBottom: '1.25rem' }}>
          <label style={{ fontSize: '0.85rem', fontWeight: 600, color: '#e2e8f0', marginBottom: '0.5rem', display: 'block' }}>
            1. Birleştirilecek Kaynak Projeleri Seçin (En az 2 proje)
          </label>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: '0.6rem' }}>
            {projects.map(p => {
              const isSelected = selectedProjectIds.includes(p.project_id);
              return (
                <div
                  key={p.project_id}
                  onClick={() => toggleSelectProject(p.project_id)}
                  style={{
                    backgroundColor: isSelected ? 'rgba(99, 102, 241, 0.15)' : 'rgba(30, 41, 59, 0.5)',
                    border: `1px solid ${isSelected ? '#6366f1' : '#334155'}`,
                    borderRadius: '0.5rem', padding: '0.6rem 0.75rem', cursor: 'pointer',
                    display: 'flex', alignItems: 'center', gap: '0.5rem', transition: 'all 0.15s ease'
                  }}
                >
                  <input type="checkbox" checked={isSelected} onChange={() => {}} style={{ cursor: 'pointer' }} />
                  <div>
                    <div style={{ fontSize: '0.85rem', fontWeight: 600, color: isSelected ? '#a5b4fc' : '#f1f5f9' }}>{p.project_name}</div>
                    <div style={{ fontSize: '0.72rem', color: '#64748b' }}>ID: {p.project_id}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Hedef Proje Bilgileri */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1.25rem' }}>
          <div>
            <label style={{ fontSize: '0.8rem', color: '#94a3b8' }}>Yeni Hedef Proje ID (Slug)</label>
            <input
              type="text"
              className="form-control"
              value={targetId}
              onChange={(e) => { setTargetId(e.target.value); setAuditReport(null); }}
              placeholder="rendergit_merged_all"
            />
          </div>
          <div>
            <label style={{ fontSize: '0.8rem', color: '#94a3b8' }}>Yeni Hedef Proje Adı</label>
            <input
              type="text"
              className="form-control"
              value={targetName}
              onChange={(e) => setTargetName(e.target.value)}
              placeholder="RenderGit Master Dataset"
            />
          </div>
        </div>

        {/* ADIM 1: DRY-RUN AUDIT BUTTON */}
        <div style={{ marginBottom: '1.25rem' }}>
          <button
            className={`btn ${isAuditing ? 'btn-disabled' : 'btn-secondary'}`}
            style={{ width: '100%', padding: '0.65rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem', fontWeight: 600 }}
            disabled={isAuditing || selectedProjectIds.length < 2}
            onClick={handleRunAudit}
          >
            {isAuditing ? '⌛ Denetim & Test Çalıştırması Yapılıyor...' : '🔍 1. İki Kez Doğrulama ve Test Çalıştırması Yap (Dry-Run Audit)'}
          </button>
        </div>

        {/* HATA AYIKLAMA KONSOLU (AUDIT & DEBUG CONSOLE) */}
        {auditReport && (
          <div style={{ backgroundColor: '#020617', border: '1px solid #1e293b', borderRadius: '0.5rem', padding: '1rem', marginBottom: '1.25rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem', borderBottom: '1px solid #1e293b', paddingBottom: '0.5rem' }}>
              <span style={{ fontSize: '0.85rem', fontWeight: 700, color: '#38bdf8', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                🛠️ Hata Ayıklama & Ön Denetim Konsolu (Debug & Audit Report)
              </span>
              <span className={`badge ${auditReport.status === 'passed' ? 'online' : auditReport.status === 'warning' ? 'warning' : 'offline'}`}>
                {auditReport.status === 'passed' ? '✓ %100 UYUMLU PASSED' : auditReport.status === 'warning' ? '⚠️ UYARILI PASSED' : '❌ HATA FAILED'}
              </span>
            </div>

            {/* Check List */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginBottom: '0.75rem' }}>
              {auditReport.checks.map((chk, idx) => (
                <div key={idx} style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem', fontSize: '0.8rem', backgroundColor: 'rgba(255,255,255,0.02)', padding: '0.4rem 0.6rem', borderRadius: '0.35rem' }}>
                  <span>{chk.status === 'ok' ? '✅' : chk.status === 'warning' ? '⚠️' : '❌'}</span>
                  <div>
                    <strong style={{ color: chk.status === 'ok' ? '#34d399' : chk.status === 'warning' ? '#fbbf24' : '#f87171' }}>{chk.name}:</strong>
                    <span style={{ color: '#cbd5e1', marginLeft: '0.4rem' }}>{chk.message}</span>
                  </div>
                </div>
              ))}
            </div>

            {/* Projected Stats */}
            <div style={{ backgroundColor: 'rgba(56, 189, 248, 0.05)', padding: '0.6rem 0.75rem', borderRadius: '0.35rem', border: '1px solid rgba(56, 189, 248, 0.15)', fontSize: '0.78rem', color: '#94a3b8' }}>
              <strong style={{ color: '#38bdf8' }}>📊 Hedef Birleştirilmiş Veri Tahmini:</strong>
              <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginTop: '0.3rem', color: '#f1f5f9' }}>
                <span>📖 Makaleler: <strong>{auditReport.projected_stats.total_articles}</strong></span>
                <span>💻 AST Kod Birimleri: <strong>{auditReport.projected_stats.total_code_units}</strong></span>
                <span>⚡ Sentetik Kod Çiftleri: <strong>{auditReport.projected_stats.total_synthetic_code_pairs}</strong></span>
                <span>📦 Toplam JSONL Örnekleri: <strong>{auditReport.projected_stats.total_jsonl_samples}</strong></span>
              </div>
            </div>
          </div>
        )}

        {/* MERGE SUCCESS REPORT */}
        {mergeSuccessReport && (
          <div style={{ backgroundColor: 'rgba(52, 211, 153, 0.1)', border: '1px solid #34d399', padding: '1rem', borderRadius: '0.5rem', marginBottom: '1.25rem', color: '#34d399', fontSize: '0.85rem' }}>
            🎉 <strong>Birleştirme Başarıyla Tamamlandı!</strong>
            <div style={{ fontSize: '0.78rem', color: '#e2e8f0', marginTop: '0.4rem' }}>
              Hedef Veritabanı: <code>{mergeSuccessReport.db_path}</code><br/>
              Birleştirilen Makaleler: {mergeSuccessReport.merged_stats.articles} | Kod Birimleri: {mergeSuccessReport.merged_stats.code_units} | Sentetik Çiftler: {mergeSuccessReport.merged_stats.synthetic_code_pairs}
            </div>
          </div>
        )}

        {/* ADIM 2: EXECUTE MERGE BUTTON */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', borderTop: '1px solid #1e293b', paddingTop: '1rem' }}>
          <button className="btn btn-secondary" onClick={onClose}>
            Kapat
          </button>
          <button
            className={`btn ${(!auditReport || !auditReport.can_proceed || isMerging) ? 'btn-disabled' : 'btn-emerald'}`}
            disabled={!auditReport || !auditReport.can_proceed || isMerging}
            onClick={handleExecuteMerge}
            style={{ fontWeight: 600 }}
          >
            {isMerging ? '⚡ Birleştirme Gerçekleştiriliyor...' : '⚡ 2. Güvenli Birleştirmeyi Başlat (Execute Merge)'}
          </button>
        </div>
      </div>
    </div>
  );
};
