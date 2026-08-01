import type { HealthInfo } from '../types';

interface HeaderProps {
  health: HealthInfo | null;
  activeTab: 'config' | 'dataset' | 'chat';
  setActiveTab: (tab: 'config' | 'dataset' | 'chat') => void;
  activeProjectName?: string;
  onOpenProjectExplorer: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  health,
  activeTab,
  setActiveTab,
  activeProjectName,
  onOpenProjectExplorer,
}) => {
  const isOllamaOnline = health?.ollama_status === 'online';

  return (
    <header className="app-header">
      <div className="brand">
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
          ⚙️ Bölüm A: Girdi & Config
        </button>
        <button
          className={`tab-btn ${activeTab === 'dataset' ? 'active' : ''}`}
          onClick={() => setActiveTab('dataset')}
        >
          📊 Bölüm B: Dataset & DB
        </button>
        <button
          className={`tab-btn ${activeTab === 'chat' ? 'active' : ''}`}
          onClick={() => setActiveTab('chat')}
        >
          💬 Bölüm C: Analyzer Chat
        </button>
      </nav>

      <div className="header-badges">
        {/* Proje Gezgini Launcher Button */}
        <button
          className="btn btn-secondary"
          style={{ padding: '0.35rem 0.75rem', fontSize: '0.8rem', borderColor: 'var(--accent-blue)' }}
          onClick={onOpenProjectExplorer}
        >
          🗂️ Proje: <strong>{activeProjectName || health?.config?.dataset_name || 'sdr_engineers'}</strong>
        </button>

        <div className={`badge ${isOllamaOnline ? 'online' : 'offline'}`}>
          <span className="dot"></span>
          Ollama: {isOllamaOnline ? 'Aktif' : 'Çevrimdışı'}
        </div>

        <div className="badge online">
          <span className="dot"></span>
          Port: 3456
        </div>
      </div>
    </header>
  );
};
