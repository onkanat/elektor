import React, { useState, useEffect } from 'react';

interface QuickHelpModalProps {
  isOpen: boolean;
  onClose: () => void;
}

/**
 * Lightweight, zero-dependency Markdown to HTML parser for high-speed dark mode rendering.
 */
function parseMarkdownToHtml(markdown: string): string {
  if (!markdown) return '';

  let html = markdown;

  // Escape HTML entities to prevent XSS except intentional formatting
  html = html
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // Fenced Code Blocks (```lang ... ```)
  html = html.replace(/```([\s\S]*?)```/g, (_match, codeContent) => {
    return `<pre><code>${codeContent.trim()}</code></pre>`;
  });

  // Inline code (`code`)
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

  // Images ![alt](url)
  html = html.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<div class="guide-img-container" style="text-align:center; margin:1rem 0;"><img src="$2" alt="$1" style="max-width:100%; border-radius:0.5rem; border:1px solid #334155; box-shadow:0 10px 15px -3px rgba(0,0,0,0.5);" /><div style="font-size:0.75rem; color:#94a3b8; margin-top:0.4rem;">📷 <em>$1</em></div></div>');

  // Headings
  html = html.replace(/^#### (.*$)/gim, '<h4>$1</h4>');
  html = html.replace(/^### (.*$)/gim, '### $1');
  html = html.replace(/^## (.*$)/gim, '## $1');
  html = html.replace(/^# (.*$)/gim, '# $1');

  // Bold & Italic
  html = html.replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>');
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');

  // Horizontal Rules
  html = html.replace(/^---$/gim, '<hr/>');

  // Blockquotes
  html = html.replace(/^&gt; (.*$)/gim, '<blockquote>$1</blockquote>');

  // Markdown Tables
  const lines = html.split('\n');
  const processedLines: string[] = [];
  let inTable = false;

  for (let i = 0; i < lines.length; i++) {
    let line = lines[i].trim();

    if (line.startsWith('|') && line.endsWith('|')) {
      if (line.includes('---')) {
        // Table separator line
        continue;
      }

      const cells = line.split('|').slice(1, -1).map(c => c.trim());
      
      if (!inTable) {
        inTable = true;
        processedLines.push('<table><thead><tr>' + cells.map(c => `<th>${c}</th>`).join('') + '</tr></thead><tbody>');
      } else {
        processedLines.push('<tr>' + cells.map(c => `<td>${c}</td>`).join('') + '</tr>');
      }
    } else {
      if (inTable) {
        inTable = false;
        processedLines.push('</tbody></table>');
      }

      // Convert #, ##, ### after html entity escape
      if (line.startsWith('# ')) {
        line = `<h1>${line.substring(2)}</h1>`;
      } else if (line.startsWith('## ')) {
        line = `<h2>${line.substring(3)}</h2>`;
      } else if (line.startsWith('### ')) {
        line = `<h3>${line.substring(4)}</h3>`;
      } else if (line.startsWith('- ')) {
        line = `<ul><li>${line.substring(2)}</li></ul>`;
      } else if (/^\d+\. /.test(line)) {
        line = `<ol><li>${line.replace(/^\d+\. /, '')}</li></ol>`;
      }

      processedLines.push(line);
    }
  }

  if (inTable) {
    processedLines.push('</tbody></table>');
  }

  html = processedLines.join('\n');

  // Clean up nested ul/ol tags
  html = html.replace(/<\/ul>\n<ul>/g, '');
  html = html.replace(/<\/ol>\n<ol>/g, '');

  // Line breaks
  html = html.replace(/\n\n/g, '<br/><br/>');

  return html;
}

export const QuickHelpModal: React.FC<QuickHelpModalProps> = ({ isOpen, onClose }) => {
  const [guideContent, setGuideContent] = useState<string>('');
  const [isLoading, setIsLoading] = useState<boolean>(true);

  useEffect(() => {
    if (isOpen) {
      setIsLoading(true);
      fetch('/api/readme')
        .then((res) => res.json())
        .then((data) => {
          setGuideContent(data.content || '# Doküman yüklenemedi.');
          setIsLoading(false);
        })
        .catch((err) => {
          console.error('Error fetching User Guide:', err);
          setGuideContent('# Doküman yüklenirken hata oluştu.');
          setIsLoading(false);
        });
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const parsedHtml = parseMarkdownToHtml(guideContent);

  return (
    <div className="modal-backdrop" onClick={onClose} style={{
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
      backgroundColor: 'rgba(0, 0, 0, 0.8)', backdropFilter: 'blur(5px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1100
    }}>
      <div
        className="modal-card"
        style={{
          maxWidth: '960px',
          width: '94%',
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column',
          backgroundColor: '#0f172a',
          border: '1px solid #334155',
          borderRadius: '0.75rem',
          padding: '1.25rem',
          boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.7)'
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '1rem',
            borderBottom: '1px solid #1e293b',
            paddingBottom: '0.75rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <span style={{ fontSize: '1.5rem' }}>📖</span>
            <div>
              <h3 style={{ margin: 0, fontSize: '1.15rem', color: '#f8fafc', fontWeight: 700 }}>
                Platform Detaylı Kullanım Kılavuzu & Rehberi
              </h3>
              <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Bölüm A, B, C, Proje Gezgini ve HF/Bulut GPU Modüllerinin Detaylı Anlatımı</span>
            </div>
          </div>
          <button className="btn btn-secondary" style={{ padding: '0.25rem 0.6rem', fontSize: '0.9rem' }} onClick={onClose}>
            ✕ Kapat
          </button>
        </div>

        {/* Content Body with Markdown HTML Renderer */}
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            background: '#020617',
            padding: '1.5rem',
            borderRadius: '0.5rem',
            border: '1px solid #1e293b',
            fontSize: '0.9rem',
            lineHeight: 1.65,
            color: '#e2e8f0',
          }}
        >
          {isLoading ? (
            <div style={{ textAlign: 'center', padding: '4rem', color: '#94a3b8' }}>
              Kullanım kılavuzu yükleniyor... ⏳
            </div>
          ) : (
            <div
              className="rich-markdown-body"
              dangerouslySetInnerHTML={{ __html: parsedHtml }}
            />
          )}
        </div>

        {/* Footer */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '1rem', borderTop: '1px solid #1e293b', paddingTop: '0.75rem' }}>
          <span style={{ fontSize: '0.78rem', color: '#94a3b8' }}>
            💡 <em>Not: Bu kılavuz `USER_GUIDE.md` dosyasından canlı render edilmektedir.</em>
          </span>
          <button className="btn btn-primary" onClick={onClose} style={{ padding: '0.4rem 1rem', fontWeight: 600 }}>
            Anladım & Kapat
          </button>
        </div>
      </div>
    </div>
  );
};
