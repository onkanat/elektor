import React, { useState, useEffect } from 'react';
import { Header } from './components/Header';
import { SectionConfig } from './components/SectionConfig';
import { SectionDatasetViewer } from './components/SectionDatasetViewer';
import { SectionModelChat } from './components/SectionModelChat';
import { SectionJudge } from './components/SectionJudge';
import { ProjectExplorer } from './components/ProjectExplorer';
import { QuickHelpModal } from './components/QuickHelpModal';
import { HFUploadModal } from './components/HFUploadModal';
import type { ProjectItem } from './components/ProjectExplorer';
import type { HealthInfo, PipelineConfig, PipelineState } from './types';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'config' | 'dataset' | 'chat' | 'judge'>('config');
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [config, setConfig] = useState<PipelineConfig | null>(null);
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [activeProjectId, setActiveProjectId] = useState<string>('sdr_engineers');
  const [showProjectExplorer, setShowProjectExplorer] = useState<boolean>(false);
  const [showQuickHelp, setShowQuickHelp] = useState<boolean>(false);
  const [showHFModal, setShowHFModal] = useState<boolean>(false);

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

  const fetchProjects = async () => {
    try {
      const res = await fetch('/api/projects');
      if (res.ok) {
        const data = await res.json();
        setProjects(data.projects || []);
        setActiveProjectId(data.active_project_id || 'sdr_engineers');
      }
    } catch (e) {
      console.error('Fetch projects error:', e);
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
    fetchProjects();
    fetchPipelineStatus();

    const interval = setInterval(() => {
      fetchPipelineStatus();
    }, 2000);

    return () => clearInterval(interval);
  }, []);

  const handleSelectProject = async (projectId: string) => {
    try {
      const res = await fetch('/api/projects/select', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId }),
      });
      if (res.ok) {
        const data = await res.json();
        setActiveProjectId(data.active_project_id);
        setConfig(data.config);
        fetchProjects();
        fetchHealth();
      }
    } catch (e) {
      console.error('Select project error:', e);
    }
  };

  const handleCreateProject = async (payload: any) => {
    const res = await fetch('/api/projects/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errData = await res.json();
      throw new Error(errData.detail || 'Proje oluşturulamadı');
    }
    const data = await res.json();
    setActiveProjectId(data.project_id);
    setConfig(data.config);
    fetchProjects();
    fetchHealth();
  };

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

  const handleRunPipeline = async (
    command: string,
    limit?: string,
    reset?: boolean,
    confirmReset?: boolean,
    shards?: number,
    shardPorts?: string
  ) => {
    try {
      await fetch('/api/pipeline/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          command,
          limit,
          reset,
          confirm_reset: confirmReset,
          shards,
          shard_ports: shardPorts,
        }),
      });
      fetchPipelineStatus();
    } catch (e) {
      console.error('Run pipeline error:', e);
    }
  };

  const activeProjectObj = projects.find((p) => p.project_id === activeProjectId);

  return (
    <div className="app-container">
      <Header
        health={health}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        activeProjectName={activeProjectObj?.project_name || config?.dataset_name}
        onOpenProjectExplorer={() => setShowProjectExplorer(true)}
        onOpenQuickHelp={() => setShowQuickHelp(true)}
        onOpenHFUploadModal={() => setShowHFModal(true)}
      />

      <ProjectExplorer
        isOpen={showProjectExplorer}
        projects={projects}
        activeProjectId={activeProjectId}
        onSelectProject={handleSelectProject}
        onCreateProject={handleCreateProject}
        onRefreshProjects={() => {
          fetchProjects();
          fetchHealth();
        }}
        onClose={() => setShowProjectExplorer(false)}
      />

      <QuickHelpModal
        isOpen={showQuickHelp}
        onClose={() => setShowQuickHelp(false)}
      />

      <HFUploadModal
        isOpen={showHFModal}
        activeProjectId={activeProjectId}
        activeProjectName={activeProjectObj?.project_name || config?.dataset_name}
        projects={projects}
        onClose={() => setShowHFModal(false)}
      />

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

            {activeTab === 'dataset' && (
              <SectionDatasetViewer
                activeProjectId={activeProjectId}
                activeProjectName={activeProjectObj?.project_name || config?.dataset_name}
                activeDatasetName={config?.dataset_name}
              />
            )}

            {activeTab === 'chat' && (
              <SectionModelChat
                config={config}
                availableModels={health?.available_models || []}
              />
            )}

            {activeTab === 'judge' && (
              <SectionJudge
                config={config}
                activeProjectId={activeProjectId}
                onRefreshHealth={fetchHealth}
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
