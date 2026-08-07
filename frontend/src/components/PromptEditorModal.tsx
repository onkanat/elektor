import React, { useState, useEffect } from 'react';

export interface PersonaItem {
  persona_id: string;
  title: string;
  description: string;
  author: string;
  system_prompt: string;
}

interface PromptEditorModalProps {
  isOpen: boolean;
  initialPersona?: string;
  initialSubject?: string;
  onClose: () => void;
  onApplyPrompt: (persona: string, subject: string, systemPrompt?: string) => void;
}

export const PromptEditorModal: React.FC<PromptEditorModalProps> = ({
  isOpen,
  initialPersona = '',
  initialSubject = '',
  onClose,
  onApplyPrompt,
}) => {
  const [activeTab, setActiveTab] = useState<'prompt' | 'tools' | 'personas'>('prompt');
  const [personaName, setPersonaName] = useState<string>(initialPersona);
  const [subjectName, setSubjectName] = useState<string>(initialSubject);
  const [systemPrompt, setSystemPrompt] = useState<string>(
    'You are a senior domain expert and principal software architect. Provide clear, highly technical, and production-ready implementations without greetings or conversational filler.'
  );

  const [personas, setPersonas] = useState<PersonaItem[]>([]);
  const [selectedPersonaId, setSelectedPersonaId] = useState<string>('');
  const [toolsJson, setToolsJson] = useState<string>(
    JSON.stringify(
      {
        tools: [
          {
            type: 'function',
            function: {
              name: 'execute_code',
              description: 'Executes source code in a sandboxed runtime environment',
              parameters: {
                type: 'object',
                properties: {
                  code: { type: 'string', description: 'Source code snippet' },
                  language: { type: 'string', enum: ['python', 'c++', 'octave'] }
                },
                required: ['code']
              }
            }
          }
        ]
      },
      null,
      2
    )
  );

  useEffect(() => {
    if (isOpen) {
      setPersonaName(initialPersona);
      setSubjectName(initialSubject);
      fetch('/api/personas')
        .then((res) => res.json())
        .then((data) => setPersonas(data.personas || []))
        .catch((err) => console.error('Failed to load personas:', err));
    }
  }, [isOpen, initialPersona, initialSubject]);

  if (!isOpen) return null;

  const charCount = systemPrompt.length;
  const wordCount = systemPrompt.trim() ? systemPrompt.trim().split(/\s+/).length : 0;
  const MAX_CHARS = 4000;
  const isNearLimit = charCount > MAX_CHARS * 0.9;

  const handleSelectPersonaTemplate = (p: PersonaItem) => {
    setPersonaName(p.title);
    setSubjectName(p.description);
    if (p.system_prompt) {
      setSystemPrompt(p.system_prompt);
    }
    setSelectedPersonaId(p.persona_id);
  };

  const handleSaveAndApply = () => {
    onApplyPrompt(personaName, subjectName, systemPrompt);
    onClose();
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
        backgroundColor: 'rgba(0, 0, 0, 0.8)',
        backdropFilter: 'blur(5px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1100,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          backgroundColor: '#0f172a',
          border: '1px solid #334155',
          borderRadius: '0.75rem',
          width: '90%',
          maxWidth: '900px',
          maxHeight: '92vh',
          overflowY: 'auto',
          padding: '1.5rem',
          boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.7)',
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', borderBottom: '1px solid #1e293b', paddingBottom: '0.75rem' }}>
          <div>
            <h2 style={{ margin: 0, fontSize: '1.2rem', color: '#38bdf8', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span>✨</span> Developer System Prompt & Persona Schema Editor
            </h2>
            <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>AI Persona, Sistem Komutları ve Tool Şeması Tasarım Laboratuvarı</span>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#94a3b8', fontSize: '1.5rem', cursor: 'pointer' }}>×</button>
        </div>

        {/* Tab Buttons */}
        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', borderBottom: '1px solid #334155', paddingBottom: '0.5rem' }}>
          <button
            onClick={() => setActiveTab('prompt')}
            style={{
              backgroundColor: activeTab === 'prompt' ? 'rgba(56, 189, 248, 0.15)' : 'transparent',
              border: `1px solid ${activeTab === 'prompt' ? '#38bdf8' : 'transparent'}`,
              color: activeTab === 'prompt' ? '#38bdf8' : '#94a3b8',
              padding: '0.4rem 0.8rem', borderRadius: '0.35rem', cursor: 'pointer', fontWeight: 600, fontSize: '0.82rem'
            }}
          >
            📝 System Prompt & Metin Editörü
          </button>
          <button
            onClick={() => setActiveTab('personas')}
            style={{
              backgroundColor: activeTab === 'personas' ? 'rgba(168, 85, 247, 0.15)' : 'transparent',
              border: `1px solid ${activeTab === 'personas' ? '#c084fc' : 'transparent'}`,
              color: activeTab === 'personas' ? '#c084fc' : '#94a3b8',
              padding: '0.4rem 0.8rem', borderRadius: '0.35rem', cursor: 'pointer', fontWeight: 600, fontSize: '0.82rem'
            }}
          >
            🏛️ Persona & Uzmanlık Kütüphanesi ({personas.length})
          </button>
          <button
            onClick={() => setActiveTab('tools')}
            style={{
              backgroundColor: activeTab === 'tools' ? 'rgba(52, 211, 153, 0.15)' : 'transparent',
              border: `1px solid ${activeTab === 'tools' ? '#34d399' : 'transparent'}`,
              color: activeTab === 'tools' ? '#34d399' : '#94a3b8',
              padding: '0.4rem 0.8rem', borderRadius: '0.35rem', cursor: 'pointer', fontWeight: 600, fontSize: '0.82rem'
            }}
          >
            🛠️ Tool Schemas (JSON)
          </button>
        </div>

        {/* TAB 1: SYSTEM PROMPT EDITOR */}
        {activeTab === 'prompt' && (
          <div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1rem' }}>
              <div>
                <label style={{ fontSize: '0.8rem', color: '#cbd5e1', fontWeight: 600 }}>Hedef Uzmanlık Personası (Persona Name)</label>
                <input
                  type="text"
                  className="form-control"
                  value={personaName}
                  onChange={(e) => setPersonaName(e.target.value)}
                  placeholder="örn: Professional Systems Engineer"
                />
              </div>
              <div>
                <label style={{ fontSize: '0.8rem', color: '#cbd5e1', fontWeight: 600 }}>Konu & Alan Tanımı (Subject)</label>
                <input
                  type="text"
                  className="form-control"
                  value={subjectName}
                  onChange={(e) => setSubjectName(e.target.value)}
                  placeholder="örn: Technical Documentation & Architecture"
                />
              </div>
            </div>

            <div style={{ marginBottom: '1rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.35rem' }}>
                <label style={{ fontSize: '0.8rem', color: '#cbd5e1', fontWeight: 600 }}>System Prompt (Sistem Talimatı)</label>
                <span style={{ fontSize: '0.75rem', color: isNearLimit ? '#ef4444' : '#94a3b8' }}>
                  {wordCount} kelime | <strong style={{ color: isNearLimit ? '#ef4444' : '#38bdf8' }}>{charCount}/{MAX_CHARS}</strong> karakter
                </span>
              </div>
              <textarea
                className="form-control"
                style={{
                  minHeight: '220px',
                  fontFamily: 'Consolas, Monaco, monospace',
                  fontSize: '0.85rem',
                  lineHeight: '1.5',
                  backgroundColor: '#1e293b',
                  color: '#f8fafc',
                  borderColor: isNearLimit ? '#ef4444' : '#334155',
                }}
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
              />
            </div>
          </div>
        )}

        {/* TAB 2: PERSONA LIBRARY */}
        {activeTab === 'personas' && (
          <div>
            <div style={{ fontSize: '0.8rem', color: '#94a3b8', marginBottom: '1rem' }}>
              <code>system_prompts</code> veritabanından yüklenen önceden yapılandırılmış uzmanlık personoları. Bir persona seçerek prompt ve konu bilgilerini tek tıkla uygulayabilirsiniz:
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', maxHeight: '350px', overflowY: 'auto', paddingRight: '0.25rem' }}>
              {personas.map((p) => (
                <div
                  key={p.persona_id}
                  onClick={() => handleSelectPersonaTemplate(p)}
                  style={{
                    backgroundColor: selectedPersonaId === p.persona_id ? 'rgba(168, 85, 247, 0.2)' : '#1e293b',
                    border: `1px solid ${selectedPersonaId === p.persona_id ? '#c084fc' : '#334155'}`,
                    padding: '0.75rem',
                    borderRadius: '0.5rem',
                    cursor: 'pointer',
                    transition: 'all 0.2s ease',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.35rem' }}>
                    <strong style={{ fontSize: '0.85rem', color: '#f8fafc' }}>{p.title}</strong>
                    <span style={{ fontSize: '0.7rem', color: '#c084fc', backgroundColor: 'rgba(168, 85, 247, 0.15)', padding: '0.15rem 0.4rem', borderRadius: '0.25rem' }}>{p.author}</span>
                  </div>
                  <p style={{ fontSize: '0.78rem', color: '#94a3b8', margin: 0, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                    {p.description}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* TAB 3: TOOL SCHEMAS */}
        {activeTab === 'tools' && (
          <div>
            <div style={{ fontSize: '0.8rem', color: '#94a3b8', marginBottom: '0.5rem' }}>
              LLM modelinin çağırabileceği fonksiyon şemaları (JSON Schema):
            </div>
            <textarea
              className="form-control"
              style={{
                minHeight: '250px',
                fontFamily: 'Consolas, Monaco, monospace',
                fontSize: '0.82rem',
                backgroundColor: '#1e293b',
                color: '#34d399',
                borderColor: '#334155',
              }}
              value={toolsJson}
              onChange={(e) => setToolsJson(e.target.value)}
            />
          </div>
        )}

        {/* Footer Actions */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid #1e293b', paddingTop: '1rem', marginTop: '1.25rem' }}>
          <button onClick={onClose} className="btn btn-secondary" style={{ fontSize: '0.8rem' }}>
            İptal
          </button>
          <button onClick={handleSaveAndApply} className="btn btn-emerald" style={{ fontSize: '0.85rem', fontWeight: 600, padding: '0.5rem 1.25rem' }}>
            🚀 Personayı Projeye Uygula ve Kaydet
          </button>
        </div>
      </div>
    </div>
  );
};
