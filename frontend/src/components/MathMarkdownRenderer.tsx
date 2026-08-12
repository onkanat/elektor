import React from 'react';
import katex from 'katex';

interface MathMarkdownRendererProps {
  content: string;
  rawMode?: boolean;
  style?: React.CSSProperties;
}

export const MathMarkdownRenderer: React.FC<MathMarkdownRendererProps> = ({
  content,
  rawMode = false,
  style,
}) => {
  if (!content) return null;

  // Raw mode: Show raw unrendered text for error debugging
  if (rawMode) {
    return (
      <pre
        style={{
          backgroundColor: '#090d16',
          border: '1px solid #1e293b',
          borderRadius: '0.4rem',
          padding: '0.75rem',
          color: '#e2e8f0',
          fontFamily: 'Consolas, Monaco, monospace',
          fontSize: '0.8rem',
          overflowX: 'auto',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          ...style,
        }}
      >
        <code>{content}</code>
      </pre>
    );
  }

  // Safe KaTeX renderer helper
  const renderKaTeXHTML = (mathStr: string, displayMode: boolean): string => {
    try {
      const cleanMath = mathStr
        .replace(/^(\$\$|\\\[|\$|\\\()/g, '')
        .replace(/(\$\$|\\\]|\$|\\\))$/g, '')
        .trim();
      return katex.renderToString(cleanMath, {
        displayMode,
        throwOnError: false,
        output: 'htmlAndMathml',
      });
    } catch (e) {
      console.warn('KaTeX render error:', e);
      return `<code class="katex-error">${mathStr}</code>`;
    }
  };

  // Helper to render mixed text and inline KaTeX ($math$ or \(math\))
  const renderInlineMathText = (line: string): React.ReactNode[] => {
    // Regex for inline math: $...$ or \(...\)
    const inlineRegex = /(\$(?:[^\$\\]|\\.)+\$|\\\((?:[^\)]|\\.)+\\\))/g;
    const parts = line.split(inlineRegex);

    return parts.map((part, pIdx) => {
      if (!part) return null;
      if (inlineRegex.test(part)) {
        // Reset regex state
        inlineRegex.lastIndex = 0;
        const html = renderKaTeXHTML(part, false);
        return (
          <span
            key={`inline-math-${pIdx}`}
            dangerouslySetInnerHTML={{ __html: html }}
            style={{ margin: '0 2px' }}
          />
        );
      }
      return <span key={`text-${pIdx}`}>{part}</span>;
    });
  };

  // Process full markdown document
  const lines = content.split('\n');
  const elements: React.ReactNode[] = [];

  let inCodeBlock = false;
  let codeBuffer: string[] = [];
  let inMathBlock = false;
  let mathBuffer: string[] = [];
  let inTableBlock = false;
  let tableRowsBuffer: string[] = [];

  const flushTable = (tableKey: string) => {
    if (tableRowsBuffer.length === 0) return;
    const rows = tableRowsBuffer.filter((r) => r.trim().startsWith('|'));
    if (rows.length === 0) {
      tableRowsBuffer = [];
      return;
    }

    const parseRow = (rowStr: string) =>
      rowStr
        .split('|')
        .slice(1, -1)
        .map((cell) => cell.trim());

    const headerCells = parseRow(rows[0]);
    // Row 1 is divider line |---|---|
    const bodyRows = rows.slice(2).map(parseRow);

    elements.push(
      <div key={tableKey} style={{ overflowX: 'auto', margin: '0.6rem 0' }}>
        <table
          style={{
            width: '100%',
            borderCollapse: 'collapse',
            fontSize: '0.8rem',
            textAlign: 'left',
            border: '1px solid #334155',
            borderRadius: '0.4rem',
            overflow: 'hidden',
          }}
        >
          <thead>
            <tr style={{ backgroundColor: '#1e293b', borderBottom: '2px solid #475569' }}>
              {headerCells.map((th, i) => (
                <th key={`th-${i}`} style={{ padding: '0.5rem 0.75rem', color: '#38bdf8' }}>
                  {renderInlineMathText(th)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {bodyRows.map((row, rIdx) => (
              <tr
                key={`tr-${rIdx}`}
                style={{
                  backgroundColor: rIdx % 2 === 0 ? '#0f172a' : '#1e293b',
                  borderBottom: '1px solid #334155',
                }}
              >
                {row.map((cell, cIdx) => (
                  <td key={`td-${cIdx}`} style={{ padding: '0.45rem 0.75rem', color: '#e2e8f0' }}>
                    {renderInlineMathText(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
    tableRowsBuffer = [];
  };

  lines.forEach((line, idx) => {
    const trimmed = line.trim();

    // 1. Code blocks (```)
    if (trimmed.startsWith('```')) {
      if (inTableBlock) {
        flushTable(`table-${idx}`);
        inTableBlock = false;
      }
      if (inCodeBlock) {
        elements.push(
          <pre
            key={`code-block-${idx}`}
            style={{
              backgroundColor: '#090d16',
              border: '1px solid #334155',
              borderRadius: '0.4rem',
              padding: '0.6rem 0.8rem',
              color: '#34d399',
              fontFamily: 'Consolas, Monaco, monospace',
              fontSize: '0.8rem',
              overflowX: 'auto',
              margin: '0.4rem 0',
            }}
          >
            <code>{codeBuffer.join('\n')}</code>
          </pre>
        );
        codeBuffer = [];
        inCodeBlock = false;
      } else {
        inCodeBlock = true;
      }
      return;
    }

    if (inCodeBlock) {
      codeBuffer.push(line);
      return;
    }

    // 2. Display Math blocks ($$ or \[ or \begin{matrix/equation})
    if (trimmed.startsWith('$$') || trimmed.startsWith('\\[') || trimmed.startsWith('\\begin{')) {
      if (inTableBlock) {
        flushTable(`table-${idx}`);
        inTableBlock = false;
      }

      // Single line block math (e.g. $$e=mc^2$$)
      if (
        (trimmed.startsWith('$$') && trimmed.endsWith('$$') && trimmed.length > 4) ||
        (trimmed.startsWith('\\[') && trimmed.endsWith('\\]') && trimmed.length > 4)
      ) {
        const html = renderKaTeXHTML(trimmed, true);
        elements.push(
          <div
            key={`math-block-${idx}`}
            dangerouslySetInnerHTML={{ __html: html }}
            style={{
              margin: '0.75rem 0',
              padding: '0.5rem',
              backgroundColor: '#0f172a',
              borderRadius: '0.4rem',
              textAlign: 'center',
              border: '1px solid #1e293b',
              overflowX: 'auto',
            }}
          />
        );
        return;
      }

      inMathBlock = true;
      mathBuffer.push(line);
      return;
    }

    if (inMathBlock) {
      mathBuffer.push(line);
      if (trimmed.endsWith('$$') || trimmed.endsWith('\\]') || trimmed.startsWith('\\end{')) {
        const fullMath = mathBuffer.join('\n');
        const html = renderKaTeXHTML(fullMath, true);
        elements.push(
          <div
            key={`math-block-${idx}`}
            dangerouslySetInnerHTML={{ __html: html }}
            style={{
              margin: '0.75rem 0',
              padding: '0.5rem',
              backgroundColor: '#0f172a',
              borderRadius: '0.4rem',
              textAlign: 'center',
              border: '1px solid #1e293b',
              overflowX: 'auto',
            }}
          />
        );
        mathBuffer = [];
        inMathBlock = false;
      }
      return;
    }

    // 3. Markdown Tables (| col1 | col2 |)
    if (trimmed.startsWith('|')) {
      inTableBlock = true;
      tableRowsBuffer.push(line);
      return;
    } else if (inTableBlock) {
      flushTable(`table-${idx}`);
      inTableBlock = false;
    }

    // 4. Headers (#, ##, ###)
    if (trimmed.startsWith('#')) {
      const level = trimmed.match(/^#+/)?.[0].length || 1;
      const titleText = trimmed.replace(/^#+\s*/, '');
      const fontSize = level === 1 ? '1.1rem' : level === 2 ? '0.95rem' : '0.85rem';
      elements.push(
        <div
          key={`header-${idx}`}
          style={{
            fontWeight: 700,
            color: '#38bdf8',
            marginTop: '0.6rem',
            marginBottom: '0.3rem',
            fontSize,
          }}
        >
          {renderInlineMathText(titleText)}
        </div>
      );
      return;
    }

    // 5. Lists (- or *)
    if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
      const itemText = trimmed.replace(/^[-*]\s*/, '');
      elements.push(
        <div
          key={`list-${idx}`}
          style={{
            marginLeft: '1rem',
            fontSize: '0.82rem',
            lineHeight: '1.45',
            color: '#cbd5e1',
            marginBottom: '0.15rem',
          }}
        >
          • {renderInlineMathText(itemText)}
        </div>
      );
      return;
    }

    // 6. Normal paragraph text
    if (trimmed) {
      elements.push(
        <div
          key={`p-${idx}`}
          style={{
            fontSize: '0.82rem',
            lineHeight: '1.5',
            color: '#e2e8f0',
            marginBottom: '0.3rem',
          }}
        >
          {renderInlineMathText(line)}
        </div>
      );
    }
  });

  if (inTableBlock) {
    flushTable(`table-end`);
  }

  return <div style={style}>{elements}</div>;
};
