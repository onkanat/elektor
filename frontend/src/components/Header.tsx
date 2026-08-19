import React from 'react';
import type { HealthInfo } from '../types';
import { SystemMetricsCard } from './SystemMetricsCard';

interface HeaderProps {
  health: HealthInfo | null;
  activeTab: 'config' | 'dataset' | 'chat' | 'judge';
  setActiveTab: (tab: 'config' | 'dataset' | 'chat' | 'judge') => void;
  activeProjectName?: string;
  onOpenProjectExplorer: () => void;
  onOpenQuickHelp: () => void;
  onOpenHFUploadModal: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  health,
  activeTab,
  setActiveTab,
  activeProjectName,
  onOpenProjectExplorer,
  onOpenQuickHelp,
  onOpenHFUploadModal,
}) => {
  const isOllamaOnline = health?.ollama_status === 'online';

  return (
    <header className="app-header">
      <div className="brand" style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
        <button
          className="help-icon-btn"
          title="Hızlı Yardım & Dokümantasyon (README.md)"
          onClick={onOpenQuickHelp}
          style={{
            background: 'rgba(59, 130, 246, 0.15)',
            border: '1px solid var(--accent-blue)',
            color: '#60a5fa',
            borderRadius: '50%',
            width: '32px',
            height: '32px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            fontSize: '1.1rem',
            fontWeight: 'bold',
            transition: 'all 0.2s ease',
            boxShadow: '0 0 10px rgba(59, 130, 246, 0.2)'
          }}
        >
          ❓
        </button>
        <div className="brand-icon">⚡</div>
        <div className="brand-title">
          <h1>Elektor Sentetik Veri Platformu</h1>
          <p>Universal PDF & RAG Dataset Generator</p>
        </div>
      </div>

      <nav className="nav-tabs">
        <button
          className={`tab-btn ${activeTab === 'config' ? 'active' : ''}`}
          onClick={() => setActiveTab('config')}
        >
          ⚙️ Girdi & Config
        </button>
        <button
          className={`tab-btn ${activeTab === 'dataset' ? 'active' : ''}`}
          onClick={() => setActiveTab('dataset')}
        >
          📊 Dataset & DB
        </button>
        <button
          className={`tab-btn ${activeTab === 'chat' ? 'active' : ''}`}
          onClick={() => setActiveTab('chat')}
        >
          💬 Analyzer Chat
        </button>
        <button
          className={`tab-btn ${activeTab === 'judge' ? 'active' : ''}`}
          onClick={() => setActiveTab('judge')}
          style={{
            borderColor: activeTab === 'judge' ? '#818cf8' : undefined,
            boxShadow: activeTab === 'judge' ? '0 0 12px rgba(99, 102, 241, 0.3)' : undefined,
          }}
        >
          🏛️ LLM Hakem & Editor
        </button>
      </nav>

      <div className="header-badges">
        {/* Live System Metrics (CPU, RAM, VRAM) */}
        <SystemMetricsCard />

        {/* Proje Gezgini Launcher Button */}
        <button
          className="btn btn-secondary"
          style={{ padding: '0.35rem 0.75rem', fontSize: '0.8rem', borderColor: 'var(--accent-blue)' }}
          onClick={onOpenProjectExplorer}
        >
          🗂️ Proje: <strong>{activeProjectName || health?.config?.dataset_name || 'sdr_engineers'}</strong>
        </button>

        {/* Phase 4 HF & Cloud GPU Launcher Button */}
        <button
          className="btn btn-emerald"
          style={{ padding: '0.35rem 0.75rem', fontSize: '0.8rem', fontWeight: 600 }}
          onClick={onOpenHFUploadModal}
          title="Hugging Face Hub Upload & Bulut GPU Fine-Tuning Paket Jeneratörü"
        >
          🤗 HF & Bulut GPU
        </button>

        <div className={`badge ${isOllamaOnline ? 'online' : 'offline'}`}>
          <span className="dot"></span>
          Ollama: {isOllamaOnline ? 'Aktif' : 'Çevrimdışı'}
        </div>
      </div>
    </header>
  );
};
