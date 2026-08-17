import { useState, useEffect, useRef } from 'react';
import type { PipelineConfig, PipelineState } from '../types';
import { ResetConfirmModal } from './ResetConfirmModal';

interface SectionConfigProps {
  config: PipelineConfig;
  onUpdateConfig: (newConfig: Partial<PipelineConfig>) => Promise<void>;
  pipelineState: PipelineState;
  onRunPipeline: (command: string, limit?: string, reset?: boolean, confirmReset?: boolean, shards?: number, shardPorts?: string) => void;
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

  // Sharding States
  const [shardingEnabled, setShardingEnabled] = useState<boolean>(false);
  const [shardsCount, setShardsCount] = useState<number>(2);
  const [shardPorts, setShardPorts] = useState<string>('11434,11435');
  const [isProbing, setIsProbing] = useState<boolean>(false);

  const terminalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setFormData(config);
    setJsonText(JSON.stringify(config, null, 2));
  }, [config]);

  // Auto-scroll terminal log widget to bottom when logs update (only if user is already near bottom)
  useEffect(() => {
    if (terminalRef.current) {
      const container = terminalRef.current;
      const isNearBottom = container.scrollHeight - container.clientHeight - container.scrollTop < 80;
      if (isNearBottom) {
        container.scrollTop = container.scrollHeight;
      }
    }
  }, [pipelineState.logs]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
    const { name, value, type } = e.target;
    let val: any = value;
    if (type === 'number') {
      val = Number(value);
    } else if (type === 'checkbox') {
      val = (e.target as HTMLInputElement).checked;
    }
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

  const handleProbePorts = async () => {
    setIsProbing(true);
    try {
      const res = await fetch('/api/system/probe-ports');
      if (res.ok) {
        const data = await res.json();
        if (data.active_ports && data.active_ports.length > 0) {
          const portsStr = data.active_ports.join(',');
          setShardPorts(portsStr);
          setShardsCount(data.active_ports.length);
          setShardingEnabled(true);
          alert(`Aktif Ollama portları keşfedildi: ${portsStr}. Sharding aktif edildi!`);
        } else {
          alert('Herhangi bir aktif ardışık Ollama portu (11434-11438) otomatik bulunamadı.');
        }
      }
    } catch (e) {
      console.error('Probe ports error:', e);
      alert('Port tarama sırasında bir ağ hatası oluştu.');
    } finally {
      setIsProbing(false);
    }
  };

  const handleTrigger = (cmd: string, limit?: string) => {
    if (resetInput) {
      setPendingCommand({ cmd, limit });
      setShowResetModal(true);
    } else {
      onRunPipeline(
        cmd,
        limit,
        false,
        false,
        shardingEnabled ? shardsCount : 1,
        shardingEnabled ? shardPorts : undefined
      );
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
          onRunPipeline(
            pendingCommand.cmd,
            pendingCommand.limit,
            true,
            true,
            shardingEnabled ? shardsCount : 1,
            shardingEnabled ? shardPorts : undefined
          );
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
            <option value="book">Book Mode (Tek veya Çoklu PDF Kitap Bölümleme)</option>
            <option value="folder">Folder Mode (Özyinelemeli Klasör + Akıllı Çoklu Kitap Bölümleme)</option>
            <option value="rendergit">Rendergit Mode (Git Kod Reposu / GitHub URL)</option>
          </select>
        </div>

        <div className="form-group">
          <label>{formData.input_mode === 'rendergit' ? 'Repo Adresi / Git URL veya Dizin (Input Path)' : 'Döküman / Klasör / Çoklu Dosya Yolu (Input Path)'}</label>
          <input
            type="text"
            name="input_path"
            className="form-control"
            value={formData.input_path}
            onChange={handleChange}
            placeholder={formData.input_mode === 'rendergit' ? 'https://github.com/karpathy/rendergit veya /path/to/repo' : '/Users/.../cilt1.pdf, /Users/.../cilt2.pdf veya Klasör Yolu'}
          />
          <span style={{ fontSize: '0.75rem', color: '#94a3b8', marginTop: '0.25rem', display: 'block' }}>
            💡 {formData.input_mode === 'rendergit' ? <strong>Rendergit Modu:</strong> : <strong>Klasör Modu:</strong>} Klasördeki/Repodaki kodlar AST ve rendergit formatıyla otomatik veri setine dönüştürülür.
          </span>
        </div>

        {/* Pragmatik vs Pedagojik Kayan Ayar Çubuğu (Slider) */}
        <div className="form-group" style={{ backgroundColor: 'rgba(255,255,255,0.03)', padding: '0.75rem', borderRadius: '0.5rem', border: '1px solid rgba(255,255,255,0.08)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
            <label style={{ margin: 0, fontWeight: 600 }}>⚡ Veri Seti Dağılım Modu (Pragmatik vs. Pedagojik)</label>
            <span style={{ fontSize: '0.85rem', fontWeight: 'bold', color: '#6366f1' }}>
              %{formData.pragmatic_ratio ?? 50} Pragmatik / %{100 - (formData.pragmatic_ratio ?? 50)} Pedagojik
            </span>
          </div>
          <input
            type="range"
            name="pragmatic_ratio"
            min="0"
            max="100"
            step="5"
            style={{ width: '100%', cursor: 'pointer', accentColor: '#6366f1' }}
            value={formData.pragmatic_ratio ?? 50}
            onChange={handleChange}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#94a3b8', marginTop: '0.25rem' }}>
            <span>🎓 %100 Pedagojik (Derin Teori)</span>
            <span>⚖️ %50 / %50 Dengeli</span>
            <span>⚡ %100 Pragmatik (Doğrudan Kod)</span>
          </div>
        </div>

        {/* 🎯 Veri Seti Kalite & Üretim Tercihleri (Çevirisiz Türkçe, DPO Doğrulama, Multi-turn) */}
        <div className="form-group" style={{ backgroundColor: 'rgba(99, 102, 241, 0.05)', padding: '0.75rem 1rem', borderRadius: '0.5rem', border: '1px solid rgba(99, 102, 241, 0.2)', marginBottom: '1rem' }}>
          <label style={{ margin: 0, fontWeight: 600, color: '#818cf8', marginBottom: '0.5rem', display: 'block' }}>
            🎯 Veri Seti Kalite & Üretim Tercihleri
          </label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.55rem' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.82rem', cursor: 'pointer', color: 'var(--text-primary)' }}>
              <input
                type="checkbox"
                name="direct_tr_generation"
                checked={formData.direct_tr_generation ?? true}
                onChange={handleChange}
              />
              <span><strong>Doğrudan Türkçe Üretim:</strong> Çeviri aşaması olmadan dökümandan doğrudan Türkçe SFT/DPO/Chat üretir. (Deaktif edilirse EN-TR çeviri çalışır)</span>
            </label>

            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.82rem', cursor: 'pointer', color: 'var(--text-primary)' }}>
              <input
                type="checkbox"
                name="enable_dpo_verification"
                checked={formData.enable_dpo_verification ?? true}
                onChange={handleChange}
              />
              <span><strong>DPO Teknik Doğrulama Katmanı:</strong> Chosen/Rejected çiftlerini mühendislik doğruluğu ve mantık hatası kalitesine göre filtreler.</span>
            </label>

            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.82rem', cursor: 'pointer', color: 'var(--text-primary)' }}>
              <input
                type="checkbox"
                name="generate_multi_turn_chat"
                checked={formData.generate_multi_turn_chat ?? true}
                onChange={handleChange}
              />
              <span><strong>Çok Turlu (Multi-turn) Diyalog Sentezi:</strong> Adım adım donanım/yazılım sorun giderme ve yönlendirme sohbetleri üretir.</span>
            </label>

            {/* Faz 2 Sentetik Kod Çeşitliliği Kontrol Kutusarı */}
            <div style={{ marginTop: '0.5rem', paddingTop: '0.5rem', borderTop: '1px solid rgba(255,255,255,0.08)', fontSize: '0.78rem', color: '#cbd5e1' }}>
              <strong style={{ color: '#38bdf8', display: 'block', marginBottom: '0.4rem' }}>💻 Faz 2 Sentetik Kod Çeşitliliği Kategorileri (Aktif/Deaktif Et):</strong>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.4rem' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.78rem', cursor: 'pointer', backgroundColor: 'rgba(56, 189, 248, 0.08)', padding: '0.35rem 0.5rem', borderRadius: '0.35rem', border: '1px solid rgba(56, 189, 248, 0.2)' }}>
                  <input
                    type="checkbox"
                    name="code_cat_explanation"
                    checked={formData.code_cat_explanation ?? true}
                    onChange={handleChange}
                  />
                  <span style={{ color: '#38bdf8' }}>📝 Kod Açıklama & Mimari</span>
                </label>

                <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.78rem', cursor: 'pointer', backgroundColor: 'rgba(52, 211, 153, 0.08)', padding: '0.35rem 0.5rem', borderRadius: '0.35rem', border: '1px solid rgba(52, 211, 153, 0.2)' }}>
                  <input
                    type="checkbox"
                    name="code_cat_completion"
                    checked={formData.code_cat_completion ?? true}
                    onChange={handleChange}
                  />
                  <span style={{ color: '#34d399' }}>💻 Kod Tamamlama (İmza → Kod)</span>
                </label>

                <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.78rem', cursor: 'pointer', backgroundColor: 'rgba(251, 113, 133, 0.08)', padding: '0.35rem 0.5rem', borderRadius: '0.35rem', border: '1px solid rgba(251, 113, 133, 0.2)' }}>
                  <input
                    type="checkbox"
                    name="code_cat_bug_fix"
                    checked={formData.code_cat_bug_fix ?? true}
                    onChange={handleChange}
                  />
                  <span style={{ color: '#fb7185' }}>🐛 Hata Ayıklama & Güvenlik</span>
                </label>

                <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.78rem', cursor: 'pointer', backgroundColor: 'rgba(251, 191, 36, 0.08)', padding: '0.35rem 0.5rem', borderRadius: '0.35rem', border: '1px solid rgba(251, 191, 36, 0.2)' }}>
                  <input
                    type="checkbox"
                    name="code_cat_unit_test"
                    checked={formData.code_cat_unit_test ?? true}
                    onChange={handleChange}
                  />
                  <span style={{ color: '#fbbf24' }}>🧪 pytest Birim Test Üretimi</span>
                </label>
              </div>
            </div>
          </div>
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
            />
          </div>
        </div>

        <div className="form-group">
          <label>Öğretmen Model (Teacher Analyzer)</label>
          <input
            type="text"
            name="model_analyzer"
            className="form-control"
            value={formData.model_analyzer}
            onChange={handleChange}
          />
        </div>

        <div className="form-group">
          <label>Çeviri Modeli (Bilingual Translator)</label>
          <input
            type="text"
            name="model_translator"
            className="form-control"
            value={formData.model_translator}
            onChange={handleChange}
          />
        </div>

        <div className="form-group">
          <label>Vektör Embedding Modeli</label>
          <input
            type="text"
            name="model_embedding"
            className="form-control"
            value={formData.model_embedding}
            onChange={handleChange}
          />
        </div>

        {/* Google LangExtract Configuration Card */}
        <div style={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '0.5rem', padding: '1rem', marginTop: '1.2rem', marginBottom: '1.2rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.8rem' }}>
            <h4 style={{ margin: 0, fontSize: '0.95rem', color: '#60a5fa', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              🔍 Google LangExtract Entegrasyonu (Grounded Extraction)
            </h4>
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.8rem', cursor: 'pointer' }}>
              <input
                type="checkbox"
                name="enable_langextract"
                checked={formData.enable_langextract ?? true}
                onChange={handleChange}
              />
              <span style={{ color: '#e2e8f0', fontWeight: 'bold' }}>LangExtract Aktif</span>
            </label>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.8rem' }}>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label style={{ fontSize: '0.78rem' }}>Sağlayıcı (Provider Priority: Ollama ➔ OpenAI ➔ Gemini)</label>
              <select
                name="langextract_provider"
                className="form-control"
                style={{ fontSize: '0.82rem' }}
                value={formData.langextract_provider || 'ollama'}
                onChange={handleChange}
              >
                <option value="ollama">1. Ollama (Yerel Ücretsiz)</option>
                <option value="openai">2. OpenAI (API)</option>
                <option value="gemini">3. Gemini API (Google)</option>
              </select>
            </div>

            <div className="form-group" style={{ marginBottom: 0 }}>
              <label style={{ fontSize: '0.78rem' }}>Şema Şablonu (Preset Schema)</label>
              <select
                name="langextract_schema_preset"
                className="form-control"
                style={{ fontSize: '0.82rem' }}
                value={formData.langextract_schema_preset || 'technical_components'}
                onChange={handleChange}
              >
                <option value="technical_components">Hardware & Technical Components</option>
                <option value="circuit_specifications">Circuit & Electrical Specs</option>
                <option value="software_units">Software Architecture & AST</option>
                <option value="pinout_mappings">Pinout & Signal Mappings</option>
                <option value="generic_technical_qa">Generic Technical Q&A</option>
              </select>
            </div>

            <div className="form-group" style={{ marginBottom: 0 }}>
              <label style={{ fontSize: '0.78rem' }}>Gemini API Key (Opsiyonel)</label>
              <input
                type="password"
                name="gemini_api_key"
                className="form-control"
                style={{ fontSize: '0.82rem' }}
                placeholder="AIzaSy..."
                value={formData.gemini_api_key || ''}
                onChange={handleChange}
              />
            </div>
          </div>
        </div>

        {/* JSON / Form Görünüm Anahtarı */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '1.5rem' }}>
          <button
            className="btn btn-secondary"
            onClick={() => setIsEditingJson(!isEditingJson)}
            style={{ fontSize: '0.8rem' }}
          >
            {isEditingJson ? '📝 Form Görünümüne Dön' : '⚙️ config.json Doğrudan Düzenle'}
          </button>

          <button className="btn btn-primary" onClick={isEditingJson ? handleSaveJson : handleSaveForm}>
            💾 Yapılandırmayı Kaydet
          </button>
        </div>

        {saveSuccess && (
          <div style={{ marginTop: '0.75rem', color: '#34d399', fontSize: '0.85rem' }}>
            ✓ config.json başarıyla güncellendi!
          </div>
        )}

        {isEditingJson && (
          <div style={{ marginTop: '1rem' }}>
            <textarea
              className="form-control"
              style={{ height: '220px', fontFamily: 'monospace', fontSize: '0.8rem' }}
              value={jsonText}
              onChange={(e) => setJsonText(e.target.value)}
            />
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

        {/* LİMİT VE RESET KONTROLLERİ */}
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', marginBottom: '1rem', background: 'var(--bg-primary)', padding: '0.75rem 1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}>
          <div style={{ flex: 1 }}>
            <label style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>Örnek Limiti (Limit: Örn. 5, 10:20, all)</label>
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
            <label htmlFor="resetCheck" style={{ fontSize: '0.8rem', cursor: 'pointer', color: resetInput ? '#fb7185' : 'var(--text-secondary)' }}>
              Veritabanını Sıfırla (--reset) ⚠️
            </label>
          </div>
        </div>

        {/* PARALEL SHARDING (SPLIT PROCESSING) KART */}
        <div style={{ marginBottom: '1rem', background: 'rgba(30, 41, 59, 0.5)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
            <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--accent-cyan)' }}>
              ⚡ Paralel Sharding (İş Bölerek İşleme)
            </span>
            <button
              className="btn btn-secondary"
              style={{ fontSize: '0.72rem', padding: '0.2rem 0.5rem' }}
              disabled={isProbing || isRunning}
              onClick={handleProbePorts}
            >
              {isProbing ? '🔍 Taranıyor...' : '🔄 Otomatik Port Tara'}
            </button>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
            <input
              type="checkbox"
              id="shardingEnabled"
              checked={shardingEnabled}
              onChange={(e) => setShardingEnabled(e.target.checked)}
              disabled={isRunning}
            />
            <label htmlFor="shardingEnabled" style={{ fontSize: '0.8rem', cursor: 'pointer', color: 'var(--text-primary)' }}>
              Paralel İşleme Modunu Aktif Et
            </label>
          </div>

          {shardingEnabled && (
            <>
              {/* VRAM UYARI KARTI */}
              <div style={{
                background: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                padding: '0.6rem 0.8rem',
                borderRadius: 'var(--radius-sm)',
                marginBottom: '0.75rem',
                fontSize: '0.75rem',
                color: '#f87171',
                lineHeight: '1.25'
              }}>
                ⚠️ <strong>VRAM Uyarısı:</strong> Eşzamanlı paralel işleme yaparken VRAM aşımı ve yavaşlama yaşamamak için <strong>9B parametre altındaki</strong> modelleri (örn: <code>ornith:9b</code> veya <code>translategemma:12b</code>) kullanmanız şiddetle tavsiye edilir.
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '0.75rem' }}>
                <div>
                  <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Parça (Shard) Sayısı</label>
                  <input
                    type="number"
                    min="1"
                    max="8"
                    className="form-control"
                    value={shardsCount}
                    onChange={(e) => setShardsCount(Math.max(1, Number(e.target.value)))}
                    disabled={isRunning}
                  />
                </div>
                <div>
                  <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Ollama Portları (Virgülle ayırın)</label>
                  <input
                    type="text"
                    className="form-control"
                    value={shardPorts}
                    onChange={(e) => setShardPorts(e.target.value)}
                    placeholder="11434,11435"
                    disabled={isRunning}
                  />
                </div>
              </div>
            </>
          )}
        </div>

        {/* BÖLÜM 1: TAM PIPELINE BUTONLARI */}
        <div style={{ marginBottom: '1.25rem' }}>
          <div style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>
            TAM PIPELINE ÇALIŞTIRMA (Tüm 4 Adım Ardışık İlerler)
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.6rem' }}>
            <button
              className={`btn btn-emerald ${isRunning ? 'btn-disabled' : ''}`}
              disabled={isRunning}
              onClick={() => handleTrigger('pipeline', limitInput)}
            >
              ⚡ Hızlı Test (Limit: {limitInput})
            </button>

            <button
              className={`btn btn-primary ${isRunning ? 'btn-disabled' : ''}`}
              disabled={isRunning}
              onClick={() => handleTrigger('pipeline', 'all')}
            >
              🔥 Tüm Dökümanı İşle (Full Pipeline)
            </button>
          </div>
        </div>

        {/* BÖLÜM 2: BAĞIMSIZ ADIM BUTONLARI (STEP-BY-STEP EXECUTION) */}
        <div style={{ marginBottom: '1.25rem', background: 'rgba(15, 23, 42, 0.4)', padding: '0.75rem', borderRadius: 'var(--radius-md)', border: '1px dashed var(--border-color)' }}>
          <div style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--accent-cyan)', marginBottom: '0.5rem' }}>
            🎯 TEKİL ADIM ÇALIŞTIR (Step-by-Step Execution)
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
            <button
              className={`btn btn-secondary ${isRunning ? 'btn-disabled' : ''}`}
              style={{ fontSize: '0.78rem', padding: '0.45rem 0.6rem', textAlign: 'left' }}
              disabled={isRunning}
              onClick={() => handleTrigger('extract', limitInput)}
              title="Sadece PDF metinlerini ve haritayı ayıklar"
            >
              📄 1. Metin Ayıkla (Extract)
            </button>

            <button
              className={`btn btn-secondary ${isRunning ? 'btn-disabled' : ''}`}
              style={{ fontSize: '0.78rem', padding: '0.45rem 0.6rem', textAlign: 'left' }}
              disabled={isRunning}
              onClick={() => handleTrigger('enrich', limitInput)}
              title="Qwen ve TranslateGemma ile SFT/DPO üretir"
            >
              🧠 2. AI Zenginleştir (Enrich)
            </button>

            <button
              className={`btn btn-secondary ${isRunning ? 'btn-disabled' : ''}`}
              style={{ fontSize: '0.78rem', padding: '0.45rem 0.6rem', textAlign: 'left' }}
              disabled={isRunning}
              onClick={() => handleTrigger('embed', limitInput)}
              title="Qdrant Vektör DB'ye gömer ve indeksler"
            >
              🔍 3. Vektörle (Embed)
            </button>

            <button
              className={`btn btn-secondary ${isRunning ? 'btn-disabled' : ''}`}
              style={{ fontSize: '0.78rem', padding: '0.45rem 0.6rem', textAlign: 'left' }}
              disabled={isRunning}
              onClick={() => handleTrigger('export')}
              title="SFT/DPO/Chat .jsonl veri setlerini exports/ klasörüne yazar"
            >
              📦 4. Veri Seti Aktar (Export)
            </button>
          </div>
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
