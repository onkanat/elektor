import { useState } from 'react';

export interface ProjectItem {
  project_id: string;
  project_name: string;
  config_file?: string;
  created_at?: number;
  last_accessed?: number;
}

interface ProjectExplorerProps {
  isOpen: boolean;
  projects: ProjectItem[];
  activeProjectId: string;
  onSelectProject: (projectId: string) => Promise<void>;
  onCreateProject: (payload: any) => Promise<void>;
  onClose: () => void;
}

export const ProjectExplorer: React.FC<ProjectExplorerProps> = ({
  isOpen,
  projects,
  activeProjectId,
  onSelectProject,
  onCreateProject,
  onClose,
}) => {
  const [showCreateModal, setShowCreateModal] = useState<boolean>(false);
  const [newProjectId, setNewProjectId] = useState<string>('');
  const [newProjectName, setNewProjectName] = useState<string>('');
  const [newInputMode, setNewInputMode] = useState<'book' | 'folder'>('book');
  const [newInputPath, setNewInputPath] = useState<string>('');
  const [newPersona, setNewPersona] = useState<string>('Professional Systems Engineer');
  const [newSubject, setNewSubject] = useState<string>('Technical Documentation & Architecture');
  const [isCreating, setIsCreating] = useState<boolean>(false);

  if (!isOpen) return null;

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newProjectId.trim() || !newProjectName.trim()) return;

    setIsCreating(true);
    try {
      await onCreateProject({
        project_id: newProjectId,
        project_name: newProjectName,
        input_mode: newInputMode,
        input_path: newInputPath,
        llm_persona: newPersona,
        llm_subject: newSubject,
      });
      setShowCreateModal(false);
      setNewProjectId('');
      setNewProjectName('');
      onClose();
    } catch (err: any) {
      alert(`Hata: ${err.message}`);
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.75)',
        backdropFilter: 'blur(5px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 999,
      }}
    >
      <div
        className="card"
        style={{
          width: '90%',
          maxWidth: '780px',
          maxHeight: '85vh',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div className="card-title" style={{ justifyContent: 'space-between' }}>
          <span>🗂️ Proje Gezgini & Çoklu Veri Setleri</span>
          <button className="btn btn-secondary" style={{ padding: '0.2rem 0.6rem' }} onClick={onClose}>
            ✕ Kapat
          </button>
        </div>

        {/* Action Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
          <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            Kayıtlı Projeler ({projects.length}) — Son gezilen proje otomatik hafızada tutulur.
          </span>
          <button className="btn btn-emerald" onClick={() => setShowCreateModal(true)}>
            ➕ Yeni Proje Oluştur
          </button>
        </div>

        {/* Create Modal Form View */}
        {showCreateModal ? (
          <form onSubmit={handleCreateSubmit} style={{ background: 'var(--bg-primary)', padding: '1.25rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)', marginBottom: '1rem' }}>
            <h3 style={{ fontSize: '1rem', marginBottom: '1rem', color: 'var(--accent-cyan)' }}>✨ Yeni Proje Tanımla</h3>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
              <div className="form-group">
                <label>Proje Kimliği (Project ID)</label>
                <input
                  type="text"
                  className="form-control"
                  placeholder="örn: rp2040_datasheet"
                  value={newProjectId}
                  onChange={(e) => setNewProjectId(e.target.value)}
                  required
                />
              </div>

              <div className="form-group">
                <label>Proje / Veri Seti Adı</label>
                <input
                  type="text"
                  className="form-control"
                  placeholder="örn: RP2040 Microcontroller Datasheet"
                  value={newProjectName}
                  onChange={(e) => setNewProjectName(e.target.value)}
                  required
                />
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '1rem' }}>
              <div className="form-group">
                <label>İşleme Modu</label>
                <select
                  className="form-control"
                  value={newInputMode}
                  onChange={(e: any) => setNewInputMode(e.target.value)}
                >
                  <option value="book">Book Mode (Tek PDF)</option>
                  <option value="folder">Folder Mode (PDF Klasörü)</option>
                </select>
              </div>

              <div className="form-group">
                <label>Döküman / Dosya Yolu</label>
                <input
                  type="text"
                  className="form-control"
                  placeholder="/Users/.../document.pdf"
                  value={newInputPath}
                  onChange={(e) => setNewInputPath(e.target.value)}
                />
              </div>
            </div>

            <div className="form-group">
              <label>Hedef Uzmanlık Personası (Persona)</label>
              <input
                type="text"
                className="form-control"
                value={newPersona}
                onChange={(e) => setNewPersona(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label>Konu & Alan Tanımı (Subject)</label>
              <input
                type="text"
                className="form-control"
                value={newSubject}
                onChange={(e) => setNewSubject(e.target.value)}
              />
            </div>

            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end', marginTop: '1rem' }}>
              <button type="button" className="btn btn-secondary" onClick={() => setShowCreateModal(false)}>
                İptal
              </button>
              <button type="submit" className="btn btn-primary" disabled={isCreating}>
                {isCreating ? 'Oluşturuluyor...' : 'Oluştur & Aktif Et 🚀'}
              </button>
            </div>
          </form>
        ) : null}

        {/* Project List Stream */}
        <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          {projects.map((proj) => {
            const isActive = proj.project_id === activeProjectId;
            return (
              <div
                key={proj.project_id}
                className="json-card"
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  borderColor: isActive ? 'var(--accent-blue)' : 'var(--border-color)',
                  background: isActive ? 'rgba(59, 130, 246, 0.08)' : 'var(--bg-primary)',
                }}
              >
                <div>
                  <div style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span>{proj.project_name}</span>
                    {isActive && (
                      <span className="badge online" style={{ fontSize: '0.7rem' }}>
                        ● Aktif Proje
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                    ID: <code>{proj.project_id}</code> | Config: <code>{proj.config_file || 'config.json'}</code>
                  </div>
                </div>

                <div>
                  {isActive ? (
                    <span style={{ fontSize: '0.8rem', color: '#34d399', fontWeight: 500 }}>Seçili ✓</span>
                  ) : (
                    <button
                      className="btn btn-primary"
                      style={{ padding: '0.35rem 0.8rem', fontSize: '0.8rem' }}
                      onClick={async () => {
                        await onSelectProject(proj.project_id);
                        onClose();
                      }}
                    >
                      Geçiş Yap ▶
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
