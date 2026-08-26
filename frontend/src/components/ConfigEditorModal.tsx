import React, { useState, useEffect } from 'react';
import type { PipelineConfig } from '../types';

interface ConfigEditorModalProps {
  isOpen: boolean;
  config: PipelineConfig;
  onClose: () => void;
  onSave: (newConfig: PipelineConfig) => Promise<void>;
}

type TabType = 'project' | 'models' | 'data' | 'code' | 'storage' | 'ocr' | 'langextract_kiwix' | 'raw_json';

export const ConfigEditorModal: React.FC<ConfigEditorModalProps> = ({
  isOpen,
  config,
  onClose,
  onSave,
}) => {
  const [activeTab, setActiveTab] = useState<TabType>('project');
  const [formData, setFormData] = useState<PipelineConfig>(config);
  const [rawJsonText, setRawJsonText] = useState<string>(JSON.stringify(config, null, 2));
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [saveSuccess, setSaveSuccess] = useState<boolean>(false);
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [copied, setCopied] = useState<boolean>(false);

  // Custom key/value pair adder state
  const [newKey, setNewKey] = useState<string>('');
  const [newValue, setNewValue] = useState<string>('');
  const [newValueType, setNewValueType] = useState<'string' | 'number' | 'boolean'>('string');

  useEffect(() => {
    if (isOpen) {
      setFormData(config);
      setRawJsonText(JSON.stringify(config, null, 2));
      setJsonError(null);
      setSaveSuccess(false);
      setSearchQuery('');
    }
  }, [isOpen, config]);

  if (!isOpen) return null;

  const handleFieldChange = (key: string, value: any) => {
    const updated = { ...formData, [key]: value };
    setFormData(updated);
    setRawJsonText(JSON.stringify(updated, null, 2));
  };

  const handleRawJsonChange = (text: string) => {
    setRawJsonText(text);
    try {
      const parsed = JSON.parse(text);
      setFormData(parsed);
      setJsonError(null);
    } catch (e: any) {
      setJsonError(e.message || 'Geçersiz JSON formatı');
    }
  };

  const handleAddCustomKey = () => {
    if (!newKey.trim()) return;
    const trimmedKey = newKey.trim();
    let val: any = newValue;
    if (newValueType === 'number') val = Number(newValue);
    if (newValueType === 'boolean') val = newValue === 'true';

    const updated = { ...formData, [trimmedKey]: val };
    setFormData(updated);
    setRawJsonText(JSON.stringify(updated, null, 2));
    setNewKey('');
    setNewValue('');
  };

  const handleRemoveCustomKey = (key: string) => {
    const updated = { ...formData };
    delete updated[key];
    setFormData(updated);
    setRawJsonText(JSON.stringify(updated, null, 2));
  };

  const handleSave = async () => {
    if (jsonError) {
      alert('Lütfen JSON biçim hatasını düzeltin: ' + jsonError);
      return;
    }
    setIsSaving(true);
    try {
      await onSave(formData);
      setSaveSuccess(true);
      setTimeout(() => {
        setSaveSuccess(false);
        onClose();
      }, 1200);
    } catch (err: any) {
      alert('Yapılandırma kaydedilirken hata oluştu: ' + (err.message || err));
    } finally {
      setIsSaving(false);
    }
  };

  const handleCopyJson = () => {
    navigator.clipboard.writeText(rawJsonText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const knownKeys = new Set([
    'project_id', 'project_name', 'dataset_name', 'dataset_name_tr', 'input_mode', 'input_path',
    'model_analyzer', 'model_translator', 'model_embedding', 'model_vision', 'ollama_url', 'openai_timeout',
    'analyzer_max_chars', 'analyzer_max_tokens', 'llm_persona', 'llm_subject', 'generation_language',
    'translation_target', 'sft_qa_count', 'pragmatic_ratio', 'direct_tr_generation', 'enable_dpo_verification',
    'generate_multi_turn_chat', 'code_cat_explanation', 'code_cat_completion', 'code_cat_bug_fix', 'code_cat_unit_test',
    'db_path', 'qdrant_db_path', 'qdrant_collection_name', 'chunk_size', 'chunk_overlap', 'ocr_threshold_chars',
    'tesseract_cmd', 'enable_vision_ocr', 'enable_langextract', 'enable_langextract_dynamic_examples',
    'langextract_provider', 'langextract_schema_preset', 'langextract_model_id', 'gemini_api_key', 'openai_api_key',
    'kiwix_zim_path', 'kiwix_download_url', 'kiwix_namespaces', 'kiwix_min_chars',
    'kiwix_extract_mode', 'kiwix_min_chosen_score', 'kiwix_min_vote_diff', 'kiwix_batch_size'
  ]);

  const customKeys = Object.keys(formData).filter((k) => !knownKeys.has(k));

  const filterMatches = (text: string) => {
    if (!searchQuery.trim()) return true;
    return text.toLowerCase().includes(searchQuery.toLowerCase());
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.82)',
        backdropFilter: 'blur(8px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1200,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          backgroundColor: '#0d1322',
          border: '1px solid #2d3748',
          borderRadius: '0.85rem',
          width: '95%',
          maxWidth: '1050px',
          height: '92vh',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 25px 60px -15px rgba(0, 0, 0, 0.8)',
          overflow: 'hidden',
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '1.2rem 1.5rem',
            borderBottom: '1px solid #1f293d',
            backgroundColor: '#111827',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <div
              style={{
                width: '38px',
                height: '38px',
                borderRadius: '8px',
                background: 'linear-gradient(135deg, #3b82f6, #06b6d4)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '1.25rem',
              }}
            >
              ⚙️
            </div>
            <div>
              <h2 style={{ margin: 0, fontSize: '1.15rem', color: '#f3f4f6', fontWeight: 700 }}>
                config.json Yapılandırma & Parametre Merkezi
              </h2>
              <span style={{ fontSize: '0.75rem', color: '#9ca3af' }}>
                Pipeline ayarları, model yapılandırmaları ve sentez parametrelerini doğrudan düzenleyin
              </span>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            {/* Search Box */}
            <div style={{ position: 'relative', width: '220px' }}>
              <input
                type="text"
                className="form-control"
                placeholder="🔍 Ayar ara..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{
                  fontSize: '0.78rem',
                  padding: '0.35rem 0.65rem 0.35rem 1.8rem',
                  backgroundColor: '#1f293d',
                  borderRadius: '20px',
                  border: '1px solid #374151',
                }}
              />
              <span style={{ position: 'absolute', left: '0.6rem', top: '0.4rem', fontSize: '0.75rem', color: '#9ca3af' }}>
                🔍
              </span>
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  style={{
                    position: 'absolute',
                    right: '0.5rem',
                    top: '0.35rem',
                    background: 'none',
                    border: 'none',
                    color: '#9ca3af',
                    fontSize: '0.8rem',
                    cursor: 'pointer',
                  }}
                >
                  ✕
                </button>
              )}
            </div>

            <button
              onClick={onClose}
              style={{
                background: 'rgba(255,255,255,0.05)',
                border: '1px solid #374151',
                color: '#9ca3af',
                borderRadius: '50%',
                width: '32px',
                height: '32px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '1.2rem',
                cursor: 'pointer',
              }}
            >
              ×
            </button>
          </div>
        </div>

        {/* Tab Navigation */}
        <div
          style={{
            display: 'flex',
            overflowX: 'auto',
            gap: '0.35rem',
            padding: '0.6rem 1.5rem',
            backgroundColor: '#0f172a',
            borderBottom: '1px solid #1e293b',
          }}
        >
          {[
            { id: 'project', label: '📁 Proje & Girdi' },
            { id: 'models', label: '🤖 Model & LLM' },
            { id: 'data', label: '🎯 Sentetik Veri' },
            { id: 'code', label: '💻 Kod Çeşitliliği' },
            { id: 'storage', label: '🗄️ Veritabanı & RAG' },
            { id: 'ocr', label: '👁️ OCR & Vizyon' },
            { id: 'langextract_kiwix', label: '🔍 LangExtract & Kiwix' },
            { id: 'raw_json', label: '📝 Ham JSON & Özel Alanlar' },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as TabType)}
              style={{
                padding: '0.45rem 0.85rem',
                borderRadius: '6px',
                fontSize: '0.8rem',
                fontWeight: 600,
                whiteSpace: 'nowrap',
                backgroundColor: activeTab === tab.id ? 'rgba(59, 130, 246, 0.18)' : 'transparent',
                border: `1px solid ${activeTab === tab.id ? '#3b82f6' : 'transparent'}`,
                color: activeTab === tab.id ? '#60a5fa' : '#94a3b8',
                transition: 'all 0.15s ease',
                cursor: 'pointer',
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Content Area */}
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: '1.5rem',
            backgroundColor: '#0b0f19',
          }}
        >
          {/* TAB 1: PROJE & GİRDİ */}
          {activeTab === 'project' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.2rem' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                {filterMatches('project_id Proje Kimliği') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                      Proje Kimliği (<code>project_id</code>)
                    </label>
                    <input
                      type="text"
                      className="form-control"
                      value={formData.project_id || ''}
                      onChange={(e) => handleFieldChange('project_id', e.target.value)}
                      placeholder="extract"
                    />
                    <span style={{ fontSize: '0.72rem', color: '#94a3b8' }}>
                      Benzersiz proje anahtarı (database/&lt;project_id&gt;.db için kullanılır)
                    </span>
                  </div>
                )}

                {filterMatches('dataset_name Veri Seti Adı') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                      Veri Seti Adı (<code>dataset_name</code>)
                    </label>
                    <input
                      type="text"
                      className="form-control"
                      value={formData.dataset_name || ''}
                      onChange={(e) => handleFieldChange('dataset_name', e.target.value)}
                      placeholder="sdr_engineers"
                    />
                    <span style={{ fontSize: '0.72rem', color: '#94a3b8' }}>
                      Global veri seti ve export ismi
                    </span>
                  </div>
                )}
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                {filterMatches('dataset_name_tr Türkçe Veri Seti Adı') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                      Türkçe Veri Seti Adı (<code>dataset_name_tr</code>)
                    </label>
                    <input
                      type="text"
                      className="form-control"
                      value={formData.dataset_name_tr || ''}
                      onChange={(e) => handleFieldChange('dataset_name_tr', e.target.value)}
                      placeholder="sdr_muhendisleri"
                    />
                  </div>
                )}

                {filterMatches('input_mode İşleme Modu') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                      İşleme Modu (<code>input_mode</code>)
                    </label>
                    <select
                      className="form-control"
                      value={formData.input_mode || 'folder'}
                      onChange={(e) => handleFieldChange('input_mode', e.target.value)}
                    >
                      <option value="folder">folder (Özyinelemeli Klasör + Çoklu Kitap)</option>
                      <option value="book">book (Tek veya Çoklu PDF Kitap)</option>
                      <option value="rendergit">rendergit (Git Reposu / Kaynak Kod)</option>
                      <option value="kiwix">kiwix / zim (OpenZIM Arşiv Çıkarıcı)</option>
                    </select>
                  </div>
                )}
              </div>

              {filterMatches('input_path Girdi Dosya Yolu') && (
                <div className="form-group">
                  <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                    Girdi Dosya / Dizin Yolu (<code>input_path</code>)
                  </label>
                  <input
                    type="text"
                    className="form-control"
                    value={formData.input_path || ''}
                    onChange={(e) => handleFieldChange('input_path', e.target.value)}
                    placeholder="/Users/.../cilt1.pdf veya https://github.com/..."
                  />
                  <span style={{ fontSize: '0.72rem', color: '#94a3b8' }}>
                    İşlenecek PDF dosya(lar)ı, klasör dizini veya Git repo bağlantısı
                  </span>
                </div>
              )}
            </div>
          )}

          {/* TAB 2: MODEL & LLM */}
          {activeTab === 'models' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.2rem' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                {filterMatches('model_analyzer Öğretmen Analiz Modeli') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                      Öğretmen Model (<code>model_analyzer</code>)
                    </label>
                    <input
                      type="text"
                      className="form-control"
                      value={formData.model_analyzer || ''}
                      onChange={(e) => handleFieldChange('model_analyzer', e.target.value)}
                      placeholder="qwen3.5:4b"
                    />
                    <span style={{ fontSize: '0.72rem', color: '#94a3b8' }}>
                      SFT/DPO çıkarımı ve analiz yapan ana LLM
                    </span>
                  </div>
                )}

                {filterMatches('model_translator Çeviri Modeli') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                      Çeviri Modeli (<code>model_translator</code>)
                    </label>
                    <input
                      type="text"
                      className="form-control"
                      value={formData.model_translator || ''}
                      onChange={(e) => handleFieldChange('model_translator', e.target.value)}
                      placeholder="qwen3.5:4b"
                    />
                    <span style={{ fontSize: '0.72rem', color: '#94a3b8' }}>
                      İki dilli (Bilingual) çevirilerde kullanılan model
                    </span>
                  </div>
                )}
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                {filterMatches('model_embedding Vektör Embedding Modeli') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                      Vektör Embedding Modeli (<code>model_embedding</code>)
                    </label>
                    <input
                      type="text"
                      className="form-control"
                      value={formData.model_embedding || ''}
                      onChange={(e) => handleFieldChange('model_embedding', e.target.value)}
                      placeholder="nomic-embed-text:latest"
                    />
                    <span style={{ fontSize: '0.72rem', color: '#94a3b8' }}>
                      Qdrant vektör indeksleme için metin gömme modeli
                    </span>
                  </div>
                )}

                {filterMatches('model_vision Görsel OCR Modeli') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                      Görsel Vision Modeli (<code>model_vision</code>)
                    </label>
                    <input
                      type="text"
                      className="form-control"
                      value={formData.model_vision || ''}
                      onChange={(e) => handleFieldChange('model_vision', e.target.value)}
                      placeholder="qwen3.5:4b"
                    />
                    <span style={{ fontSize: '0.72rem', color: '#94a3b8' }}>
                      Şema ve grafik görsel analizi için vision modeli
                    </span>
                  </div>
                )}
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '1rem' }}>
                {filterMatches('ollama_url Ollama Sunucu Adresi') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                      Ollama Sunucu URL (<code>ollama_url</code>)
                    </label>
                    <input
                      type="text"
                      className="form-control"
                      value={formData.ollama_url || ''}
                      onChange={(e) => handleFieldChange('ollama_url', e.target.value)}
                      placeholder="http://127.0.0.1:11434"
                    />
                  </div>
                )}

                {filterMatches('openai_timeout API Zaman Aşımı') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                      API Timeout Saniye (<code>openai_timeout</code>)
                    </label>
                    <input
                      type="number"
                      className="form-control"
                      value={formData.openai_timeout ?? 600}
                      onChange={(e) => handleFieldChange('openai_timeout', Number(e.target.value))}
                    />
                  </div>
                )}

                {filterMatches('analyzer_max_chars Maksimum Karakter') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                      Analiz Karakter Limiti (<code>analyzer_max_chars</code>)
                    </label>
                    <input
                      type="number"
                      className="form-control"
                      value={formData.analyzer_max_chars ?? 4000}
                      onChange={(e) => handleFieldChange('analyzer_max_chars', Number(e.target.value))}
                    />
                  </div>
                )}
              </div>

              {filterMatches('analyzer_max_tokens Maksimum Token') && (
                <div className="form-group">
                  <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                    Analiz Token Limiti (<code>analyzer_max_tokens</code>)
                  </label>
                  <input
                    type="number"
                    className="form-control"
                    value={formData.analyzer_max_tokens ?? 8192}
                    onChange={(e) => handleFieldChange('analyzer_max_tokens', Number(e.target.value))}
                  />
                  <span style={{ fontSize: '0.72rem', color: '#94a3b8' }}>
                    Model çıkarımında izin verilen maksimum token penceresi
                  </span>
                </div>
              )}
            </div>
          )}

          {/* TAB 3: SENTETİK VERİ & PERSONA */}
          {activeTab === 'data' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.2rem' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                {filterMatches('llm_persona Uzmanlık Personası') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                      Hedef Uzmanlık Personası (<code>llm_persona</code>)
                    </label>
                    <input
                      type="text"
                      className="form-control"
                      value={formData.llm_persona || ''}
                      onChange={(e) => handleFieldChange('llm_persona', e.target.value)}
                      placeholder="Professional Systems Engineer"
                    />
                  </div>
                )}

                {filterMatches('llm_subject Konu Alan Tanımı') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                      Konu & Alan Tanımı (<code>llm_subject</code>)
                    </label>
                    <input
                      type="text"
                      className="form-control"
                      value={formData.llm_subject || ''}
                      onChange={(e) => handleFieldChange('llm_subject', e.target.value)}
                      placeholder="Technical Documentation & Architecture"
                    />
                  </div>
                )}
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '1rem' }}>
                {filterMatches('generation_language Üretim Dili') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                      Üretim Dili (<code>generation_language</code>)
                    </label>
                    <select
                      className="form-control"
                      value={formData.generation_language || 'bilingual'}
                      onChange={(e) => handleFieldChange('generation_language', e.target.value)}
                    >
                      <option value="bilingual">bilingual (Çift Dilli)</option>
                      <option value="tr">tr (Türkçe)</option>
                      <option value="en">en (İngilizce)</option>
                    </select>
                  </div>
                )}

                {filterMatches('translation_target Hedef Çeviri') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                      Hedef Dil (<code>translation_target</code>)
                    </label>
                    <input
                      type="text"
                      className="form-control"
                      value={formData.translation_target || 'tr'}
                      onChange={(e) => handleFieldChange('translation_target', e.target.value)}
                      placeholder="tr"
                    />
                  </div>
                )}

                {filterMatches('sft_qa_count Soru Cevap Sayısı') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                      SFT Q&A Sayısı (<code>sft_qa_count</code>)
                    </label>
                    <input
                      type="number"
                      className="form-control"
                      value={formData.sft_qa_count ?? 10}
                      onChange={(e) => handleFieldChange('sft_qa_count', Number(e.target.value))}
                    />
                  </div>
                )}
              </div>

              {filterMatches('pragmatic_ratio Pragmatik Pedagojik Dağılım') && (
                <div style={{ backgroundColor: 'rgba(255,255,255,0.03)', padding: '1rem', borderRadius: '0.5rem', border: '1px solid rgba(255,255,255,0.08)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                    <label style={{ margin: 0, fontWeight: 600, fontSize: '0.82rem' }}>
                      ⚡ Veri Seti Dağılım Modu (<code>pragmatic_ratio</code>: %{formData.pragmatic_ratio ?? 50})
                    </label>
                    <span style={{ fontSize: '0.85rem', fontWeight: 'bold', color: '#818cf8' }}>
                      %{formData.pragmatic_ratio ?? 50} Pragmatik / %{100 - (formData.pragmatic_ratio ?? 50)} Pedagojik
                    </span>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    step="5"
                    style={{ width: '100%', cursor: 'pointer', accentColor: '#6366f1' }}
                    value={formData.pragmatic_ratio ?? 50}
                    onChange={(e) => handleFieldChange('pragmatic_ratio', Number(e.target.value))}
                  />
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: '#94a3b8', marginTop: '0.35rem' }}>
                    <span>🎓 %100 Pedagojik (Derin Teori)</span>
                    <span>⚖️ %50 / %50 Dengeli</span>
                    <span>⚡ %100 Pragmatik (Doğrudan Kod)</span>
                  </div>
                </div>
              )}

              {/* Kalite & Üretim Anahtarları */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '0.75rem' }}>
                {filterMatches('direct_tr_generation Doğrudan Türkçe') && (
                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', padding: '0.6rem 0.8rem', backgroundColor: '#1e293b', borderRadius: '6px', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={formData.direct_tr_generation ?? true}
                      onChange={(e) => handleFieldChange('direct_tr_generation', e.target.checked)}
                    />
                    <span style={{ fontSize: '0.82rem' }}>
                      <strong>Doğrudan Türkçe Üretim (<code>direct_tr_generation</code>):</strong> Çeviri aşaması olmadan doğrudan Türkçe veri üretir.
                    </span>
                  </label>
                )}

                {filterMatches('enable_dpo_verification DPO Doğrulama') && (
                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', padding: '0.6rem 0.8rem', backgroundColor: '#1e293b', borderRadius: '6px', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={formData.enable_dpo_verification ?? true}
                      onChange={(e) => handleFieldChange('enable_dpo_verification', e.target.checked)}
                    />
                    <span style={{ fontSize: '0.82rem' }}>
                      <strong>DPO Teknik Doğrulama (<code>enable_dpo_verification</code>):</strong> Chosen/Rejected çiftlerini mühendislik doğruluğuna göre filtreler.
                    </span>
                  </label>
                )}

                {filterMatches('generate_multi_turn_chat Çok Turlu Sohbet') && (
                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', padding: '0.6rem 0.8rem', backgroundColor: '#1e293b', borderRadius: '6px', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={formData.generate_multi_turn_chat ?? true}
                      onChange={(e) => handleFieldChange('generate_multi_turn_chat', e.target.checked)}
                    />
                    <span style={{ fontSize: '0.82rem' }}>
                      <strong>Çok Turlu Diyalog Sentezi (<code>generate_multi_turn_chat</code>):</strong> Adım adım donanım/yazılım sorun giderme diyalogları üretir.
                    </span>
                  </label>
                )}
              </div>
            </div>
          )}

          {/* TAB 4: KOD ÇEŞİTLİLİĞİ */}
          {activeTab === 'code' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div style={{ fontSize: '0.82rem', color: '#94a3b8', marginBottom: '0.5rem' }}>
                Faz 2 Sentetik Kod Çeşitliliği Kategorileri: AST tabanlı kod analizi ve sentetik kod veri seti jeneratörü tercihleri.
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.85rem' }}>
                {filterMatches('code_cat_explanation Kod Açıklama Mimari') && (
                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', padding: '0.75rem', backgroundColor: 'rgba(56, 189, 248, 0.08)', border: '1px solid rgba(56, 189, 248, 0.25)', borderRadius: '8px', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={formData.code_cat_explanation ?? true}
                      onChange={(e) => handleFieldChange('code_cat_explanation', e.target.checked)}
                    />
                    <div>
                      <strong style={{ fontSize: '0.82rem', color: '#38bdf8', display: 'block' }}>📝 Kod Açıklama & Mimari</strong>
                      <span style={{ fontSize: '0.72rem', color: '#94a3b8' }}><code>code_cat_explanation</code></span>
                    </div>
                  </label>
                )}

                {filterMatches('code_cat_completion Kod Tamamlama İmza') && (
                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', padding: '0.75rem', backgroundColor: 'rgba(52, 211, 153, 0.08)', border: '1px solid rgba(52, 211, 153, 0.25)', borderRadius: '8px', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={formData.code_cat_completion ?? true}
                      onChange={(e) => handleFieldChange('code_cat_completion', e.target.checked)}
                    />
                    <div>
                      <strong style={{ fontSize: '0.82rem', color: '#34d399', display: 'block' }}>💻 Kod Tamamlama (İmza ➔ Kod)</strong>
                      <span style={{ fontSize: '0.72rem', color: '#94a3b8' }}><code>code_cat_completion</code></span>
                    </div>
                  </label>
                )}

                {filterMatches('code_cat_bug_fix Hata Ayıklama Güvenlik') && (
                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', padding: '0.75rem', backgroundColor: 'rgba(251, 113, 133, 0.08)', border: '1px solid rgba(251, 113, 133, 0.25)', borderRadius: '8px', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={formData.code_cat_bug_fix ?? true}
                      onChange={(e) => handleFieldChange('code_cat_bug_fix', e.target.checked)}
                    />
                    <div>
                      <strong style={{ fontSize: '0.82rem', color: '#fb7185', display: 'block' }}>🐛 Hata Ayıklama & Güvenlik</strong>
                      <span style={{ fontSize: '0.72rem', color: '#94a3b8' }}><code>code_cat_bug_fix</code></span>
                    </div>
                  </label>
                )}

                {filterMatches('code_cat_unit_test pytest Birim Test') && (
                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', padding: '0.75rem', backgroundColor: 'rgba(251, 191, 36, 0.08)', border: '1px solid rgba(251, 191, 36, 0.25)', borderRadius: '8px', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={formData.code_cat_unit_test ?? true}
                      onChange={(e) => handleFieldChange('code_cat_unit_test', e.target.checked)}
                    />
                    <div>
                      <strong style={{ fontSize: '0.82rem', color: '#fbbf24', display: 'block' }}>🧪 pytest Birim Test Üretimi</strong>
                      <span style={{ fontSize: '0.72rem', color: '#94a3b8' }}><code>code_cat_unit_test</code></span>
                    </div>
                  </label>
                )}
              </div>
            </div>
          )}

          {/* TAB 5: VERİTABANI & RAG */}
          {activeTab === 'storage' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.2rem' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                {filterMatches('db_path SQLite Veritabanı Yolu') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                      SQLite Veritabanı Yolu (<code>db_path</code>)
                    </label>
                    <input
                      type="text"
                      className="form-control"
                      value={formData.db_path || ''}
                      onChange={(e) => handleFieldChange('db_path', e.target.value)}
                      placeholder="database/extract.db"
                    />
                  </div>
                )}

                {filterMatches('qdrant_db_path Qdrant Klasörü') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                      Qdrant Depo Dizini (<code>qdrant_db_path</code>)
                    </label>
                    <input
                      type="text"
                      className="form-control"
                      value={formData.qdrant_db_path || ''}
                      onChange={(e) => handleFieldChange('qdrant_db_path', e.target.value)}
                      placeholder="qdrant_extract"
                    />
                  </div>
                )}
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '1rem' }}>
                {filterMatches('qdrant_collection_name Koleksiyon Adı') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                      Qdrant Koleksiyonu (<code>qdrant_collection_name</code>)
                    </label>
                    <input
                      type="text"
                      className="form-control"
                      value={formData.qdrant_collection_name || ''}
                      onChange={(e) => handleFieldChange('qdrant_collection_name', e.target.value)}
                      placeholder="extract_articles"
                    />
                  </div>
                )}

                {filterMatches('chunk_size Parça Boyutu') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                      Chunk Boyutu (<code>chunk_size</code>)
                    </label>
                    <input
                      type="number"
                      className="form-control"
                      value={formData.chunk_size ?? 800}
                      onChange={(e) => handleFieldChange('chunk_size', Number(e.target.value))}
                    />
                  </div>
                )}

                {filterMatches('chunk_overlap Örtüşme Payı') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                      Chunk Örtüşme (<code>chunk_overlap</code>)
                    </label>
                    <input
                      type="number"
                      className="form-control"
                      value={formData.chunk_overlap ?? 150}
                      onChange={(e) => handleFieldChange('chunk_overlap', Number(e.target.value))}
                    />
                  </div>
                )}
              </div>
            </div>
          )}

          {/* TAB 6: OCR & VİZYON */}
          {activeTab === 'ocr' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.2rem' }}>
              {filterMatches('enable_vision_ocr Görsel OCR') && (
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', padding: '0.75rem', backgroundColor: '#1e293b', borderRadius: '8px', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={formData.enable_vision_ocr ?? true}
                    onChange={(e) => handleFieldChange('enable_vision_ocr', e.target.checked)}
                  />
                  <span style={{ fontSize: '0.82rem' }}>
                    <strong>Görsel OCR Motorunu Aktif Et (<code>enable_vision_ocr</code>):</strong> PDF'teki çizim ve devre şemalarını Vision modeliyle otomatik analiz eder.
                  </span>
                </label>
              )}

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                {filterMatches('ocr_threshold_chars OCR Eşik Karakteri') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                      OCR Eşik Karakteri (<code>ocr_threshold_chars</code>)
                    </label>
                    <input
                      type="number"
                      className="form-control"
                      value={formData.ocr_threshold_chars ?? 100}
                      onChange={(e) => handleFieldChange('ocr_threshold_chars', Number(e.target.value))}
                    />
                    <span style={{ fontSize: '0.72rem', color: '#94a3b8' }}>
                      Sayfadaki metin bu sayının altındaysa OCR tetiklenir
                    </span>
                  </div>
                )}

                {filterMatches('tesseract_cmd Tesseract Yolu') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                      Tesseract Binary Yolu (<code>tesseract_cmd</code>)
                    </label>
                    <input
                      type="text"
                      className="form-control"
                      value={formData.tesseract_cmd || '/opt/homebrew/bin/tesseract'}
                      onChange={(e) => handleFieldChange('tesseract_cmd', e.target.value)}
                    />
                  </div>
                )}
              </div>
            </div>
          )}

          {/* TAB 7: LANGEXTRACT & KIWIX */}
          {activeTab === 'langextract_kiwix' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.2rem' }}>
              {/* LangExtract Grubu */}
              <div style={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '0.65rem', padding: '1rem' }}>
                <h4 style={{ margin: 0, fontSize: '0.9rem', color: '#60a5fa', marginBottom: '0.8rem' }}>
                  🔍 Google LangExtract Entegrasyonu
                </h4>

                <div style={{ display: 'flex', gap: '1.5rem', marginBottom: '1rem' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.82rem', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={formData.enable_langextract ?? true}
                      onChange={(e) => handleFieldChange('enable_langextract', e.target.checked)}
                    />
                    <span style={{ fontWeight: 'bold' }}>LangExtract Aktif</span>
                  </label>

                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.82rem', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={formData.enable_langextract_dynamic_examples ?? true}
                      onChange={(e) => handleFieldChange('enable_langextract_dynamic_examples', e.target.checked)}
                    />
                    <span style={{ color: '#38bdf8', fontWeight: 'bold' }}>✨ Dinamik Doküman Ön Taraması & Few-Shot</span>
                  </label>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                  <div className="form-group">
                    <label style={{ fontSize: '0.78rem' }}>Sağlayıcı (<code>langextract_provider</code>)</label>
                    <select
                      className="form-control"
                      value={formData.langextract_provider || 'ollama'}
                      onChange={(e) => handleFieldChange('langextract_provider', e.target.value)}
                    >
                      <option value="ollama">Ollama (Yerel Ücretsiz)</option>
                      <option value="openai">OpenAI API</option>
                      <option value="gemini">Gemini API (Google)</option>
                    </select>
                  </div>

                  <div className="form-group">
                    <label style={{ fontSize: '0.78rem' }}>Şema Şablonu (<code>langextract_schema_preset</code>)</label>
                    <select
                      className="form-control"
                      value={formData.langextract_schema_preset || 'generic_technical_qa'}
                      onChange={(e) => handleFieldChange('langextract_schema_preset', e.target.value)}
                    >
                      <option value="generic_technical_qa">Generic Technical Q&A</option>
                      <option value="technical_components">Hardware & Technical Components</option>
                      <option value="circuit_specifications">Circuit & Electrical Specs</option>
                      <option value="software_units">Software Architecture & AST</option>
                      <option value="pinout_mappings">Pinout & Signal Mappings</option>
                      <option value="engineering_exercise_sheet">Engineering Exercise Sheet</option>
                    </select>
                  </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                  <div className="form-group">
                    <label style={{ fontSize: '0.78rem' }}>Gemini API Key (Opsiyonel)</label>
                    <input
                      type="password"
                      className="form-control"
                      value={formData.gemini_api_key || ''}
                      onChange={(e) => handleFieldChange('gemini_api_key', e.target.value)}
                      placeholder="AIzaSy..."
                    />
                  </div>

                  <div className="form-group">
                    <label style={{ fontSize: '0.78rem' }}>OpenAI API Key (Opsiyonel)</label>
                    <input
                      type="password"
                      className="form-control"
                      value={formData.openai_api_key || ''}
                      onChange={(e) => handleFieldChange('openai_api_key', e.target.value)}
                      placeholder="sk-..."
                    />
                  </div>
                </div>
              </div>

              {/* Kiwix Grubu */}
              <div style={{ backgroundColor: 'rgba(15, 23, 42, 0.6)', border: '1px solid #334155', borderRadius: '0.65rem', padding: '1rem' }}>
                <h4 style={{ margin: 0, fontSize: '0.9rem', color: '#38bdf8', marginBottom: '0.8rem' }}>
                  🌐 Kiwix & OpenZIM Çıkarıcı
                </h4>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                  <div className="form-group">
                    <label style={{ fontSize: '0.78rem' }}>Yerel .zim Dosya Yolu (<code>kiwix_zim_path</code>)</label>
                    <input
                      type="text"
                      className="form-control"
                      value={formData.kiwix_zim_path || ''}
                      onChange={(e) => handleFieldChange('kiwix_zim_path', e.target.value)}
                      placeholder="downloads/ham.stackexchange.zim"
                    />
                  </div>

                  <div className="form-group">
                    <label style={{ fontSize: '0.78rem' }}>Kiwix İndirme URL (<code>kiwix_download_url</code>)</label>
                    <input
                      type="text"
                      className="form-control"
                      value={formData.kiwix_download_url || ''}
                      onChange={(e) => handleFieldChange('kiwix_download_url', e.target.value)}
                      placeholder="https://download.kiwix.org/zim/..."
                    />
                  </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                  <div className="form-group">
                    <label style={{ fontSize: '0.78rem' }}>İsim Alanları (<code>kiwix_namespaces</code> virgülle ayırın)</label>
                    <input
                      type="text"
                      className="form-control"
                      value={Array.isArray(formData.kiwix_namespaces) ? formData.kiwix_namespaces.join(', ') : ''}
                      onChange={(e) => {
                        const arr = e.target.value.split(',').map((s) => s.trim());
                        handleFieldChange('kiwix_namespaces', arr);
                      }}
                      placeholder="A, "
                    />
                  </div>

                  <div className="form-group">
                    <label style={{ fontSize: '0.78rem' }}>Minimum Karakter (<code>kiwix_min_chars</code>)</label>
                    <input
                      type="number"
                      className="form-control"
                      value={formData.kiwix_min_chars ?? 100}
                      onChange={(e) => handleFieldChange('kiwix_min_chars', Number(e.target.value))}
                    />
                  </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '1rem' }}>
                  <div className="form-group">
                    <label style={{ fontSize: '0.78rem' }}>Ayrıştırma Modu (<code>kiwix_extract_mode</code>)</label>
                    <select
                      className="form-control"
                      value={formData.kiwix_extract_mode || 'auto'}
                      onChange={(e) => handleFieldChange('kiwix_extract_mode', e.target.value)}
                    >
                      <option value="auto">auto (Otomatik Algıla)</option>
                      <option value="stackexchange">stackexchange (Q&A, Tags, Votes & DPO)</option>
                      <option value="wiki">wiki (Ansiklopedi Markdown)</option>
                    </select>
                  </div>

                  <div className="form-group">
                    <label style={{ fontSize: '0.78rem' }}>Toplu Kayıt (<code>kiwix_batch_size</code>)</label>
                    <input
                      type="number"
                      className="form-control"
                      value={formData.kiwix_batch_size ?? 500}
                      onChange={(e) => handleFieldChange('kiwix_batch_size', Number(e.target.value))}
                    />
                  </div>

                  <div className="form-group">
                    <label style={{ fontSize: '0.78rem' }}>DPO Min. Oy Farkı (<code>kiwix_min_vote_diff</code>)</label>
                    <input
                      type="number"
                      className="form-control"
                      value={formData.kiwix_min_vote_diff ?? 2}
                      onChange={(e) => handleFieldChange('kiwix_min_vote_diff', Number(e.target.value))}
                    />
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* TAB 8: HAM JSON & ÖZEL ALANLAR */}
          {activeTab === 'raw_json' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
                  <code>config.json</code> dosyasının ham JSON formatı (Gerçek zamanlı form ile iki yönlü senkronizedir):
                </span>
                <button
                  onClick={handleCopyJson}
                  className="btn btn-secondary"
                  style={{ fontSize: '0.75rem', padding: '0.25rem 0.6rem' }}
                >
                  {copied ? '✓ Kopyalandı' : '📋 JSON Kopyala'}
                </button>
              </div>

              {jsonError && (
                <div style={{ color: '#ef4444', backgroundColor: 'rgba(239, 68, 68, 0.1)', padding: '0.5rem 0.75rem', borderRadius: '6px', fontSize: '0.78rem', border: '1px solid rgba(239, 68, 68, 0.3)' }}>
                  ⚠️ {jsonError}
                </div>
              )}

              <textarea
                className="form-control"
                style={{
                  height: '280px',
                  fontFamily: 'Consolas, Monaco, "Courier New", monospace',
                  fontSize: '0.82rem',
                  lineHeight: '1.45',
                  backgroundColor: '#070b14',
                  color: '#34d399',
                  borderColor: jsonError ? '#ef4444' : '#1f293d',
                }}
                value={rawJsonText}
                onChange={(e) => handleRawJsonChange(e.target.value)}
              />

              {/* Dinamik Özel Alan Ekleme */}
              <div style={{ backgroundColor: '#111827', border: '1px solid #1f293d', borderRadius: '8px', padding: '0.85rem', marginTop: '0.5rem' }}>
                <h5 style={{ margin: 0, fontSize: '0.82rem', color: '#f3f4f6', marginBottom: '0.5rem' }}>
                  ➕ config.json İçin Özel Alan (Custom Key-Value) Ekle
                </h5>

                <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 2fr auto', gap: '0.5rem', alignItems: 'center' }}>
                  <input
                    type="text"
                    className="form-control"
                    placeholder="Anahtar (örn: custom_seed)"
                    style={{ fontSize: '0.78rem' }}
                    value={newKey}
                    onChange={(e) => setNewKey(e.target.value)}
                  />

                  <select
                    className="form-control"
                    style={{ fontSize: '0.78rem' }}
                    value={newValueType}
                    onChange={(e) => setNewValueType(e.target.value as any)}
                  >
                    <option value="string">Metin (string)</option>
                    <option value="number">Sayı (number)</option>
                    <option value="boolean">Mantıksal (boolean)</option>
                  </select>

                  <input
                    type="text"
                    className="form-control"
                    placeholder={newValueType === 'boolean' ? 'true veya false' : 'Değer'}
                    style={{ fontSize: '0.78rem' }}
                    value={newValue}
                    onChange={(e) => setNewValue(e.target.value)}
                  />

                  <button
                    onClick={handleAddCustomKey}
                    className="btn btn-primary"
                    style={{ fontSize: '0.78rem', padding: '0.4rem 0.8rem' }}
                  >
                    Ekle
                  </button>
                </div>

                {customKeys.length > 0 && (
                  <div style={{ marginTop: '0.75rem', borderTop: '1px solid #1e293b', paddingTop: '0.5rem' }}>
                    <span style={{ fontSize: '0.75rem', color: '#94a3b8', display: 'block', marginBottom: '0.35rem' }}>
                      Mevcut Özel Alanlar:
                    </span>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
                      {customKeys.map((k) => (
                        <div
                          key={k}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.35rem',
                            backgroundColor: 'rgba(59, 130, 246, 0.15)',
                            border: '1px solid rgba(59, 130, 246, 0.3)',
                            padding: '0.2rem 0.5rem',
                            borderRadius: '4px',
                            fontSize: '0.75rem',
                          }}
                        >
                          <span><strong>{k}:</strong> {JSON.stringify(formData[k])}</span>
                          <button
                            onClick={() => handleRemoveCustomKey(k)}
                            style={{ background: 'none', border: 'none', color: '#fb7185', cursor: 'pointer', fontWeight: 'bold' }}
                          >
                            ×
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '1rem 1.5rem',
            borderTop: '1px solid #1f293d',
            backgroundColor: '#111827',
          }}
        >
          <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center' }}>
            <button
              onClick={() => {
                setFormData(config);
                setRawJsonText(JSON.stringify(config, null, 2));
              }}
              className="btn btn-secondary"
              style={{ fontSize: '0.8rem', padding: '0.4rem 0.8rem' }}
            >
              ↺ Sıfırla (Mevcut Duruma Dön)
            </button>

            {saveSuccess && (
              <span style={{ color: '#34d399', fontSize: '0.82rem', fontWeight: 600 }}>
                ✓ config.json başarıyla güncellendi!
              </span>
            )}
          </div>

          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
            <button
              onClick={onClose}
              className="btn btn-secondary"
              style={{ fontSize: '0.82rem', padding: '0.45rem 1rem' }}
            >
              Kapat
            </button>
            <button
              onClick={handleSave}
              disabled={isSaving || !!jsonError}
              className="btn btn-primary"
              style={{
                fontSize: '0.85rem',
                fontWeight: 600,
                padding: '0.45rem 1.4rem',
                background: 'linear-gradient(135deg, #3b82f6, #2563eb)',
              }}
            >
              {isSaving ? 'Kaydediliyor... ⏳' : '💾 Yapılandırmayı Kaydet'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
