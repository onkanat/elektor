import React, { useState, useEffect } from 'react';

interface QuickHelpModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const QuickHelpModal: React.FC<QuickHelpModalProps> = ({ isOpen, onClose }) => {
  const [readmeContent, setReadmeContent] = useState<string>('');
  const [isLoading, setIsLoading] = useState<boolean>(true);

  useEffect(() => {
    if (isOpen) {
      setIsLoading(true);
      fetch('/api/readme')
        .then((res) => res.json())
        .then((data) => {
          setReadmeContent(data.content || '# Doküman yüklenemedi.');
          setIsLoading(false);
        })
        .catch((err) => {
          console.error('Error fetching README:', err);
          setReadmeContent('# Doküman yüklenirken hata oluştu.');
          setIsLoading(false);
        });
    }
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal-card"
        style={{
          maxWidth: '900px',
          width: '92%',
          maxHeight: '85vh',
          display: 'flex',
          flexDirection: 'column',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '1rem',
            borderBottom: '1px solid var(--border-color)',
            paddingBottom: '0.75rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ fontSize: '1.4rem' }}>❓</span>
            <h3 style={{ margin: 0, fontSize: '1.15rem', color: 'var(--text-primary)' }}>
              Hızlı Yardım & Kullanım Dokümantasyonu (README.md)
            </h3>
          </div>
          <button className="btn btn-secondary" style={{ padding: '0.2rem 0.6rem' }} onClick={onClose}>
            ✕ Kapat
          </button>
        </div>

        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            background: 'var(--bg-primary)',
            padding: '1.25rem',
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--border-color)',
            fontSize: '0.88rem',
            lineHeight: 1.6,
            color: 'var(--text-primary)',
          }}
        >
          {isLoading ? (
            <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-secondary)' }}>
              Doküman yükleniyor... ⏳
            </div>
          ) : (
            <div className="markdown-body" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
              {readmeContent}
            </div>
          )}
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '1rem' }}>
          <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
            💡 <em>Not: Bu alanda şimdilik projenin ana README.md rehberi gösterilmektedir.</em>
          </span>
          <button className="btn btn-primary" onClick={onClose}>
            Anladım
          </button>
        </div>
      </div>
    </div>
  );
};
