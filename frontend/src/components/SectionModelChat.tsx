import { useState, useEffect, useRef } from 'react';
import type { PipelineConfig, ChatMessage } from '../types';

interface SectionModelChatProps {
  config: PipelineConfig;
  availableModels: string[];
}

export const SectionModelChat: React.FC<SectionModelChatProps> = ({ config, availableModels }) => {
  const [selectedModel, setSelectedModel] = useState<string>(config.model_analyzer || 'qwen3.6:27b-mtp-q4_K_M');
  const [systemPrompt, setSystemPrompt] = useState<string>(
    `${config.llm_persona}\nFocus Domain: ${config.llm_subject}`
  );
  const [inputPrompt, setInputPrompt] = useState<string>('');
  
  // Chat Modes: 'standard' vs 'simulator'
  const [chatMode, setChatMode] = useState<'standard' | 'simulator'>('simulator');
  
  // Standard Chat Messages State
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: 'assistant',
      content: 'Merhaba! Ben sentetik veri analitik ve test modelinizim. Döküman veya teknik konu hakkında bana soru sorabilir veya SFT/DPO istemlerini test edebilirsiniz.',
    },
  ]);
  const [isSending, setIsSending] = useState<boolean>(false);

  // Simulator Arena State
  const [simulationHistory, setSimulationHistory] = useState<any[]>([]);
  const [isSimulating, setIsSimulating] = useState<boolean>(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const simEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (config.model_analyzer) {
      setSelectedModel(config.model_analyzer);
    }
    if (config.llm_persona) {
      setSystemPrompt(`${config.llm_persona}\nFocus Domain: ${config.llm_subject}`);
    }
  }, [config]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    simEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, simulationHistory]);

  // Standard Chat Handler
  const handleSendMessage = async () => {
    if (!inputPrompt.trim() || isSending) return;

    const userMsg: ChatMessage = { role: 'user', content: inputPrompt };
    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    setInputPrompt('');
    setIsSending(true);

    try {
      const apiMessages = updatedMessages.filter((m) => m.role !== 'system');

      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: selectedModel,
          messages: apiMessages,
          system_prompt: systemPrompt,
        }),
      });

      const data = await res.json();
      if (res.ok && data.message) {
        setMessages([...updatedMessages, data.message]);
      } else {
        setMessages([
          ...updatedMessages,
          { role: 'assistant', content: `[Hata]: ${data.detail || 'Model yanıt vermedi.'}` },
        ]);
      }
    } catch (e: any) {
      setMessages([
        ...updatedMessages,
        { role: 'assistant', content: `[Bağlantı Hatası]: ${e.message}` },
      ]);
    } finally {
      setIsSending(false);
    }
  };

  // Pre-Fine-Tuning Simulator Handler
  const handleRunSimulation = async () => {
    if (!inputPrompt.trim() || isSimulating) return;

    const promptText = inputPrompt;
    setInputPrompt('');
    setIsSimulating(true);

    try {
      const res = await fetch('/api/chat/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: selectedModel,
          prompt: promptText,
          system_prompt: systemPrompt,
        }),
      });

      const data = await res.json();
      if (res.ok) {
        setSimulationHistory((prev) => [...prev, data]);
      } else {
        alert(`Simülasyon Hatası: ${data.detail || 'Bilinmeyen hata'}`);
      }
    } catch (e: any) {
      alert(`Simülasyon Bağlantı Hatası: ${e.message}`);
    } finally {
      setIsSimulating(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      {/* Üst Mod Seçim Barı */}
      <div className="card" style={{ padding: '0.75rem 1.25rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <span style={{ fontWeight: 600, fontSize: '1rem', color: 'var(--text-primary)' }}>🎯 Bölüm C Çalışma Modu:</span>
          <div className="nav-tabs" style={{ background: 'var(--bg-primary)', padding: '0.2rem' }}>
            <button
              className={`tab-btn ${chatMode === 'simulator' ? 'active' : ''}`}
              onClick={() => setChatMode('simulator')}
              style={{ fontSize: '0.82rem', padding: '0.35rem 0.85rem' }}
            >
              ⚔️ Pre-FT Etki Simülatörü Arena
            </button>
            <button
              className={`tab-btn ${chatMode === 'standard' ? 'active' : ''}`}
              onClick={() => setChatMode('standard')}
              style={{ fontSize: '0.82rem', padding: '0.35rem 0.85rem' }}
            >
              💬 Standart Model Sohbet
            </button>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Aktif Model:</span>
          <select
            className="form-control"
            style={{ width: 'auto', padding: '0.25rem 0.5rem', fontSize: '0.8rem' }}
            value={selectedModel}
            onChange={(e) => setSelectedModel(e.target.value)}
          >
            {availableModels.length > 0 ? (
              availableModels.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))
            ) : (
              <option value={config.model_analyzer}>{config.model_analyzer}</option>
            )}
          </select>
        </div>
      </div>

      {/* MOD 1: PRE-FINE-TUNING IMPACT SIMULATOR ARENA */}
      {chatMode === 'simulator' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          {/* Prompt Sandbox Accordion/Settings */}
          <div className="card" style={{ padding: '1rem' }}>
            <label style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.4rem', display: 'block' }}>
              ⚙️ Simülasyon Uzmanlık Kimliği (System Persona / Focus Subject Prompt)
            </label>
            <textarea
              className="form-control"
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              rows={2}
              style={{ fontSize: '0.82rem' }}
              placeholder="Model personanızı girin..."
            />
          </div>

          {/* Arena Visual Comparisons */}
          {simulationHistory.length === 0 ? (
            <div className="card" style={{ textAlign: 'center', padding: '3rem 2rem', background: 'rgba(15, 23, 42, 0.4)' }}>
              <div style={{ fontSize: '2.5rem', marginBottom: '0.75rem' }}>⚔️</div>
              <h3 style={{ margin: '0 0 0.5rem 0', color: 'var(--text-primary)' }}>Model Eğitimi Öncesi Katkı & Etki Simülatörü</h3>
              <p style={{ maxWidth: '650px', margin: '0 auto', fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                Aşağıdaki girdi alanına bir soru veya teknik konu yazarak <strong>Ham Model (Zero-Shot)</strong> ile <strong>Veritabanı & SFT Enjekteli Modeli</strong> yan yana karşılaştırın. Sistem otonom olarak Qdrant, SQLite ve JSONL araçlarını çağırarak eğitimin modele sağlayacağı <strong>Bilgi Kazanımı (%)</strong> farkını simüle eder.
              </p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
              {simulationHistory.map((sim: any, idx: number) => {
                const evalData = sim.evaluation || {};
                const gain = evalData.knowledge_gain_percent || 0;
                
                return (
                  <div key={idx} className="card" style={{ border: '1px solid var(--border-color)', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                    {/* Soru Başlığı */}
                    <div style={{ background: 'var(--bg-primary)', padding: '0.75rem 1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-color)', fontWeight: 600, color: 'var(--accent-cyan)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span>❓ Soru #{idx + 1}: "{sim.prompt}"</span>
                      <span className="badge online" style={{ fontSize: '0.75rem' }}>Model: {sim.model}</span>
                    </div>

                    {/* Delta Impact Scorecard Banner */}
                    <div style={{ background: 'rgba(59, 130, 246, 0.1)', padding: '0.85rem 1.25rem', borderRadius: 'var(--radius-md)', border: '1px solid rgba(59, 130, 246, 0.3)', display: 'grid', gridTemplateColumns: '1fr 1fr 1.5fr', gap: '1rem', alignItems: 'center' }}>
                      <div>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>📊 Bilgi Kazanımı (Gain)</div>
                        <div style={{ fontSize: '1.4rem', fontWeight: 800, color: gain >= 50 ? '#34d399' : '#f59e0b' }}>
                          +{gain}%
                        </div>
                      </div>
                      <div>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>🎯 Olgusal Doğruluk</div>
                        <div style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--text-primary)', marginTop: '0.2rem' }}>
                          {evalData.factuality || 'Yüksek'}
                        </div>
                      </div>
                      <div>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>⚖️ FT Karar Tavsiyesi</div>
                        <div style={{ fontSize: '0.95rem', fontWeight: 700, color: '#60a5fa', marginTop: '0.2rem' }}>
                          {evalData.verdict || 'Fine-Tuning Önerilir'}
                        </div>
                        {evalData.explanation && (
                          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                            {evalData.explanation}
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Tool Call Badges */}
                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                      {sim.tool_logs?.map((tool: any, tIdx: number) => (
                        <div key={tIdx} className="badge online" style={{ fontSize: '0.75rem', background: 'rgba(16, 185, 129, 0.15)', border: '1px solid rgba(16, 185, 129, 0.3)', color: '#34d399' }}>
                          🛠️ {tool.name}: {tool.count !== undefined ? `${tool.count} sonuç` : (tool.articles_found ? `${tool.articles_found} döküman` : 'Başarılı')}
                        </div>
                      ))}
                    </div>

                    {/* Side-by-Side Comparison Columns */}
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                      {/* Left: Base Model */}
                      <div style={{ background: 'rgba(15, 23, 42, 0.6)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid rgba(239, 68, 68, 0.3)' }}>
                        <div style={{ fontSize: '0.85rem', fontWeight: 700, color: '#f87171', marginBottom: '0.5rem', display: 'flex', justifyContent: 'space-between' }}>
                          <span>🛡️ Ham Model (Zero-Shot)</span>
                          <span style={{ fontSize: '0.72rem', opacity: 0.7 }}>Eğitimsiz / RAG'sız</span>
                        </div>
                        <div style={{ fontSize: '0.83rem', color: '#cbd5e1', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
                          {sim.base_response}
                        </div>
                      </div>

                      {/* Right: Simulated FT Model */}
                      <div style={{ background: 'rgba(15, 23, 42, 0.6)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid rgba(16, 185, 129, 0.4)' }}>
                        <div style={{ fontSize: '0.85rem', fontWeight: 700, color: '#34d399', marginBottom: '0.5rem', display: 'flex', justifyContent: 'space-between' }}>
                          <span>⚡ Simüle Edilmiş FT Model</span>
                          <span style={{ fontSize: '0.72rem', opacity: 0.7 }}>RAG + SFT Context</span>
                        </div>
                        <div style={{ fontSize: '0.83rem', color: '#f8fafc', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
                          {sim.simulated_response}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
              {isSimulating && (
                <div className="card" style={{ padding: '1.5rem', textAlign: 'center', color: 'var(--accent-cyan)' }}>
                  ⏳ Otonom RAG & MCP araçları çağrılıyor, Ham vs Simüle model yanıtları karşılaştırılıyor...
                </div>
              )}
              <div ref={simEndRef} />
            </div>
          )}

          {/* Simulator Input Area */}
          <div className="card" style={{ padding: '0.75rem 1rem' }}>
            <div className="chat-input-area" style={{ padding: 0 }}>
              <input
                type="text"
                className="form-control"
                placeholder="Model eğitimi öncesi etkisini simüle etmek istediğiniz soruyu yazın..."
                value={inputPrompt}
                onChange={(e) => setInputPrompt(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleRunSimulation()}
              />
              <button className="btn btn-primary" onClick={handleRunSimulation} disabled={isSimulating}>
                {isSimulating ? 'Simüle Ediliyor...' : '⚔️ Etkiyi Simüle Et'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MOD 2: STANDART MODEL SOHBET */}
      {chatMode === 'standard' && (
        <div className="grid-2">
          {/* Sol Kart: System Prompt Sandbox */}
          <div className="card">
            <div className="card-title">
              <span>⚙️</span> Model & Prompt Sandbox Ayarları
            </div>

            <div className="form-group">
              <label>Sistem Talimatı (System Persona / Subject Prompt)</label>
              <textarea
                className="form-control"
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                rows={8}
                placeholder="Model personanızı girin..."
              />
            </div>

            <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', background: 'var(--bg-primary)', padding: '0.75rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-color)' }}>
              💡 <strong>İpucu:</strong> Bu alanda modelin uzmanlık personasına ve konu alanına uyumunu standart sohbet üzerinden canlı test edebilirsiniz.
            </div>
          </div>

          {/* Sağ Kart: Canlı Chat Arayüzü */}
          <div className="chat-container">
            <div className="chat-header">
              <span style={{ fontWeight: 600 }}>💬 Standart Model Chat</span>
              <span className="badge online" style={{ fontSize: '0.75rem' }}>
                Model: {selectedModel}
              </span>
            </div>

            <div className="chat-messages">
              {messages.map((msg: ChatMessage, index: number) => (
                <div key={index} className={`chat-bubble ${msg.role}`}>
                  <div style={{ fontSize: '0.75rem', fontWeight: 600, marginBottom: '0.25rem', opacity: 0.8 }}>
                    {msg.role === 'user' ? 'Siz (User)' : 'Analyzer Model'}
                  </div>
                  <div style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>
                </div>
              ))}
              {isSending && (
                <div className="chat-bubble assistant" style={{ color: 'var(--accent-cyan)' }}>
                  Model düşünüyor ve yanıt üretiyor... ⏳
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            <div className="chat-input-area">
              <input
                type="text"
                className="form-control"
                placeholder="Test etmek istediğiniz soruyu veya teknik konuyu yazın..."
                value={inputPrompt}
                onChange={(e) => setInputPrompt(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
              />
              <button className="btn btn-primary" onClick={handleSendMessage} disabled={isSending}>
                Gönder 🚀
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
