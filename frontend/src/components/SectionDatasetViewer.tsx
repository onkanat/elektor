import { useState, useEffect, useMemo } from 'react';
import type { DatasetItem, SQLiteTableInfo, QdrantInfo } from '../types';

interface SectionDatasetViewerProps {
  activeProjectId?: string;
  activeProjectName?: string;
  activeDatasetName?: string;
}

export const SectionDatasetViewer: React.FC<SectionDatasetViewerProps> = ({
  activeProjectId = 'sdr_engineers',
  activeProjectName,
  activeDatasetName = 'rp2040_datasheet',
}) => {
  const [subTab, setSubTab] = useState<'jsonl' | 'sqlite' | 'qdrant'>('jsonl');

  // Filter Mode: 'active' (show active project files) vs 'all' (show all projects)
  const [projectFilterMode, setProjectFilterMode] = useState<'active' | 'all'>('active');

  // JSONL Dataset State
  const [datasets, setDatasets] = useState<DatasetItem[]>([]);
  const [selectedFile, setSelectedFile] = useState<string>('');
  const [datasetRecords, setDatasetRecords] = useState<any[]>([]);
  const [jsonlPage, setJsonlPage] = useState<number>(1);
  const [totalJsonlMatches, setTotalJsonlMatches] = useState<number>(0);
  const [jsonlSearch, setJsonlSearch] = useState<string>('');
  const [isLoadingJsonl, setIsLoadingJsonl] = useState<boolean>(false);

  // SQLite State
  const [sqliteTables, setSqliteTables] = useState<SQLiteTableInfo[]>([]);
  const [selectedTable, setSelectedTable] = useState<string>('articles');
  const [sqliteRows, setSqliteRows] = useState<any[]>([]);
  const [sqlitePage, setSqlitePage] = useState<number>(1);
  const [totalSqliteRecords, setTotalSqliteRecords] = useState<number>(0);
  const [sqliteSearch, setSqliteSearch] = useState<string>('');
  const [isLoadingSqlite, setIsLoadingSqlite] = useState<boolean>(false);

  // Qdrant State
  const [qdrantInfo, setQdrantInfo] = useState<QdrantInfo | null>(null);
  const [qdrantQuery, setQdrantQuery] = useState<string>('software defined radio');
  const [qdrantResults, setQdrantResults] = useState<any[]>([]);
  const [isSearchingQdrant, setIsSearchingQdrant] = useState<boolean>(false);

  // Robust project matching logic
  const isProjectMatch = (relativePath: string): boolean => {
    const folder = relativePath.split('/')[0].toLowerCase();
    const pid = (activeProjectId || '').toLowerCase();
    const dname = (activeDatasetName || '').toLowerCase();

    if (!folder) return false;
    if (folder === pid || folder === dname) return true;

    // Extract core tokens (e.g., "rp2040" from "test_rp2040" or "rp2040_datasheet")
    const cleanFolder = folder.replace(/^test_|_datasheet$|_project$/g, '');
    const cleanPid = pid.replace(/^test_|_datasheet$|_project$/g, '');
    const cleanDname = dname.replace(/^test_|_datasheet$|_project$/g, '');

    if (cleanFolder.length >= 3 && cleanPid.length >= 3 && (cleanPid.includes(cleanFolder) || cleanFolder.includes(cleanPid))) {
      return true;
    }
    if (cleanFolder.length >= 3 && cleanDname.length >= 3 && (cleanDname.includes(cleanFolder) || cleanFolder.includes(cleanDname))) {
      return true;
    }
    return false;
  };

  const [selectedRowModal, setSelectedRowModal] = useState<any | null>(null);

  // Fetch JSONL dataset list on mount / project change
  useEffect(() => {
    fetch('/api/datasets')
      .then((res) => res.json())
      .then((data) => {
        if (data.datasets && data.datasets.length > 0) {
          setDatasets(data.datasets);
          const activeList = data.datasets.filter((d: DatasetItem) => isProjectMatch(d.relative_path));
          if (activeList.length > 0) {
            setSelectedFile(activeList[0].relative_path);
          } else {
            setSelectedFile(data.datasets[0].relative_path);
          }
        }
      })
      .catch((err) => console.error('Error fetching datasets:', err));
  }, [activeProjectId, activeDatasetName]);

  // Filter datasets based on projectFilterMode
  const filteredDatasets = useMemo(() => {
    return datasets.filter((d) => {
      if (projectFilterMode === 'all') return true;
      return isProjectMatch(d.relative_path);
    });
  }, [datasets, projectFilterMode, activeProjectId, activeDatasetName]);

  // Handle switching filter modes
  const handleSwitchFilterMode = (mode: 'active' | 'all') => {
    setProjectFilterMode(mode);
    setJsonlPage(1);
    if (mode === 'active') {
      const activeList = datasets.filter((d) => isProjectMatch(d.relative_path));
      if (activeList.length > 0) {
        setSelectedFile(activeList[0].relative_path);
      }
    } else if (mode === 'all' && datasets.length > 0) {
      const exists = filteredDatasets.some((d) => d.relative_path === selectedFile);
      if (!exists) {
        setSelectedFile(datasets[0].relative_path);
      }
    }
  };

  // Fetch JSONL records when selectedFile, page, or search changes
  useEffect(() => {
    if (!selectedFile) return;
    setIsLoadingJsonl(true);
    fetch(`/api/datasets/preview?file_path=${encodeURIComponent(selectedFile)}&page=${jsonlPage}&limit=10&search=${encodeURIComponent(jsonlSearch)}`)
      .then((res) => res.json())
      .then((data) => {
        setDatasetRecords(data.items || []);
        setTotalJsonlMatches(data.total_matches || 0);
        setIsLoadingJsonl(false);
      })
      .catch((err) => {
        console.error('Error fetching dataset records:', err);
        setIsLoadingJsonl(false);
      });
  }, [selectedFile, jsonlPage, jsonlSearch]);

  // Fetch SQLite tables on subTab switch or project change
  useEffect(() => {
    if (subTab === 'sqlite') {
      setIsLoadingSqlite(true);
      fetch('/api/db/sqlite/tables')
        .then((res) => res.json())
        .then((data) => {
          if (data.tables) {
            setSqliteTables(data.tables);
            if (data.tables.length > 0) {
              const exists = data.tables.some((t: SQLiteTableInfo) => t.name === selectedTable);
              if (!exists) {
                setSelectedTable(data.tables[0].name);
              }
            }
          }
          setIsLoadingSqlite(false);
        })
        .catch((err) => {
          console.error('Error fetching SQLite tables:', err);
          setIsLoadingSqlite(false);
        });
    }
  }, [subTab, activeProjectId, activeDatasetName]);

  // Fetch SQLite rows
  useEffect(() => {
    if (subTab !== 'sqlite' || !selectedTable) return;
    setIsLoadingSqlite(true);
    fetch(`/api/db/sqlite/query?table=${encodeURIComponent(selectedTable)}&page=${sqlitePage}&limit=10&search=${encodeURIComponent(sqliteSearch)}`)
      .then((res) => res.json())
      .then((data) => {
        setSqliteRows(data.records || []);
        setTotalSqliteRecords(data.total_records || 0);
        setIsLoadingSqlite(false);
      })
      .catch((err) => {
        console.error('Error fetching SQLite rows:', err);
        setIsLoadingSqlite(false);
      });
  }, [selectedTable, sqlitePage, sqliteSearch, subTab, activeProjectId, activeDatasetName]);

  // Fetch Qdrant Info on subTab switch or project change
  useEffect(() => {
    if (subTab === 'qdrant') {
      fetch('/api/db/qdrant/info')
        .then((res) => res.json())
        .then((data) => setQdrantInfo(data))
        .catch((err) => console.error('Error fetching Qdrant info:', err));
    }
  }, [subTab, activeProjectId, activeDatasetName]);

  const handleQdrantSearch = async () => {
    if (!qdrantQuery.trim()) return;
    setIsSearchingQdrant(true);
    try {
      const res = await fetch('/api/db/qdrant/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: qdrantQuery, top_k: 5 }),
      });
      const data = await res.json();
      setQdrantResults(data.results || []);
    } catch (e) {
      console.error('Error searching Qdrant:', e);
    } finally {
      setIsSearchingQdrant(false);
    }
  };

  const selectedFolder = selectedFile ? selectedFile.split('/')[0] : '';

  return (
    <div className="card">
      <div className="card-title" style={{ justifyContent: 'space-between' }}>
        <span>📊 Bölüm B: Dataset & Veritabanı Görüntüleyici</span>
        
        <div className="nav-tabs" style={{ background: 'var(--bg-primary)' }}>
          <button
            className={`tab-btn ${subTab === 'jsonl' ? 'active' : ''}`}
            onClick={() => setSubTab('jsonl')}
          >
            📄 JSONL Veri Setleri
          </button>
          <button
            className={`tab-btn ${subTab === 'sqlite' ? 'active' : ''}`}
            onClick={() => setSubTab('sqlite')}
          >
            🗄️ Lite SQLite Sorgulayıcı
          </button>
          <button
            className={`tab-btn ${subTab === 'qdrant' ? 'active' : ''}`}
            onClick={() => setSubTab('qdrant')}
          >
            🔍 Lite Qdrant Vektör Arama
          </button>
        </div>
      </div>

      {/* TAB 1: JSONL DATASETS */}
      {subTab === 'jsonl' && (
        <div>
          {/* Proje Filtre Barı & İndikatör */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'var(--bg-primary)', padding: '0.6rem 1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)', marginBottom: '1rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)' }}>Proje Filtresi:</span>
              <button
                className={`tab-btn ${projectFilterMode === 'active' ? 'active' : ''}`}
                style={{ padding: '0.25rem 0.75rem', fontSize: '0.78rem' }}
                onClick={() => handleSwitchFilterMode('active')}
              >
                📌 Aktif Proje ({activeProjectName || activeProjectId})
              </button>
              <button
                className={`tab-btn ${projectFilterMode === 'all' ? 'active' : ''}`}
                style={{ padding: '0.25rem 0.75rem', fontSize: '0.78rem' }}
                onClick={() => handleSwitchFilterMode('all')}
              >
                🌐 Tüm Projeler ({datasets.length} Dosya)
              </button>
            </div>

            <div className="badge online" style={{ fontSize: '0.75rem' }}>
              Klasör: exports/<code>{selectedFolder || 'seçilmedi'}</code>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '1rem', marginBottom: '1.25rem', alignItems: 'center' }}>
            <div style={{ flex: 1.5 }}>
              <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Veri Seti Dosyası Seçin</label>
              <select
                className="form-control"
                value={selectedFile}
                onChange={(e) => {
                  setSelectedFile(e.target.value);
                  setJsonlPage(1);
                }}
              >
                {filteredDatasets.length === 0 ? (
                  <option value="">(Bu filtre için veri seti dosyası bulunamadı)</option>
                ) : (
                  filteredDatasets.map((d: DatasetItem) => {
                    const projFolder = d.relative_path.split('/')[0];
                    const isCurrentProj = isProjectMatch(d.relative_path);
                    return (
                      <option key={d.relative_path} value={d.relative_path}>
                        {isCurrentProj ? '★' : '📂'} [{projFolder}] ➔ {d.filename} ({d.sample_count} örnek, {(d.size_bytes / 1024).toFixed(1)} KB)
                      </option>
                    );
                  })
                )}
              </select>
            </div>

            <div style={{ flex: 1 }}>
              <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Arama Yapın</label>
              <input
                type="text"
                className="form-control"
                placeholder="Veri seti içeriğinde ara..."
                value={jsonlSearch}
                onChange={(e) => {
                  setJsonlSearch(e.target.value);
                  setJsonlPage(1);
                }}
              />
            </div>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.75rem', fontSize: '0.85rem' }}>
            <span>Toplam Eşleşen Kayıt: <strong>{totalJsonlMatches}</strong></span>
            <div>
              <button
                className="btn btn-secondary"
                style={{ padding: '0.2rem 0.6rem', marginRight: '0.5rem' }}
                disabled={jsonlPage <= 1}
                onClick={() => setJsonlPage(jsonlPage - 1)}
              >
                ◀ Önceki
              </button>
              <span>Sayfa {jsonlPage}</span>
              <button
                className="btn btn-secondary"
                style={{ padding: '0.2rem 0.6rem', marginLeft: '0.5rem' }}
                disabled={datasetRecords.length < 10}
                onClick={() => setJsonlPage(jsonlPage + 1)}
              >
                Sonraki ▶
              </button>
            </div>
          </div>

          {isLoadingJsonl ? (
            <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)' }}>Yükleniyor...</div>
          ) : datasetRecords.length === 0 ? (
            <div style={{ padding: '2rem', textAlign: 'center', color: '#64748b' }}>
              Seçilen filtre veya dosya için veri seti kaydı bulunamadı.
            </div>
          ) : (
            <div>
              {datasetRecords.map((item: any, idx: number) => (
                <div key={idx} className="json-card">
                  {/* If SFT format */}
                  {item.instruction && (
                    <div>
                      <div style={{ color: '#38bdf8', fontWeight: 600, marginBottom: '0.3rem' }}>
                        Instruction (Soru): {item.instruction}
                      </div>
                      <div style={{ color: '#34d399', whiteSpace: 'pre-wrap' }}>
                        Response (Cevap): {item.output || item.response}
                      </div>
                    </div>
                  )}

                  {/* If DPO format */}
                  {item.prompt && (
                    <div>
                      <div style={{ color: '#38bdf8', fontWeight: 600, marginBottom: '0.3rem' }}>
                        Prompt: {item.prompt}
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginTop: '0.5rem' }}>
                        <div style={{ background: 'rgba(16, 185, 129, 0.1)', padding: '0.5rem', borderRadius: '4px', border: '1px solid rgba(16, 185, 129, 0.3)' }}>
                          <span style={{ color: '#34d399', fontWeight: 600 }}>✓ Chosen (Tercih Edilen):</span>
                          <div style={{ color: '#e2e8f0', marginTop: '0.2rem' }}>{item.chosen}</div>
                        </div>
                        <div style={{ background: 'rgba(244, 63, 94, 0.1)', padding: '0.5rem', borderRadius: '4px', border: '1px solid rgba(244, 63, 94, 0.3)' }}>
                          <span style={{ color: '#fb7185', fontWeight: 600 }}>✗ Rejected (Reddedilen):</span>
                          <div style={{ color: '#cbd5e1', marginTop: '0.2rem' }}>{item.rejected}</div>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Generic JSON display fallback */}
                  {!item.instruction && !item.prompt && (
                    <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                      {JSON.stringify(item, null, 2)}
                    </pre>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* TAB 2: LITE SQLITE QUERY VIEWER */}
      {subTab === 'sqlite' && (
        <div>
          <div style={{ display: 'flex', gap: '1rem', marginBottom: '1.25rem', alignItems: 'center' }}>
            <div style={{ width: '220px' }}>
              <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Tablo Seçin</label>
              <select
                className="form-control"
                value={selectedTable}
                onChange={(e) => {
                  setSelectedTable(e.target.value);
                  setSqlitePage(1);
                }}
              >
                {sqliteTables.map((t: SQLiteTableInfo) => (
                  <option key={t.name} value={t.name}>
                    {t.name} ({t.count} kayıt)
                  </option>
                ))}
              </select>
            </div>

            <div style={{ flex: 1 }}>
              <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Filtrele / Ara (Başlık veya Metin)</label>
              <input
                type="text"
                className="form-control"
                placeholder="SQLite tablosunda filtrele..."
                value={sqliteSearch}
                onChange={(e) => {
                  setSqliteSearch(e.target.value);
                  setSqlitePage(1);
                }}
              />
            </div>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.75rem', fontSize: '0.85rem' }}>
            <span>Toplam Kayıt: <strong>{totalSqliteRecords}</strong></span>
            <div>
              <button
                className="btn btn-secondary"
                style={{ padding: '0.2rem 0.6rem', marginRight: '0.5rem' }}
                disabled={sqlitePage <= 1}
                onClick={() => setSqlitePage(sqlitePage - 1)}
              >
                ◀ Önceki
              </button>
              <span>Sayfa {sqlitePage}</span>
              <button
                className="btn btn-secondary"
                style={{ padding: '0.2rem 0.6rem', marginLeft: '0.5rem' }}
                disabled={sqliteRows.length < 10}
                onClick={() => setSqlitePage(sqlitePage + 1)}
              >
                Sonraki ▶
              </button>
            </div>
          </div>

          {isLoadingSqlite ? (
            <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)' }}>SQLite yükleniyor...</div>
          ) : sqliteRows.length === 0 ? (
            <div style={{ padding: '2rem', textAlign: 'center', color: '#64748b' }}>SQLite kaydı bulunamadı.</div>
          ) : (
            <div className="table-responsive">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Başlık / Bilgi</th>
                    <th>Metin & İçerik Önizlemesi</th>
                    <th style={{ width: '110px' }}>İşlem</th>
                  </tr>
                </thead>
                <tbody>
                  {sqliteRows.map((row: any, i: number) => {
                    const textPreview = row.extracted_text_preview || row.extracted_text || row.summary_preview || row.summary || row.tr_sft_qa_preview || row.sft_qa_preview || row.zoom_snippet || '-';
                    const titleStr = row.title || row.turkish_title || row.filename || `Kayıt #${row.article_id || row.id}`;
                    const subtitle = row.year ? `Yıl: ${row.year}` : (row.article_id ? `Article ID: ${row.article_id}` : (row.file_path ? `Path: ${row.file_path}` : ''));

                    return (
                      <tr key={i} style={{ cursor: 'pointer' }} onClick={() => setSelectedRowModal(row)}>
                        <td style={{ fontWeight: 600, color: 'var(--accent-cyan)' }}>{row.id}</td>
                        <td style={{ fontWeight: 500, minWidth: '180px' }}>
                          <div>{titleStr}</div>
                          {subtitle && <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>{subtitle}</div>}
                        </td>
                        <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', maxWidth: '500px', whiteSpace: 'normal', wordBreak: 'break-word', lineHeight: 1.4 }}>
                          {textPreview}
                        </td>
                        <td>
                          <button
                            className="btn btn-secondary"
                            style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem' }}
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedRowModal(row);
                            }}
                          >
                            🔍 Detay / Metin
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Full Extracted Text & Row Details Modal */}
          {selectedRowModal && (
            <div className="modal-backdrop" onClick={() => setSelectedRowModal(null)}>
              <div className="modal-card" style={{ maxWidth: '800px', width: '90%' }} onClick={(e) => e.stopPropagation()}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem' }}>
                  <h3 style={{ margin: 0, fontSize: '1.1rem', color: 'var(--text-primary)' }}>
                    📖 Metin Detayı: {selectedRowModal.title || selectedRowModal.filename || `ID #${selectedRowModal.id}`}
                  </h3>
                  <button className="btn btn-secondary" style={{ padding: '0.2rem 0.6rem' }} onClick={() => setSelectedRowModal(null)}>✕ Kapat</button>
                </div>

                <div style={{ maxHeight: '60vh', overflowY: 'auto', background: 'var(--bg-primary)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)', fontSize: '0.85rem', lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: 'var(--text-primary)' }}>
                  {selectedRowModal.extracted_text || selectedRowModal.summary || selectedRowModal.tr_sft_qa || selectedRowModal.sft_qa || JSON.stringify(selectedRowModal, null, 2)}
                </div>

                <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1rem' }}>
                  <button className="btn btn-primary" onClick={() => setSelectedRowModal(null)}>Tamam</button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB 3: LITE QDRANT SEARCH */}
      {subTab === 'qdrant' && (
        <div>
          <div style={{ display: 'flex', gap: '1rem', marginBottom: '1.25rem', alignItems: 'center' }}>
            <div style={{ flex: 1 }}>
              <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Semantik / RAG Vektör Araması Yapın</label>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <input
                  type="text"
                  className="form-control"
                  placeholder="Örn: ESP32 bluetooth low energy..."
                  value={qdrantQuery}
                  onChange={(e) => setQdrantQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleQdrantSearch()}
                />
                <button className="btn btn-primary" onClick={handleQdrantSearch} disabled={isSearchingQdrant}>
                  {isSearchingQdrant ? 'Aranıyor...' : '🔍 Vektör Ara'}
                </button>
              </div>
            </div>

            <div className="badge online" style={{ height: 'fit-content', marginTop: '1.2rem' }}>
              Koleksiyon: {qdrantInfo?.collection || 'sdr_articles'} ({qdrantInfo?.points_count || 0} Vektör Chunk)
            </div>
          </div>

          {qdrantResults.length === 0 ? (
            <div style={{ padding: '2rem', textAlign: 'center', color: '#64748b' }}>
              Qdrant veritabanında arama yapmak için bir sorgu girip "Vektör Ara" butonuna basın.
            </div>
          ) : (
            <div>
              {qdrantResults.map((match: any, i: number) => (
                <div key={i} className="json-card" style={{ borderLeft: '4px solid var(--accent-blue)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                    <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                      [{i + 1}] {match.title} ({match.year})
                    </span>
                    <span className="badge online" style={{ fontSize: '0.75rem' }}>
                      Skor: {(match.score * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                    {match.text}
                  </div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.5rem' }}>
                    Dosya: {match.filename}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
