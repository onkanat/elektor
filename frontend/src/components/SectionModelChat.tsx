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
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: 'assistant',
      content: 'Merhaba! Ben sentetik veri analitik ve test modelinizim. Döküman veya teknik konu hakkında bana soru sorabilir veya SFT/DPO istemlerini test edebilirsiniz.',
    },
  ]);
  const [isSending, setIsSending] = useState<boolean>(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

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
  }, [messages]);

  const handleSendMessage = async () => {
    if (!inputPrompt.trim() || isSending) return;

    const userMsg: ChatMessage = { role: 'user', content: inputPrompt };
    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    setInputPrompt('');
    setIsSending(true);

    try {
      // Filter system prompt out of messages array for payload
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

  return (
    <div className="grid-2">
      {/* Sol Kart: System Prompt Sandbox & Model Ayarları */}
      <div className="card">
        <div className="card-title">
          <span>⚙️</span> Model & Prompt Sandbox Ayarları
        </div>

        <div className="form-group">
          <label>Aktif Analyzer Model (Ollama)</label>
          <select
            className="form-control"
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
          💡 <strong>İpucu:</strong> Bu sandbox alanı üzerinden modelin SFT soru/cevap üretmeden önce verilen uzmanlık personasına ve konu alanına uyumunu canlı olarak test edebilirsiniz.
        </div>
      </div>

      {/* Sağ Kart: Canlı Chat Arayüzü */}
      <div className="chat-container">
        <div className="chat-header">
          <span style={{ fontWeight: 600 }}>💬 Model Test Chat</span>
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
  );
};
