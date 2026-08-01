import React, { useState, useEffect } from 'react';
import { Header } from './components/Header';
import { SectionConfig } from './components/SectionConfig';
import { SectionDatasetViewer } from './components/SectionDatasetViewer';
import { SectionModelChat } from './components/SectionModelChat';
import type { HealthInfo, PipelineConfig, PipelineState } from './types';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'config' | 'dataset' | 'chat'>('config');
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [config, setConfig] = useState<PipelineConfig | null>(null);
  const [pipelineState, setPipelineState] = useState<PipelineState>({
    status: 'idle',
    command: null,
    start_time: null,
    end_time: null,
    exit_code: null,
    logs: [],
  });

  const fetchHealth = async () => {
    try {
      const res = await fetch('/api/health');
      if (res.ok) {
        const data: HealthInfo = await res.json();
        setHealth(data);
        setConfig(data.config);
      }
    } catch (e) {
      console.error('API health fetch error:', e);
    }
  };

  const fetchPipelineStatus = async () => {
    try {
      const res = await fetch('/api/pipeline/status');
      if (res.ok) {
        const data: PipelineState = await res.json();
        setPipelineState(data);
      }
    } catch (e) {
      console.error('Pipeline status fetch error:', e);
    }
  };

  useEffect(() => {
    fetchHealth();
    fetchPipelineStatus();

    // Poll pipeline status every 2 seconds
    const interval = setInterval(() => {
      fetchPipelineStatus();
    }, 2000);

    return () => clearInterval(interval);
  }, []);

  const handleUpdateConfig = async (newConfig: Partial<PipelineConfig>) => {
    try {
      const res = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newConfig),
      });
      if (res.ok) {
        const data = await res.json();
        setConfig(data.config);
      }
    } catch (e) {
      console.error('Update config error:', e);
    }
  };

  const handleRunPipeline = async (command: string, limit?: string, reset?: boolean) => {
    try {
      await fetch('/api/pipeline/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command, limit, reset }),
      });
      fetchPipelineStatus();
    } catch (e) {
      console.error('Run pipeline error:', e);
    }
  };

  return (
    <div className="app-container">
      <Header health={health} activeTab={activeTab} setActiveTab={setActiveTab} />

      <main className="main-content">
        {config ? (
          <>
            {activeTab === 'config' && (
              <SectionConfig
                config={config}
                onUpdateConfig={handleUpdateConfig}
                pipelineState={pipelineState}
                onRunPipeline={handleRunPipeline}
              />
            )}

            {activeTab === 'dataset' && <SectionDatasetViewer />}

            {activeTab === 'chat' && (
              <SectionModelChat
                config={config}
                availableModels={health?.available_models || []}
              />
            )}
          </>
        ) : (
          <div style={{ padding: '4rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
            Backend API (Port 3456) ile bağlantı kuruluyor... ⏳
          </div>
        )}
      </main>
    </div>
  );
};

export default App;
