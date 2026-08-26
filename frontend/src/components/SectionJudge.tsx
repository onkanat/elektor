import React, { useState, useEffect } from 'react';
import type { JudgeStats, TokenBudgetInfo, HookAuditInfo, PipelineConfig } from '../types';

interface SectionJudgeProps {
  config?: PipelineConfig | null;
  activeProjectId: string;
  onRefreshHealth?: () => void;
}

interface BatchJobItem {
  id: number;
  job_id: string;
  job_type: string;
  model: string;
  state: string;
  total_requests: number;
  processed_requests: number;
  mode: string;
  threshold: number;
  created_at: string;
  completed_at: string | null;
}

export const SectionJudge: React.FC<SectionJudgeProps> = ({
  activeProjectId,
  onRefreshHealth,
}) => {
  const [judgeStats, setJudgeStats] = useState<JudgeStats | null>(null);
  const [budgetInfo, setBudgetInfo] = useState<TokenBudgetInfo | null>(null);
  const [hookAudit, setHookAudit] = useState<HookAuditInfo | null>(null);
  const [batchJobs, setBatchJobs] = useState<BatchJobItem[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [syncingBatch, setSyncingBatch] = useState<boolean>(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  // Form parameters
  const [mode, setMode] = useState<'strict' | 'hybrid_editor'>('strict');
  const [executionType, setExecutionType] = useState<'online' | 'batch'>('online');
  const [threshold, setThreshold] = useState<number>(7.0);
  const [limit, setLimit] = useState<string>('50');
  const [isTriggerRunning, setIsTriggerRunning] = useState<boolean>(false);
  const [triggerUseBatch, setTriggerUseBatch] = useState<boolean>(true);

  const fetchJudgeStats = async () => {
    try {
      const res = await fetch(`/api/judge/stats?project_id=${encodeURIComponent(activeProjectId)}`);
      if (res.ok) {
        const data = await res.json();
        setJudgeStats(data);
      }
    } catch (e) {
      console.error('Judge stats fetch error:', e);
    }
  };

  const fetchBudgetInfo = async () => {
    try {
      const res = await fetch('/api/gemini/budget');
      if (res.ok) {
        const data = await res.json();
        const info = data.consumption ? data.consumption : data;
        setBudgetInfo(info);
      }
    } catch (e) {
      console.error('Gemini budget fetch error:', e);
    }
  };

  const fetchHookAudit = async () => {
    try {
      const res = await fetch('/api/hooks/audit');
      if (res.ok) {
        const data = await res.json();
        setHookAudit(data);
      }
    } catch (e) {
      console.error('Hook audit fetch error:', e);
    }
  };

  const fetchBatchJobs = async () => {
    try {
      const res = await fetch('/api/judge/batch/jobs');
      if (res.ok) {
        const data = await res.json();
        setBatchJobs(data.jobs || []);
      }
    } catch (e) {
      console.error('Batch jobs fetch error:', e);
    }
  };

  const refreshAll = () => {
    fetchJudgeStats();
    fetchBudgetInfo();
    fetchHookAudit();
    fetchBatchJobs();
    if (onRefreshHealth) onRefreshHealth();
  };

  useEffect(() => {
    refreshAll();
  }, [activeProjectId]);

  const handleRunJudge = async () => {
    setLoading(true);
    setActionMessage(null);
    try {
      const parsedLimit = limit === 'all' ? null : parseInt(limit, 10);
      
      if (executionType === 'batch') {
        const res = await fetch('/api/judge/batch/submit', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            project_id: activeProjectId,
            mode,
            threshold: parseFloat(threshold.toString()),
            limit: parsedLimit,
          }),
        });
        const data = await res.json();
        if (data.status === 'active_job_exists') {
          setActionMessage(`⚠️ ${data.message}`);
          refreshAll();
        } else if (res.ok) {
          setActionMessage(`📦 Gemini Batch Job Başlatıldı: ${data.job_id || 'ID Alındı'} (${data.total_requests || 0} adet, %50 indirimli).`);
          refreshAll();
        } else {
          setActionMessage(`❌ Hata: ${data.detail || data.error || 'Batch iş gönderme başarısız.'}`);
        }
      } else {
        const res = await fetch('/api/judge/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            project_id: activeProjectId,
            mode,
            threshold: parseFloat(threshold.toString()),
            limit: parsedLimit,
          }),
        });
        const data = await res.json();
        if (res.ok) {
          setActionMessage(`✅ Hakem denetimi tamamlandı: ${data.approved || 0} onaylandı, ${data.borderline || 0} yeniden yazıldı, ${data.rejected || 0} reddedildi.`);
          refreshAll();
        } else {
          setActionMessage(`❌ Hata: ${data.detail || 'Hakem çalıştırma başarısız.'}`);
        }
      }
    } catch (e: any) {
      setActionMessage(`❌ İstek hatası: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleCancelBatchJob = async (jobId: string) => {
    setActionMessage(null);
    try {
      const res = await fetch('/api/judge/batch/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: jobId }),
      });
      const data = await res.json();
      if (res.ok) {
        setActionMessage(`🗑️ Batch işi (${jobId}) silindi / iptal edildi.`);
        refreshAll();
      } else {
        setActionMessage(`❌ İptal hatası: ${data.detail || data.message || 'Bilinmeyen hata'}`);
      }
    } catch (e: any) {
      setActionMessage(`❌ İptal isteği hatası: ${e.message}`);
    }
  };

  const handleSyncBatchJobs = async () => {
    setSyncingBatch(true);
    setActionMessage(null);
    try {
      const res = await fetch('/api/judge/batch/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const data = await res.json();
      if (res.ok) {
        setActionMessage(`🔄 Batch Senkronizasyonu: ${data.synced_count || 0} yeni kayıt veritabanına eşitlendi.`);
        refreshAll();
      } else {
        setActionMessage(`❌ Eşitleme hatası: ${data.detail || 'Bilinmeyen hata'}`);
      }
    } catch (e: any) {
      setActionMessage(`❌ Eşitleme isteği hatası: ${e.message}`);
    } finally {
      setSyncingBatch(false);
    }
  };

  const handleRunScheduledTrigger = async () => {
    setIsTriggerRunning(true);
    setActionMessage(null);
    try {
      const res = await fetch('/api/triggers/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          limit: 50,
          mode: 'strict',
          threshold,
          use_batch_api: triggerUseBatch,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        setActionMessage(`⚡ Otonom Denetim Tetiklendi: ${data.message || 'Başarıyla tamamlandı.'}`);
        refreshAll();
      } else {
        setActionMessage(`❌ Tetikleyici hatası: ${data.detail || 'Bilinmeyen hata'}`);
      }
    } catch (e: any) {
      setActionMessage(`❌ İstek hatası: ${e.message}`);
    } finally {
      setIsTriggerRunning(false);
    }
  };

  // Safe formatting helpers
  const totalTokensFormatted = budgetInfo?.total_tokens != null ? Number(budgetInfo.total_tokens).toLocaleString() : '0';
  const monthlyLimitFormatted = budgetInfo?.monthly_limit_tokens != null ? (Number(budgetInfo.monthly_limit_tokens) / 1_000_000).toFixed(0) : '100';
  const estimatedCostFormatted = budgetInfo?.estimated_cost_tl != null ? Number(budgetInfo.estimated_cost_tl).toFixed(2) : '0.00';
  const remainingGrantFormatted = budgetInfo?.remaining_grant_tl != null ? Number(budgetInfo.remaining_grant_tl).toFixed(2) : '473.98';
  const budgetPercent = budgetInfo?.budget_percent != null ? Number(budgetInfo.budget_percent) : 0.0;

  const totalJudgedCount = judgeStats?.total_judged != null ? Number(judgeStats.total_judged).toLocaleString() : '0';
  const approvedCount = judgeStats?.approved != null ? Number(judgeStats.approved).toLocaleString() : '0';
  const borderlineCount = judgeStats?.borderline != null ? Number(judgeStats.borderline).toLocaleString() : '0';
  const rejectedCount = judgeStats?.rejected != null ? Number(judgeStats.rejected).toLocaleString() : '0';
  const avgScoreFormatted = judgeStats?.average_score != null ? Number(judgeStats.average_score).toFixed(1) : '0.0';

  const preHookDecision = hookAudit?.pre_hook_safe_test?.decision || 'allow';
  const postHookStatus = hookAudit?.post_hook_linter_test?.status || 'passed';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      {/* 1. TOP BANNER: Google Developer Program & Token Bütçesi */}
      <div className="card" style={{ background: 'linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%)', border: '1px solid rgba(99, 102, 241, 0.3)', boxShadow: '0 4px 20px rgba(0,0,0,0.4)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
              <span style={{ fontSize: '1.5rem' }}>💎</span>
              <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 700, color: '#f8fafc' }}>
                Google Developer Program Kredi & Token Bütçe Yöneticisi
              </h3>
              <span className="badge online" style={{ background: 'rgba(99, 102, 241, 0.2)', color: '#a5b4fc', border: '1px solid rgba(99, 102, 241, 0.4)' }}>
                Gemini 3.6 Flash / 2.5 Pro
              </span>
            </div>
            <p style={{ margin: '0.35rem 0 0 0', fontSize: '0.82rem', color: '#cbd5e1' }}>
              Aylık düzenli hibe: <strong style={{ color: '#34d399' }}>₺473,98</strong> | Güvenli otomatik bütçe kapısı ve aşım koruması.
            </p>
          </div>

          <button
            onClick={refreshAll}
            className="btn btn-secondary"
            style={{ fontSize: '0.8rem', padding: '0.4rem 0.85rem' }}
          >
            🔄 Verileri Yenile
          </button>
        </div>

        {/* Budget Progress Bar & Breakdown */}
        <div style={{ marginTop: '1rem', paddingTop: '1rem', borderTop: '1px solid rgba(99, 102, 241, 0.2)', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem' }}>
          <div style={{ background: 'rgba(0,0,0,0.35)', padding: '0.75rem 1rem', borderRadius: 'var(--radius-md)', border: '1px solid rgba(255,255,255,0.05)' }}>
            <span style={{ fontSize: '0.72rem', color: '#94a3b8', display: 'block' }}>Bu Ay Harcanan Token</span>
            <strong style={{ fontSize: '1.15rem', color: '#a5b4fc' }}>{totalTokensFormatted}</strong>
            <span style={{ fontSize: '0.72rem', color: '#64748b', display: 'block' }}>/ {monthlyLimitFormatted}M Tavan Limit</span>
          </div>

          <div style={{ background: 'rgba(0,0,0,0.35)', padding: '0.75rem 1rem', borderRadius: 'var(--radius-md)', border: '1px solid rgba(255,255,255,0.05)' }}>
            <span style={{ fontSize: '0.72rem', color: '#94a3b8', display: 'block' }}>Tahmini Harcama</span>
            <strong style={{ fontSize: '1.15rem', color: '#34d399' }}>₺{estimatedCostFormatted}</strong>
            <span style={{ fontSize: '0.72rem', color: '#64748b', display: 'block' }}>Kalan Hibe: ₺{remainingGrantFormatted}</span>
          </div>

          <div style={{ background: 'rgba(0,0,0,0.35)', padding: '0.75rem 1rem', borderRadius: 'var(--radius-md)', border: '1px solid rgba(255,255,255,0.05)', gridColumn: 'span 2' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#cbd5e1', marginBottom: '0.4rem' }}>
              <span>Bütçe Kullanım Oranı</span>
              <strong style={{ color: '#a5b4fc' }}>%{budgetPercent.toFixed(2)}</strong>
            </div>
            <div style={{ width: '100%', height: '8px', background: '#1e293b', borderRadius: '999px', overflow: 'hidden' }}>
              <div
                style={{
                  width: `${Math.min(100, Math.max(0.5, budgetPercent))}%`,
                  height: '100%',
                  background: 'linear-gradient(90deg, #10b981, #6366f1, #f59e0b)',
                  transition: 'width 0.4s ease',
                }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* 2. MAIN GRID: Judge Controls & Scoreboard */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '1.25rem' }}>
        {/* Left Column: Form Controls */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div className="card-title" style={{ justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.5rem' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span>⚖️</span>
              <span>LLM Hakem & Editor-in-Chief</span>
            </span>
            <span className="badge online" style={{ fontSize: '0.72rem' }}>{activeProjectId}</span>
          </div>

          {/* Mode Selector */}
          <div>
            <label style={{ fontSize: '0.75rem', fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', display: 'block', marginBottom: '0.4rem' }}>
              Hakem Çalışma Modu
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.6rem' }}>
              <button
                type="button"
                onClick={() => setMode('strict')}
                className="btn"
                style={{
                  textAlign: 'left',
                  padding: '0.6rem 0.75rem',
                  borderRadius: 'var(--radius-md)',
                  background: mode === 'strict' ? 'rgba(99, 102, 241, 0.2)' : 'var(--bg-primary)',
                  border: mode === 'strict' ? '1px solid #6366f1' : '1px solid var(--border-color)',
                  color: mode === 'strict' ? '#ffffff' : 'var(--text-secondary)',
                }}
              >
                <div style={{ fontWeight: 700, fontSize: '0.82rem', color: mode === 'strict' ? '#a5b4fc' : undefined }}>1. Strict Judge</div>
                <div style={{ fontSize: '0.7rem', color: '#94a3b8', marginTop: '0.2rem' }}>Hızlı 1-10 puanlama & eleme.</div>
              </button>

              <button
                type="button"
                onClick={() => setMode('hybrid_editor')}
                className="btn"
                style={{
                  textAlign: 'left',
                  padding: '0.6rem 0.75rem',
                  borderRadius: 'var(--radius-md)',
                  background: mode === 'hybrid_editor' ? 'rgba(245, 158, 11, 0.2)' : 'var(--bg-primary)',
                  border: mode === 'hybrid_editor' ? '1px solid #f59e0b' : '1px solid var(--border-color)',
                  color: mode === 'hybrid_editor' ? '#ffffff' : 'var(--text-secondary)',
                }}
              >
                <div style={{ fontWeight: 700, fontSize: '0.82rem', color: mode === 'hybrid_editor' ? '#fde68a' : undefined }}>2. Editor-in-Chief</div>
                <div style={{ fontSize: '0.7rem', color: '#94a3b8', marginTop: '0.2rem' }}>Sınırda kalanları cerrahi onarır.</div>
              </button>
            </div>
          </div>

          {/* Execution Channel: Online vs Gemini Batch API */}
          <div>
            <label style={{ fontSize: '0.75rem', fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', display: 'block', marginBottom: '0.4rem' }}>
              İşlem Tipi & API Kanalı
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.6rem' }}>
              <button
                type="button"
                onClick={() => setExecutionType('online')}
                className="btn"
                style={{
                  textAlign: 'left',
                  padding: '0.55rem 0.75rem',
                  borderRadius: 'var(--radius-md)',
                  background: executionType === 'online' ? 'rgba(59, 130, 246, 0.2)' : 'var(--bg-primary)',
                  border: executionType === 'online' ? '1px solid #3b82f6' : '1px solid var(--border-color)',
                  color: executionType === 'online' ? '#ffffff' : 'var(--text-secondary)',
                }}
              >
                <div style={{ fontWeight: 700, fontSize: '0.8rem', color: executionType === 'online' ? '#93c5fd' : undefined }}>⚡ Gerçek Zamanlı (Anlık)</div>
                <div style={{ fontSize: '0.68rem', color: '#94a3b8', marginTop: '0.15rem' }}>Doğrudan değerlendirir.</div>
              </button>

              <button
                type="button"
                onClick={() => setExecutionType('batch')}
                className="btn"
                style={{
                  textAlign: 'left',
                  padding: '0.55rem 0.75rem',
                  borderRadius: 'var(--radius-md)',
                  background: executionType === 'batch' ? 'rgba(16, 185, 129, 0.2)' : 'var(--bg-primary)',
                  border: executionType === 'batch' ? '1px solid #10b981' : '1px solid var(--border-color)',
                  color: executionType === 'batch' ? '#ffffff' : 'var(--text-secondary)',
                }}
              >
                <div style={{ fontWeight: 700, fontSize: '0.8rem', color: executionType === 'batch' ? '#6ee7b7' : undefined }}>📦 Gemini Batch API</div>
                <div style={{ fontSize: '0.68rem', color: '#34d399', marginTop: '0.15rem' }}>%50 İndirimli & Kotasız</div>
              </button>
            </div>
          </div>

          {/* Threshold Slider */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.4rem' }}>
              <label style={{ fontSize: '0.75rem', fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase' }}>
                Onay Eşiği Puanı
              </label>
              <span className="badge online" style={{ fontSize: '0.8rem', fontWeight: 700 }}>
                {threshold.toFixed(1)} / 10.0
              </span>
            </div>
            <input
              type="range"
              min="1.0"
              max="9.5"
              step="0.5"
              value={threshold}
              onChange={(e) => setThreshold(parseFloat(e.target.value))}
              style={{ width: '100%', cursor: 'pointer' }}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.68rem', color: '#64748b', marginTop: '0.2rem' }}>
              <span>1.0 (Esnek)</span>
              <span>7.0 (Önerilen Standart)</span>
              <span>9.5 (Katı)</span>
            </div>
          </div>

          {/* Limit Selector */}
          <div>
            <label style={{ fontSize: '0.75rem', fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', display: 'block', marginBottom: '0.4rem' }}>
              Örnek Sayısı (Limit)
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.4rem' }}>
              {['10', '25', '50', 'all'].map((val) => (
                <button
                  key={val}
                  type="button"
                  onClick={() => setLimit(val)}
                  className="btn"
                  style={{
                    padding: '0.4rem 0',
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    borderRadius: 'var(--radius-md)',
                    background: limit === val ? '#6366f1' : 'var(--bg-primary)',
                    color: limit === val ? '#ffffff' : 'var(--text-secondary)',
                    border: limit === val ? '1px solid #6366f1' : '1px solid var(--border-color)',
                  }}
                >
                  {val === 'all' ? 'Tümü' : `${val} Adet`}
                </button>
              ))}
            </div>
          </div>

          {/* Action Message */}
          {actionMessage && (
            <div style={{ padding: '0.6rem 0.8rem', background: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', fontSize: '0.78rem', color: '#f1f5f9' }}>
              {actionMessage}
            </div>
          )}

          {/* Run Button */}
          <button
            onClick={handleRunJudge}
            disabled={loading}
            className={`btn ${loading ? 'btn-disabled' : executionType === 'batch' ? 'btn-secondary' : 'btn-primary'}`}
            style={{
              width: '100%',
              padding: '0.75rem',
              fontSize: '0.85rem',
              fontWeight: 700,
              marginTop: 'auto',
              background: executionType === 'batch' ? 'linear-gradient(135deg, #059669 0%, #10b981 100%)' : undefined,
              color: '#ffffff',
            }}
          >
            {loading
              ? '⚙️ İşlem Yürütülüyor...'
              : executionType === 'batch'
              ? `📦 Gemini Batch Job Başlat (%50 İndirimli ${mode === 'strict' ? 'Strict' : 'Editor'})`
              : `🎯 Hakem Kalite Denetimini Başlat (${mode === 'strict' ? 'Strict' : 'Editor'})`}
          </button>
        </div>

        {/* Right Column: Scoreboard & Hooks */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          {/* Scoreboard Card */}
          <div className="card">
            <div className="card-title" style={{ justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.5rem' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span>📊</span>
                <span>Hakem Skor Dağılımı</span>
              </span>
              <span style={{ fontSize: '0.78rem', fontWeight: 700, color: '#34d399' }}>
                Ortalama: {avgScoreFormatted} / 10
              </span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '0.75rem', marginTop: '0.75rem' }}>
              <div style={{ background: 'var(--bg-primary)', padding: '0.75rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)', textAlign: 'center' }}>
                <span style={{ fontSize: '0.7rem', color: '#94a3b8', textTransform: 'uppercase', display: 'block' }}>Toplam Denetlenen</span>
                <strong style={{ fontSize: '1.35rem', color: '#f8fafc', display: 'block', marginTop: '0.2rem' }}>{totalJudgedCount}</strong>
              </div>

              <div style={{ background: 'rgba(16, 185, 129, 0.1)', padding: '0.75rem', borderRadius: 'var(--radius-md)', border: '1px solid rgba(16, 185, 129, 0.3)', textAlign: 'center' }}>
                <span style={{ fontSize: '0.7rem', color: '#34d399', textTransform: 'uppercase', display: 'block' }}>Onaylanan (Approved)</span>
                <strong style={{ fontSize: '1.35rem', color: '#34d399', display: 'block', marginTop: '0.2rem' }}>{approvedCount}</strong>
              </div>

              <div style={{ background: 'rgba(245, 158, 11, 0.1)', padding: '0.75rem', borderRadius: 'var(--radius-md)', border: '1px solid rgba(245, 158, 11, 0.3)', textAlign: 'center' }}>
                <span style={{ fontSize: '0.7rem', color: '#f59e0b', textTransform: 'uppercase', display: 'block' }}>Yeniden Yazılan</span>
                <strong style={{ fontSize: '1.35rem', color: '#f59e0b', display: 'block', marginTop: '0.2rem' }}>{borderlineCount}</strong>
              </div>

              <div style={{ background: 'rgba(244, 63, 94, 0.1)', padding: '0.75rem', borderRadius: 'var(--radius-md)', border: '1px solid rgba(244, 63, 94, 0.3)', textAlign: 'center' }}>
                <span style={{ fontSize: '0.7rem', color: '#f43f5e', textTransform: 'uppercase', display: 'block' }}>Reddedilen</span>
                <strong style={{ fontSize: '1.35rem', color: '#f43f5e', display: 'block', marginTop: '0.2rem' }}>{rejectedCount}</strong>
              </div>
            </div>
          </div>

          {/* Hooks & Triggers Card */}
          <div className="card">
            <div className="card-title" style={{ justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.5rem' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span>🛡️</span>
                <span>Managed Agents Hooks & Otonom Tetikleyiciler</span>
              </span>
              <span className="badge online" style={{ fontSize: '0.7rem' }}>.agents/hooks.json</span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginTop: '0.75rem' }}>
              <div style={{ background: 'var(--bg-primary)', padding: '0.6rem 0.75rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.78rem', fontWeight: 700, color: '#f1f5f9' }}>Pre-Tool Gate</span>
                  <span className="badge online" style={{ fontSize: '0.65rem' }}>{preHookDecision}</span>
                </div>
                <p style={{ margin: '0.3rem 0 0 0', fontSize: '0.68rem', color: '#94a3b8' }}>
                  Tehlikeli komut ve token bütçe aşım koruması.
                </p>
              </div>

              <div style={{ background: 'var(--bg-primary)', padding: '0.6rem 0.75rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.78rem', fontWeight: 700, color: '#f1f5f9' }}>Dataset Linter</span>
                  <span className="badge online" style={{ fontSize: '0.65rem' }}>{postHookStatus}</span>
                </div>
                <p style={{ margin: '0.3rem 0 0 0', fontSize: '0.68rem', color: '#94a3b8' }}>
                  AST sözdizimi, LaTeX denge ve JSON şema denetimi.
                </p>
              </div>
            </div>

            <div style={{ marginTop: '0.75rem', paddingTop: '0.75rem', borderTop: '1px solid var(--border-color)', display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.72rem', color: '#cbd5e1', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={triggerUseBatch}
                    onChange={(e) => setTriggerUseBatch(e.target.checked)}
                  />
                  <span>Otonom tetikleyicide <strong>Gemini Batch API (%50 İndirim)</strong> kullan</span>
                </label>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
                <span style={{ fontSize: '0.72rem', color: '#94a3b8' }}>
                  Düşük kullanım saatlerinde denetlenmemiş verileri otonom tarar.
                </span>
                <button
                  onClick={handleRunScheduledTrigger}
                  disabled={isTriggerRunning}
                  className="btn btn-secondary"
                  style={{ fontSize: '0.75rem', padding: '0.35rem 0.75rem' }}
                >
                  {isTriggerRunning ? '⚙️ Çalışıyor...' : '⚡ Otonom Denetimi Tetikle'}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 3. GEMINI BATCH JOBS MONITORING CARD */}
      <div className="card">
        <div className="card-title" style={{ justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.5rem' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span>📦</span>
            <span>Gemini Batch Prediction İş Takipçisi (Asenkron & %50 İndirimli)</span>
          </span>
          <button
            onClick={handleSyncBatchJobs}
            disabled={syncingBatch}
            className="btn btn-secondary"
            style={{ fontSize: '0.75rem', padding: '0.3rem 0.7rem' }}
          >
            {syncingBatch ? '🔄 Eşitleniyor...' : '🔄 Tamamlananları Eşitle (Sync)'}
          </button>
        </div>

        {batchJobs.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '1.5rem', color: '#64748b', fontSize: '0.82rem' }}>
            Henüz oluşturulmuş bir Gemini Batch işi bulunmuyor. Toplu iş gönderildiğinde burada listelenecektir.
          </div>
        ) : (
          <div style={{ overflowX: 'auto', marginTop: '0.5rem' }}>
            <table style={{ width: '100%', fontSize: '0.75rem', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-color)', color: '#94a3b8', textAlign: 'left' }}>
                  <th style={{ padding: '0.5rem' }}>İş ID (Job Name)</th>
                  <th style={{ padding: '0.5rem' }}>Model</th>
                  <th style={{ padding: '0.5rem' }}>Mod</th>
                  <th style={{ padding: '0.5rem' }}>Örnek Sayısı</th>
                  <th style={{ padding: '0.5rem' }}>Durum (State)</th>
                  <th style={{ padding: '0.5rem' }}>Oluşturulma</th>
                  <th style={{ padding: '0.5rem', textAlign: 'right' }}>İşlem</th>
                </tr>
              </thead>
              <tbody>
                {batchJobs.map((job) => {
                  const isCompleted = job.state === 'COMPLETED' || job.state === 'JOB_STATE_SUCCEEDED';
                  const isFailed = job.state === 'FAILED' || job.state === 'JOB_STATE_FAILED';
                  const isRunning = job.state === 'JOB_STATE_RUNNING' || job.state === 'PENDING' || job.state === 'JOB_STATE_PENDING';

                  return (
                    <tr key={job.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                      <td style={{ padding: '0.5rem', fontFamily: 'monospace', color: '#a5b4fc' }}>
                        {job.job_id}
                      </td>
                      <td style={{ padding: '0.5rem', color: '#cbd5e1' }}>{job.model}</td>
                      <td style={{ padding: '0.5rem', textTransform: 'capitalize' }}>{job.mode}</td>
                      <td style={{ padding: '0.5rem', color: '#cbd5e1' }}>{job.total_requests} adet</td>
                      <td style={{ padding: '0.5rem' }}>
                        <span
                          className={`badge ${isCompleted ? 'online' : isFailed ? 'offline' : ''}`}
                          style={{
                            fontSize: '0.68rem',
                            background: isCompleted ? 'rgba(16, 185, 129, 0.2)' : isRunning ? 'rgba(59, 130, 246, 0.2)' : undefined,
                            color: isCompleted ? '#34d399' : isRunning ? '#60a5fa' : undefined,
                          }}
                        >
                          {job.state}
                        </span>
                      </td>
                      <td style={{ padding: '0.5rem', color: '#64748b' }}>
                        {job.created_at ? new Date(job.created_at).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' }) : '-'}
                      </td>
                      <td style={{ padding: '0.5rem', textAlign: 'right' }}>
                        <button
                          type="button"
                          onClick={() => handleCancelBatchJob(job.job_id)}
                          className="btn"
                          style={{
                            fontSize: '0.68rem',
                            padding: '0.2rem 0.5rem',
                            background: 'rgba(239, 68, 68, 0.15)',
                            border: '1px solid rgba(239, 68, 68, 0.3)',
                            color: '#f87171',
                            borderRadius: 'var(--radius-sm)',
                          }}
                          title="Bu batch işini sil veya iptal et"
                        >
                          🗑️ Sil
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
