import { useState, useEffect, useRef } from 'react';
import type { PipelineConfig, PipelineState } from '../types';
import { ResetConfirmModal } from './ResetConfirmModal';

interface SectionConfigProps {
  config: PipelineConfig;
  onUpdateConfig: (newConfig: Partial<PipelineConfig>) => Promise<void>;
  pipelineState: PipelineState;
  onRunPipeline: (command: string, limit?: string, reset?: boolean, confirmReset?: boolean) => void;
}

export const SectionConfig: React.FC<SectionConfigProps> = ({
  config,
  onUpdateConfig,
  pipelineState,
  onRunPipeline,
}) => {
  const [formData, setFormData] = useState<PipelineConfig>(config);
  const [limitInput, setLimitInput] = useState<string>('5');
  const [resetInput, setResetInput] = useState<boolean>(false);
  const [jsonText, setJsonText] = useState<string>(JSON.stringify(config, null, 2));
  const [isEditingJson, setIsEditingJson] = useState<boolean>(false);
  const [saveSuccess, setSaveSuccess] = useState<boolean>(false);
  const [showResetModal, setShowResetModal] = useState<boolean>(false);
  const [pendingCommand, setPendingCommand] = useState<{ cmd: string; limit?: string }>({ cmd: 'pipeline', limit: '5' });

  const terminalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setFormData(config);
    setJsonText(JSON.stringify(config, null, 2));
  }, [config]);

  // Auto-scroll terminal log widget to bottom when logs update
  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [pipelineState.logs]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
    const { name, value, type } = e.target;
    const val = type === 'number' ? Number(value) : value;
    const updated = { ...formData, [name]: val };
    setFormData(updated);
    setJsonText(JSON.stringify(updated, null, 2));
  };

  const handleSaveForm = async () => {
    await onUpdateConfig(formData);
    setSaveSuccess(true);
    setTimeout(() => setSaveSuccess(false), 3000);
  };

  const handleSaveJson = async () => {
    try {
      const parsed = JSON.parse(jsonText);
      await onUpdateConfig(parsed);
      setFormData(parsed);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (e) {
      alert('Geçersiz JSON formatı! Lütfen kontrol edin.');
    }
  };

  const handleTrigger = (cmd: string, limit?: string) => {
    if (resetInput) {
      setPendingCommand({ cmd, limit });
      setShowResetModal(true);
    } else {
      onRunPipeline(cmd, limit, false, false);
    }
  };

  const isRunning = pipelineState.status === 'running';

  return (
    <div className="grid-2">
      <ResetConfirmModal
        isOpen={showResetModal}
        projectName={formData.dataset_name || formData.project_id || 'sdr_engineers'}
        projectId={formData.project_id || 'sdr_engineers'}
        onCancel={() => setShowResetModal(false)}
        onConfirm={() => {
          onRunPipeline(pendingCommand.cmd, pendingCommand.limit, true, true);
          setShowResetModal(false);
        }}
      />

      {/* Sol Kart: Döküman & Yapılandırma Parametreleri */}
      <div className="card">
        <div className="card-title">
          <span>📁</span> 1. Döküman & Sentetik Veri Parametreleri
        </div>

        <div className="form-group">
          <label>İşleme Modu (Input Mode)</label>
          <select
            name="input_mode"
            className="form-control"
            value={formData.input_mode}
            onChange={handleChange}
          >
            <option value="book">Book Mode (Tek Kitap/PDF Bölümleme)</option>
            <option value="folder">Folder Mode (Özyinelemeli PDF Klasörü)</option>
          </select>
        </div>

        <div className="form-group">
          <label>Döküman / Dosya Yolu (Input Path)</label>
          <input
            type="text"
            name="input_path"
            className="form-control"
            value={formData.input_path}
            onChange={handleChange}
            placeholder="/Users/.../SDR4Engineers.pdf"
          />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
          <div className="form-group">
            <label>Üretim Dili (Generation Language)</label>
            <select
              name="generation_language"
              className="form-control"
              value={formData.generation_language}
              onChange={handleChange}
            >
              <option value="en">English (İngilizce)</option>
              <option value="tr">Türkçe</option>
              <option value="bilingual">Bilingual (Çift Dilli)</option>
            </select>
          </div>

          <div className="form-group">
            <label>SFT Soru/Cevap Sayısı (sft_qa_count)</label>
            <input
              type="number"
              name="sft_qa_count"
              className="form-control"
              value={formData.sft_qa_count}
              onChange={handleChange}
              min={1}
              max={50}
            />
          </div>
        </div>

        <div className="form-group">
          <label>Hedef Uzmanlık Personası (LLM Persona)</label>
          <textarea
            name="llm_persona"
            className="form-control"
            value={formData.llm_persona}
            onChange={handleChange}
            rows={2}
          />
        </div>

        <div className="form-group">
          <label>Konu & Alan Tanımı (LLM Subject)</label>
          <textarea
            name="llm_subject"
            className="form-control"
            value={formData.llm_subject}
            onChange={handleChange}
            rows={2}
          />
        </div>

        <div style={{ display: 'flex', gap: '1rem', marginTop: '1.25rem' }}>
          <button className="btn btn-primary" onClick={handleSaveForm}>
            💾 Yapılandırmayı Kaydet
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => setIsEditingJson(!isEditingJson)}
          >
            {isEditingJson ? '📝 Forma Dön' : '🔍 Raw config.json Düzenle'}
          </button>
          {saveSuccess && <span style={{ color: '#34d399', alignSelf: 'center', fontSize: '0.85rem' }}>✓ Kaydedildi!</span>}
        </div>

        {isEditingJson && (
          <div style={{ marginTop: '1rem' }}>
            <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Canlı config.json Editörü</label>
            <textarea
              className="form-control mono"
              value={jsonText}
              onChange={(e) => setJsonText(e.target.value)}
              rows={12}
            />
            <button className="btn btn-emerald" style={{ marginTop: '0.5rem' }} onClick={handleSaveJson}>
              JSON Olarak Kaydet
            </button>
          </div>
        )}
      </div>

      {/* Sağ Kart: Pipeline Tetikleme & Canlı Terminal */}
      <div className="card">
        <div className="card-title" style={{ justifyContent: 'space-between' }}>
          <span>🚀 2. Pipeline Çalıştırma & Canlı Terminal</span>
          <span className={`badge ${isRunning ? 'online' : 'offline'}`}>
            {isRunning ? '▶ Çalışıyor...' : '⏸ Beklemede'}
          </span>
        </div>

        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', marginBottom: '1rem' }}>
          <div style={{ flex: 1 }}>
            <label style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>Limit (Örn: 5, 10:20, all)</label>
            <input
              type="text"
              className="form-control"
              value={limitInput}
              onChange={(e) => setLimitInput(e.target.value)}
              placeholder="5"
            />
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '1rem' }}>
            <input
              type="checkbox"
              id="resetCheck"
              checked={resetInput}
              onChange={(e) => setResetInput(e.target.checked)}
            />
            <label htmlFor="resetCheck" style={{ fontSize: '0.8rem', cursor: 'pointer' }}>
              Veritabanını Sıfırla (--reset)
            </label>
          </div>
        </div>

        {/* Action Buttons */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.6rem', marginBottom: '1.25rem' }}>
          <button
            className={`btn btn-emerald ${isRunning ? 'btn-disabled' : ''}`}
            disabled={isRunning}
            onClick={() => handleTrigger('pipeline', limitInput)}
          >
            ⚡ Hızlı Test Çalıştır (Limit: {limitInput})
          </button>

          <button
            className={`btn btn-primary ${isRunning ? 'btn-disabled' : ''}`}
            disabled={isRunning}
            onClick={() => handleTrigger('pipeline', 'all')}
          >
            🔥 Tüm Dökümanı İşle (Full Pipeline)
          </button>
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', marginBottom: '1rem' }}>
          <button
            className="btn btn-secondary"
            style={{ fontSize: '0.75rem', padding: '0.35rem 0.75rem' }}
            disabled={isRunning}
            onClick={() => onRunPipeline('extract', limitInput)}
          >
            1. Extract
          </button>
          <button
            className="btn btn-secondary"
            style={{ fontSize: '0.75rem', padding: '0.35rem 0.75rem' }}
            disabled={isRunning}
            onClick={() => onRunPipeline('enrich', limitInput)}
          >
            2. Enrich
          </button>
          <button
            className="btn btn-secondary"
            style={{ fontSize: '0.75rem', padding: '0.35rem 0.75rem' }}
            disabled={isRunning}
            onClick={() => onRunPipeline('embed', limitInput)}
          >
            3. Embed
          </button>

          <button
            className="btn btn-secondary"
            style={{ fontSize: '0.75rem', padding: '0.35rem 0.75rem' }}
            disabled={isRunning}
            onClick={() => onRunPipeline('export')}
          >
            4. Export JSONL
          </button>
        </div>

        {/* Live Terminal */}
        <div style={{ marginBottom: '0.5rem', display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>Konsol Çıktısı (PYTHONUNBUFFERED)</span>
          {pipelineState.command && (
            <span style={{ fontSize: '0.75rem', color: 'var(--accent-cyan)' }}>
              Komut: python run.py {pipelineState.command}
            </span>
          )}
        </div>

        <div className="terminal" ref={terminalRef}>
          {pipelineState.logs.length === 0 ? (
            <div style={{ color: '#64748b' }}>Henüz bir pipeline görevi başlatılmadı.</div>
          ) : (
            pipelineState.logs.map((log, index) => (
              <div key={index} className="terminal-line">
                {log}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};
