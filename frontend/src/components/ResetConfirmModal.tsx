import { useState } from 'react';

interface ResetConfirmModalProps {
  isOpen: boolean;
  projectName: string;
  projectId: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export const ResetConfirmModal: React.FC<ResetConfirmModalProps> = ({
  isOpen,
  projectName,
  projectId,
  onConfirm,
  onCancel,
}) => {
  const [confirmInput, setConfirmInput] = useState<string>('');

  if (!isOpen) return null;

  const isConfirmed =
    confirmInput.trim().toLowerCase() === projectId.toLowerCase() ||
    confirmInput.trim().toUpperCase() === 'SIFIRLA';

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.8)',
        backdropFilter: 'blur(6px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
    >
      <div
        className="card"
        style={{
          width: '90%',
          maxWidth: '520px',
          borderColor: 'var(--accent-rose)',
          boxShadow: '0 0 30px rgba(244, 63, 94, 0.3)',
        }}
      >
        <div className="card-title" style={{ color: 'var(--accent-rose)', borderBottomColor: 'rgba(244, 63, 94, 0.3)' }}>
          <span>⚠️ GÜVENLİK UYARISI: Veritabanı Sıfırlama</span>
        </div>

        <div style={{ fontSize: '0.9rem', color: 'var(--text-primary)', marginBottom: '1rem', lineHeight: 1.6 }}>
          <p style={{ marginBottom: '0.75rem' }}>
            <strong>"{projectName || projectId}"</strong> projesine ait mevcut veritabanı (SQLite & Qdrant) ve üretilmiş <strong>.jsonl</strong> veri setleri tamamen silinecektir!
          </p>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
            Bu işlem geri alınamaz. Onaylamak için aşağıdaki alana <strong>SIFIRLA</strong> veya proje ID'si olan <code>{projectId}</code> yazın:
          </p>
        </div>

        <div className="form-group" style={{ marginBottom: '1.25rem' }}>
          <input
            type="text"
            className="form-control"
            style={{ borderColor: 'var(--accent-rose)', color: 'var(--accent-rose)', fontWeight: 600 }}
            placeholder={`Onay için '${projectId}' veya 'SIFIRLA' yazın`}
            value={confirmInput}
            onChange={(e) => setConfirmInput(e.target.value)}
          />
        </div>

        <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
          <button className="btn btn-secondary" onClick={onCancel}>
            İptal Et
          </button>

          <button
            className={`btn btn-danger ${!isConfirmed ? 'btn-disabled' : ''}`}
            disabled={!isConfirmed}
            onClick={() => {
              if (isConfirmed) {
                onConfirm();
                setConfirmInput('');
              }
            }}
          >
            🔥 Verileri Sıfırla ve Başlat
          </button>
        </div>
      </div>
    </div>
  );
};
