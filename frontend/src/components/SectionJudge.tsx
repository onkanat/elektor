import React, { useState, useEffect } from 'react';
import type { JudgeStats, TokenBudgetInfo, HookAuditInfo, PipelineConfig } from '../types';

interface SectionJudgeProps {
  config: PipelineConfig | null;
  activeProjectId: string;
  onRefreshHealth?: () => void;
}

export const SectionJudge: React.FC<SectionJudgeProps> = ({
  config: _config,
  activeProjectId,
  onRefreshHealth,
}) => {
  const [judgeStats, setJudgeStats] = useState<JudgeStats | null>(null);
  const [budgetInfo, setBudgetInfo] = useState<TokenBudgetInfo | null>(null);
  const [hookAudit, setHookAudit] = useState<HookAuditInfo | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  // Form parameters
  const [mode, setMode] = useState<'strict' | 'hybrid_editor'>('strict');
  const [threshold, setThreshold] = useState<number>(7.0);
  const [limit, setLimit] = useState<string>('50');
  const [isTriggerRunning, setIsTriggerRunning] = useState<boolean>(false);

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
        setBudgetInfo(data.consumption || data);
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

  const refreshAll = () => {
    fetchJudgeStats();
    fetchBudgetInfo();
    fetchHookAudit();
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
        setActionMessage(`✅ Hakem değerlendirmesi tamamlandı: ${data.approved || 0} onaylandı, ${data.borderline || 0} yeniden yazıldı, ${data.rejected || 0} reddedildi.`);
        refreshAll();
      } else {
        setActionMessage(`❌ Hata: ${data.detail || 'Hakem çalıştırma başarısız.'}`);
      }
    } catch (e: any) {
      setActionMessage(`❌ İstek hatası: ${e.message}`);
    } finally {
      setLoading(false);
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

  return (
    <div className="space-y-6 animate-fadeIn pb-12">
      {/* Top Banner: Google Developer Program & Token Budget Bar */}
      <div className="bg-gradient-to-r from-gray-900 via-indigo-950 to-gray-900 border border-indigo-500/30 rounded-2xl p-6 shadow-2xl relative overflow-hidden">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 relative z-10">
          <div>
            <div className="flex items-center space-x-3">
              <span className="text-2xl">💎</span>
              <h2 className="text-xl font-bold text-white tracking-wide">
                Google Developer Program Kredi & Token Bütçe Yöneticisi
              </h2>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-indigo-500/20 text-indigo-300 border border-indigo-500/40">
                Gemini 3.6 Flash / 2.5 Pro
              </span>
            </div>
            <p className="text-sm text-gray-300 mt-1">
              Aylık düzenli hibe: <strong className="text-emerald-400">₺473,98</strong> | Güvenli otomatik bütçe kapısı ve aşım koruması.
            </p>
          </div>

          <button
            onClick={refreshAll}
            className="self-start md:self-auto px-4 py-2 bg-indigo-600/30 hover:bg-indigo-600/50 text-indigo-200 border border-indigo-500/40 rounded-xl text-sm font-medium transition flex items-center space-x-2"
          >
            <span>🔄</span>
            <span>Verileri Yenile</span>
          </button>
        </div>

        {/* Budget Progress Bar */}
        <div className="mt-6 pt-4 border-t border-indigo-500/20 grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="bg-black/40 rounded-xl p-3 border border-indigo-500/20">
            <span className="text-xs text-gray-400 block">Bu Ay Harcanan Token</span>
            <span className="text-lg font-bold text-indigo-300">
              {budgetInfo ? budgetInfo.total_tokens.toLocaleString() : '0'}
            </span>
            <span className="text-xs text-gray-500 block">
              / {budgetInfo ? (budgetInfo.monthly_limit_tokens / 1_000_000).toFixed(0) : '100'}M Limit
            </span>
          </div>

          <div className="bg-black/40 rounded-xl p-3 border border-indigo-500/20">
            <span className="text-xs text-gray-400 block">Tahmini Harcama</span>
            <span className="text-lg font-bold text-emerald-400">
              ₺{budgetInfo ? budgetInfo.estimated_cost_tl.toFixed(2) : '0.00'}
            </span>
            <span className="text-xs text-gray-500 block">
              Kalan Hibe: ₺{budgetInfo ? budgetInfo.remaining_grant_tl.toFixed(2) : '473.98'}
            </span>
          </div>

          <div className="bg-black/40 rounded-xl p-3 border border-indigo-500/20 md:col-span-2 flex flex-col justify-center">
            <div className="flex justify-between text-xs text-gray-300 mb-1">
              <span>Bütçe Kullanım Oranı</span>
              <span className="font-semibold text-indigo-300">
                %{budgetInfo ? budgetInfo.budget_percent.toFixed(2) : '0.00'}
              </span>
            </div>
            <div className="w-full bg-gray-800 rounded-full h-3 overflow-hidden border border-gray-700">
              <div
                className="bg-gradient-to-r from-emerald-500 via-indigo-500 to-amber-500 h-full rounded-full transition-all duration-500"
                style={{ width: `${Math.min(100, budgetInfo?.budget_percent || 0.5)}%` }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Main Content Grid: Judge Configuration (Left) & Stats Dashboard (Right) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Judge & Editor Execution Form */}
        <div className="lg:col-span-5 bg-gray-900 border border-gray-800 rounded-2xl p-6 shadow-xl space-y-6">
          <div className="flex items-center justify-between border-b border-gray-800 pb-3">
            <div className="flex items-center space-x-2">
              <span className="text-xl">⚖️</span>
              <h3 className="font-bold text-white text-base">LLM Hakem & Editor-in-Chief</h3>
            </div>
            <span className="text-xs text-gray-400">Proje: {activeProjectId}</span>
          </div>

          {/* Mode Selector */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-gray-300 uppercase tracking-wider block">
              Hakem Çalışma Modu
            </label>
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setMode('strict')}
                className={`p-3 rounded-xl border text-left transition ${
                  mode === 'strict'
                    ? 'bg-indigo-600/20 border-indigo-500 text-white shadow-lg'
                    : 'bg-gray-800/60 border-gray-700 text-gray-400 hover:bg-gray-800'
                }`}
              >
                <div className="font-bold text-sm text-indigo-300">1. Strict Judge</div>
                <div className="text-xs text-gray-400 mt-1">Hızlı 1-10 puanlama & eleme (Ekonomik token).</div>
              </button>

              <button
                type="button"
                onClick={() => setMode('hybrid_editor')}
                className={`p-3 rounded-xl border text-left transition ${
                  mode === 'hybrid_editor'
                    ? 'bg-amber-600/20 border-amber-500 text-white shadow-lg'
                    : 'bg-gray-800/60 border-gray-700 text-gray-400 hover:bg-gray-800'
                }`}
              >
                <div className="font-bold text-sm text-amber-300">2. Editor-in-Chief</div>
                <div className="text-xs text-gray-400 mt-1">Sınırda kalanları cerrahi yeniden yazıp onarır.</div>
              </button>
            </div>
          </div>

          {/* Approval Threshold Slider */}
          <div className="space-y-2">
            <div className="flex justify-between items-center">
              <label className="text-xs font-semibold text-gray-300 uppercase tracking-wider">
                Onay Eşiği Puanı (Threshold)
              </label>
              <span className="text-sm font-bold text-emerald-400 px-2 py-0.5 bg-emerald-500/10 border border-emerald-500/30 rounded-lg">
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
              className="w-full h-2 bg-gray-800 rounded-lg appearance-none cursor-pointer accent-indigo-500"
            />
            <div className="flex justify-between text-2xs text-gray-500">
              <span>1.0 (Tümünü Onayla)</span>
              <span>7.0 (Önerilen)</span>
              <span>9.5 (Çok Katı)</span>
            </div>
          </div>

          {/* Record Limit Selector */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-gray-300 uppercase tracking-wider block">
              Değerlendirilecek Kayıt Sayısı
            </label>
            <div className="grid grid-cols-4 gap-2">
              {['10', '25', '50', 'all'].map((val) => (
                <button
                  key={val}
                  type="button"
                  onClick={() => setLimit(val)}
                  className={`py-2 rounded-xl text-xs font-semibold border transition ${
                    limit === val
                      ? 'bg-indigo-600 border-indigo-500 text-white shadow-md'
                      : 'bg-gray-800 border-gray-700 text-gray-400 hover:bg-gray-750'
                  }`}
                >
                  {val === 'all' ? 'Tümü' : `${val} Adet`}
                </button>
              ))}
            </div>
          </div>

          {/* Action Message Alert */}
          {actionMessage && (
            <div className="p-3 rounded-xl bg-gray-800/90 border border-gray-700 text-xs text-gray-200 animate-fadeIn">
              {actionMessage}
            </div>
          )}

          {/* Run Button */}
          <button
            onClick={handleRunJudge}
            disabled={loading}
            className={`w-full py-3.5 px-4 rounded-xl font-bold text-sm shadow-xl flex items-center justify-center space-x-2 transition ${
              loading
                ? 'bg-gray-700 text-gray-400 cursor-not-allowed'
                : 'bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 text-white'
            }`}
          >
            {loading ? (
              <>
                <span className="animate-spin text-lg">⚙️</span>
                <span>Hakem Değerlendirmesi Yürütülüyor...</span>
              </>
            ) : (
              <>
                <span>🎯</span>
                <span>Hakem Kalite Denetimini Başlat ({mode === 'strict' ? 'Strict' : 'Editor'})</span>
              </>
            )}
          </button>
        </div>

        {/* Right Column: Judge Scoreboard & Environment Hooks */}
        <div className="lg:col-span-7 space-y-6">
          {/* Judge Stats Cards */}
          <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-gray-800 pb-3">
              <div className="flex items-center space-x-2">
                <span className="text-xl">📊</span>
                <h3 className="font-bold text-white text-base">Hakem Skor Dağılımı</h3>
              </div>
              <span className="text-xs text-emerald-400 font-semibold">
                Ortalama Puan: {judgeStats ? judgeStats.average_score.toFixed(1) : '0.0'} / 10
              </span>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              <div className="bg-black/30 border border-gray-800 rounded-xl p-4 text-center">
                <span className="text-2xs text-gray-400 uppercase tracking-wider block">Toplam Denetlenen</span>
                <span className="text-2xl font-extrabold text-white mt-1 block">
                  {judgeStats ? judgeStats.total_judged.toLocaleString() : '0'}
                </span>
              </div>

              <div className="bg-emerald-950/20 border border-emerald-500/30 rounded-xl p-4 text-center">
                <span className="text-2xs text-emerald-400 uppercase tracking-wider block">Onaylanan (Approved)</span>
                <span className="text-2xl font-extrabold text-emerald-400 mt-1 block">
                  {judgeStats ? judgeStats.approved.toLocaleString() : '0'}
                </span>
              </div>

              <div className="bg-amber-950/20 border border-amber-500/30 rounded-xl p-4 text-center">
                <span className="text-2xs text-amber-400 uppercase tracking-wider block">Yeniden Yazılan</span>
                <span className="text-2xl font-extrabold text-amber-400 mt-1 block">
                  {judgeStats ? judgeStats.borderline.toLocaleString() : '0'}
                </span>
              </div>

              <div className="bg-rose-950/20 border border-rose-500/30 rounded-xl p-4 text-center">
                <span className="text-2xs text-rose-400 uppercase tracking-wider block">Reddedilen</span>
                <span className="text-2xl font-extrabold text-rose-400 mt-1 block">
                  {judgeStats ? judgeStats.rejected.toLocaleString() : '0'}
                </span>
              </div>
            </div>
          </div>

          {/* Managed Agents Hooks & Scheduled Triggers Panel */}
          <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-gray-800 pb-3">
              <div className="flex items-center space-x-2">
                <span className="text-xl">🛡️</span>
                <h3 className="font-bold text-white text-base">Managed Agents Hooks & Otonom Tetikleyiciler</h3>
              </div>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                .agents/hooks.json Aktif
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Pre-Tool Security Gate */}
              <div className="bg-black/30 border border-gray-800 rounded-xl p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-gray-200">Pre-Tool Security Gate</span>
                  <span className="text-2xs font-semibold px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/40">
                    Korumalı
                  </span>
                </div>
                <p className="text-2xs text-gray-400">
                  Tehlikeli komut kalıplarını (`rm -rf`, `forkbomb`) ve token bütçe tavan aşımını otomatik engeller.
                </p>
                <div className="text-2xs text-gray-500 font-mono">
                  Son Test: {hookAudit ? hookAudit.pre_hook_safe_test.decision : 'allow'}
                </div>
              </div>

              {/* Post-Tool Dataset Linter */}
              <div className="bg-black/30 border border-gray-800 rounded-xl p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-gray-200">Post-Tool Dataset Linter</span>
                  <span className="text-2xs font-semibold px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-400 border border-indigo-500/40">
                    AST + LaTeX
                  </span>
                </div>
                <p className="text-2xs text-gray-400">
                  Python `ast.parse` kod doğruluğu, LaTeX formül dengesi ve JSON şema bütünlüğünü denetler.
                </p>
                <div className="text-2xs text-gray-500 font-mono">
                  Linter Durumu: {hookAudit ? hookAudit.post_hook_linter_test.status : 'passed'}
                </div>
              </div>
            </div>

            {/* Autonomous Scheduled Trigger Button */}
            <div className="pt-2 flex flex-col sm:flex-row items-center justify-between gap-3 border-t border-gray-800/80">
              <div className="text-xs text-gray-400">
                Düşük kullanım saatlerinde (gece/off-peak) denetlenmemiş verileri bütçe dahilinde otonom iyileştirir.
              </div>
              <button
                onClick={handleRunScheduledTrigger}
                disabled={isTriggerRunning}
                className="px-4 py-2 bg-indigo-900/40 hover:bg-indigo-900/70 border border-indigo-500/40 text-indigo-200 rounded-xl text-xs font-semibold transition whitespace-nowrap flex items-center space-x-2"
              >
                {isTriggerRunning ? (
                  <>
                    <span className="animate-spin">⚙️</span>
                    <span>Tetikleyici Çalışıyor...</span>
                  </>
                ) : (
                  <>
                    <span>⚡</span>
                    <span>Otonom Denetimi Tetikle (Trigger)</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
