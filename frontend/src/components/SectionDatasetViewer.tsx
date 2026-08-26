import { useState, useEffect, useMemo } from 'react';
import type { DatasetItem, SQLiteTableInfo, QdrantInfo } from '../types';
import { MathMarkdownRenderer } from './MathMarkdownRenderer';

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
  const [subTab, setSubTab] = useState<'jsonl' | 'sqlite' | 'qdrant' | 'catalog'>('jsonl');
  const [catalogData, setCatalogData] = useState<{ exists: boolean; content: string; filename?: string; size_bytes?: number } | null>(null);
  const [isLoadingCatalog, setIsLoadingCatalog] = useState<boolean>(false);

  // Render mode: KaTeX Math vs Raw Text
  const [renderMathMode, setRenderMathMode] = useState<boolean>(true);

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

  const handleRateItem = async (articleId: number, rating: number) => {
    try {
      const res = await fetch('/api/dataset/rate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ article_id: articleId, rating }),
      });
      if (res.ok) {
        setSqliteRows((prev) =>
          prev.map((r) => (r.article_id === articleId || r.id === articleId ? { ...r, human_rating: rating } : r))
        );
        if (selectedRowModal && (selectedRowModal.article_id === articleId || selectedRowModal.id === articleId)) {
          setSelectedRowModal((prev: any) => ({ ...prev, human_rating: rating }));
        }
      }
    } catch (e) {
      console.error('Failed to rate item:', e);
    }
  };

  const handleToggleExcludeItem = async (articleId: number, currentExcludeState: boolean) => {
    const newExclude = !currentExcludeState;
    try {
      const res = await fetch('/api/dataset/exclude', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ article_id: articleId, exclude: newExclude }),
      });
      if (res.ok) {
        setSqliteRows((prev) =>
          prev.map((r) => (r.article_id === articleId || r.id === articleId ? { ...r, is_excluded: newExclude ? 1 : 0 } : r))
        );
        if (selectedRowModal && (selectedRowModal.article_id === articleId || selectedRowModal.id === articleId)) {
          setSelectedRowModal((prev: any) => ({ ...prev, is_excluded: newExclude ? 1 : 0 }));
        }
      }
    } catch (e) {
      console.error('Failed to toggle exclude item:', e);
    }
  };

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

  // Fetch JSONL dataset list on mount / project change / manual refresh
  const fetchDatasets = () => {
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
  };

  useEffect(() => {
    fetchDatasets();
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

  // Fetch Multimodal Markdown Catalog
  const fetchCatalog = () => {
    setIsLoadingCatalog(true);
    fetch(`/api/dataset/catalog?project_id=${encodeURIComponent(activeProjectId)}`)
      .then((res) => res.json())
      .then((data) => {
        setCatalogData(data);
        setIsLoadingCatalog(false);
      })
      .catch((err) => {
        console.error('Error fetching catalog:', err);
        setIsLoadingCatalog(false);
      });
  };

  useEffect(() => {
    if (subTab === 'catalog') {
      fetchCatalog();
    }
  }, [subTab, activeProjectId]);

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
          <button
            className={`tab-btn ${subTab === 'catalog' ? 'active' : ''}`}
            onClick={() => setSubTab('catalog')}
            style={{ borderColor: subTab === 'catalog' ? '#a855f7' : undefined }}
          >
            🖼️ Multimodal Katalog (.md)
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

            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              <button
                className="btn btn-secondary"
                style={{ padding: '0.25rem 0.6rem', fontSize: '0.75rem' }}
                onClick={() => fetchDatasets()}
                title="Veri seti listesini yeniden tara"
              >
                🔄 Listeyi Yenile
              </button>
              <div className="badge online" style={{ fontSize: '0.75rem' }}>
                Klasör: exports/<code>{selectedFolder || 'seçilmedi'}</code>
              </div>
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
                      {item.input && (
                        <div style={{ background: 'rgba(56, 189, 248, 0.08)', padding: '0.4rem 0.6rem', borderRadius: '4px', border: '1px solid rgba(56, 189, 248, 0.2)', marginBottom: '0.4rem', fontSize: '0.78rem', color: '#93c5fd' }}>
                          <strong>Bağlam / Etiketler:</strong> {item.input}
                        </div>
                      )}
                      <div style={{ color: '#34d399', whiteSpace: 'pre-wrap' }}>
                        Response (Cevap): {item.output || item.response}
                      </div>
                    </div>
                  )}

                  {/* If DPO format */}
                  {item.prompt && (
                    <div>
                      {item.metadata && (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', marginBottom: '0.4rem', fontSize: '0.75rem', alignItems: 'center' }}>
                          {item.metadata.source && (
                            <span className="badge" style={{ background: 'rgba(148, 163, 184, 0.15)', color: '#cbd5e1', border: '1px solid rgba(148, 163, 184, 0.3)' }}>
                              📦 {item.metadata.source}
                            </span>
                          )}
                          {item.metadata.chosen_score !== undefined && (
                            <span className="badge online" style={{ fontSize: '0.72rem' }}>
                              🏆 Chosen Skor: +{item.metadata.chosen_score} {item.metadata.chosen_is_accepted ? '(Kabul Edildi)' : ''}
                            </span>
                          )}
                          {item.metadata.rejected_score !== undefined && (
                            <span className="badge warning" style={{ fontSize: '0.72rem' }}>
                              ⚠️ Rejected Skor: {item.metadata.rejected_score}
                            </span>
                          )}
                          {item.metadata.quality_status && (
                            <span className="badge" style={{ background: 'rgba(99, 102, 241, 0.15)', color: '#818cf8' }}>
                              {item.metadata.quality_status}
                            </span>
                          )}
                        </div>
                      )}
                      <div style={{ color: '#38bdf8', fontWeight: 600, marginBottom: '0.3rem' }}>
                        Prompt: {item.prompt}
                      </div>
                      {item.input && (
                        <div style={{ background: 'rgba(56, 189, 248, 0.08)', padding: '0.4rem 0.6rem', borderRadius: '4px', border: '1px solid rgba(56, 189, 248, 0.2)', marginBottom: '0.4rem', fontSize: '0.78rem', color: '#93c5fd' }}>
                          <strong>Girdi / Detay:</strong> {item.input}
                        </div>
                      )}
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

                    let tagsList: string[] = [];
                    if (row.tags) {
                      try {
                        tagsList = typeof row.tags === 'string' ? JSON.parse(row.tags) : row.tags;
                      } catch {
                        tagsList = String(row.tags).split(',').map((s: string) => s.trim()).filter(Boolean);
                      }
                    }

                    return (
                      <tr key={i} style={{ cursor: 'pointer' }} onClick={() => setSelectedRowModal(row)}>
                        <td style={{ fontWeight: 600, color: 'var(--accent-cyan)' }}>{row.id}</td>
                        <td style={{ fontWeight: 500, minWidth: '220px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap' }}>
                            <span>{titleStr}</span>
                            {row.source_type && (
                              <span className="badge" style={{ fontSize: '0.68rem', background: 'rgba(99, 102, 241, 0.15)', color: '#818cf8', padding: '0.05rem 0.35rem' }}>
                                {row.source_type}
                              </span>
                            )}
                          </div>
                          
                          {/* Badges Bar (Tags, Score, Accepted, Vetoed) */}
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem', marginTop: '0.3rem', alignItems: 'center' }}>
                            {row.vote_score !== undefined && row.vote_score !== null && row.vote_score !== 0 && (
                              <span style={{ background: row.vote_score > 0 ? 'rgba(16, 185, 129, 0.15)' : 'rgba(244, 63, 94, 0.15)', color: row.vote_score > 0 ? '#34d399' : '#fb7185', padding: '0.08rem 0.35rem', borderRadius: '4px', fontSize: '0.68rem', fontWeight: 600 }}>
                                ▲ {row.vote_score} oy
                              </span>
                            )}
                            {row.is_accepted === 1 && (
                              <span style={{ background: 'rgba(16, 185, 129, 0.2)', color: '#10b981', padding: '0.08rem 0.35rem', borderRadius: '4px', fontSize: '0.68rem', fontWeight: 600 }}>
                                ✓ Kabul Edildi
                              </span>
                            )}
                            {row.is_vetoed === 1 && (
                              <span style={{ background: 'rgba(245, 158, 11, 0.2)', color: '#fbbf24', padding: '0.08rem 0.35rem', borderRadius: '4px', fontSize: '0.68rem' }}>
                                🚫 Kapatılmış/Veto
                              </span>
                            )}
                            {tagsList.slice(0, 3).map((tag, tIdx) => (
                              <span key={tIdx} style={{ background: 'rgba(56, 189, 248, 0.12)', color: '#38bdf8', padding: '0.08rem 0.3rem', borderRadius: '4px', fontSize: '0.68rem', border: '1px solid rgba(56, 189, 248, 0.25)' }}>
                                #{tag}
                              </span>
                            ))}
                            {tagsList.length > 3 && (
                              <span style={{ fontSize: '0.68rem', color: '#94a3b8' }}>+{tagsList.length - 3}</span>
                            )}
                          </div>

                          {subtitle && <div style={{ fontSize: '0.73rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>{subtitle}</div>}
                        </td>
                        <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', maxWidth: '480px', whiteSpace: 'normal', wordBreak: 'break-word', lineHeight: 1.4 }}>
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
              <div className="modal-card" style={{ maxWidth: '850px', width: '92%' }} onClick={(e) => e.stopPropagation()}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem' }}>
                  <h3 style={{ margin: 0, fontSize: '1.05rem', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                    📖 Metin Detayı: {selectedRowModal.title || selectedRowModal.filename || `ID #${selectedRowModal.id || selectedRowModal.article_id}`}
                    {selectedRowModal.is_excluded === 1 && (
                      <span className="badge offline" style={{ fontSize: '0.7rem', textDecoration: 'line-through' }}>🗑️ İhraç Dışı (Silindi)</span>
                    )}
                    {selectedRowModal.human_rating === 1 && (
                      <span className="badge online" style={{ fontSize: '0.7rem' }}>👍 Beğenildi (Verified)</span>
                    )}
                    {selectedRowModal.human_rating === -1 && (
                      <span className="badge warning" style={{ fontSize: '0.7rem' }}>👎 Beğenilmedi (Rejected)</span>
                    )}
                  </h3>
                  
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <label style={{ fontSize: '0.78rem', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.3rem', color: renderMathMode ? '#38bdf8' : 'var(--text-secondary)' }}>
                      <input
                        type="checkbox"
                        checked={renderMathMode}
                        onChange={(e) => setRenderMathMode(e.target.checked)}
                      />
                      👁️ KaTeX Render
                    </label>
                    <button className="btn btn-secondary" style={{ padding: '0.2rem 0.6rem' }} onClick={() => setSelectedRowModal(null)}>✕ Kapat</button>
                  </div>
                </div>

                {/* StackExchange / Kiwix Metadata Banner in Modal */}
                {(selectedRowModal.tags || selectedRowModal.vote_score || selectedRowModal.is_accepted === 1 || selectedRowModal.is_vetoed === 1 || selectedRowModal.source_type) && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.75rem', padding: '0.5rem 0.75rem', background: 'rgba(15, 23, 42, 0.7)', borderRadius: '6px', border: '1px solid var(--border-color)', alignItems: 'center', fontSize: '0.78rem' }}>
                    {selectedRowModal.source_type && (
                      <span className="badge" style={{ background: 'rgba(99, 102, 241, 0.2)', color: '#a5b4fc' }}>
                        Kaynak: {selectedRowModal.source_type}
                      </span>
                    )}
                    {selectedRowModal.vote_score !== undefined && (
                      <span className="badge" style={{ background: selectedRowModal.vote_score > 0 ? 'rgba(16, 185, 129, 0.2)' : 'rgba(244, 63, 94, 0.2)', color: selectedRowModal.vote_score > 0 ? '#34d399' : '#fb7185' }}>
                        ▲ Net Skor: {selectedRowModal.vote_score}
                      </span>
                    )}
                    {selectedRowModal.is_accepted === 1 && (
                      <span className="badge online" style={{ fontSize: '0.72rem' }}>
                        ✓ Kabul Edilmiş Yanıt İçeriyor
                      </span>
                    )}
                    {selectedRowModal.is_vetoed === 1 && (
                      <span className="badge warning" style={{ fontSize: '0.72rem' }}>
                        🚫 Topluluk Vetosu / Kapatılmış Soru
                      </span>
                    )}
                    {selectedRowModal.tags && (
                      <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'center', flexWrap: 'wrap' }}>
                        <span style={{ color: 'var(--text-secondary)' }}>Etiketler:</span>
                        {(typeof selectedRowModal.tags === 'string' ? (selectedRowModal.tags.startsWith('[') ? JSON.parse(selectedRowModal.tags) : selectedRowModal.tags.split(',')) : selectedRowModal.tags).map((t: string, idx: number) => (
                          <span key={idx} style={{ background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', padding: '0.05rem 0.35rem', borderRadius: '4px', fontSize: '0.7rem', border: '1px solid rgba(56, 189, 248, 0.3)' }}>
                            #{t.trim()}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                <div style={{ maxHeight: '60vh', overflowY: 'auto', background: 'var(--bg-primary)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)', fontSize: '0.85rem', lineHeight: 1.6, color: 'var(--text-primary)' }}>
                  <MathMarkdownRenderer
                    content={
                      selectedRowModal.extracted_text ||
                      selectedRowModal.summary ||
                      selectedRowModal.tr_sft_qa ||
                      selectedRowModal.sft_qa ||
                      (typeof selectedRowModal === 'string' ? selectedRowModal : JSON.stringify(selectedRowModal, null, 2))
                    }
                    rawMode={!renderMathMode}
                  />
                </div>

                {/* Human Feedback & Exclude Action Bar */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '1rem', paddingTop: '0.75rem', borderTop: '1px solid var(--border-color)' }}>
                  <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                    <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>İnsan Onay & Kalite Düzeltme:</span>
                    
                    <button
                      className="btn btn-secondary"
                      onClick={() => handleRateItem(selectedRowModal.article_id || selectedRowModal.id, 1)}
                      style={{
                        padding: '0.3rem 0.65rem',
                        fontSize: '0.78rem',
                        borderColor: selectedRowModal.human_rating === 1 ? '#10b981' : undefined,
                        color: selectedRowModal.human_rating === 1 ? '#34d399' : undefined,
                        backgroundColor: selectedRowModal.human_rating === 1 ? 'rgba(16, 185, 129, 0.15)' : undefined,
                      }}
                    >
                      👍 Beğendim {selectedRowModal.human_rating === 1 ? '✓' : ''}
                    </button>

                    <button
                      className="btn btn-secondary"
                      onClick={() => handleRateItem(selectedRowModal.article_id || selectedRowModal.id, -1)}
                      style={{
                        padding: '0.3rem 0.65rem',
                        fontSize: '0.78rem',
                        borderColor: selectedRowModal.human_rating === -1 ? '#f43f5e' : undefined,
                        color: selectedRowModal.human_rating === -1 ? '#fb7185' : undefined,
                        backgroundColor: selectedRowModal.human_rating === -1 ? 'rgba(244, 63, 94, 0.15)' : undefined,
                      }}
                    >
                      👎 Beğenmedim {selectedRowModal.human_rating === -1 ? '✓' : ''}
                    </button>

                    <button
                      className="btn btn-secondary"
                      onClick={() => handleToggleExcludeItem(selectedRowModal.article_id || selectedRowModal.id, selectedRowModal.is_excluded === 1)}
                      style={{
                        padding: '0.3rem 0.65rem',
                        fontSize: '0.78rem',
                        borderColor: selectedRowModal.is_excluded === 1 ? '#e11d48' : '#64748b',
                        color: selectedRowModal.is_excluded === 1 ? '#fda4af' : '#cbd5e1',
                        backgroundColor: selectedRowModal.is_excluded === 1 ? 'rgba(225, 29, 72, 0.2)' : undefined,
                        textDecoration: selectedRowModal.is_excluded === 1 ? 'line-through' : 'none',
                      }}
                    >
                      🗑️ {selectedRowModal.is_excluded === 1 ? 'Veri Setine Geri Al' : 'Veri Setinden Sil (İhraç Dışı Bırak)'}
                    </button>
                  </div>

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

      {/* TAB 4: MULTIMODAL MARKDOWN CATALOG */}
      {subTab === 'catalog' && (
        <div style={{ padding: '1rem', background: 'var(--bg-primary)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span style={{ fontSize: '1.2rem' }}>🖼️</span>
              <div>
                <h4 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                  Multimodal Teknik Katalog & Şema Dökümü (`multimodal_catalog.md`)
                </h4>
                <p style={{ margin: 0, fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                  Proje: <code>{activeProjectId}</code> | WebP Şema Kırpmaları & DeepSeek-OCR Analizleri
                </p>
              </div>
            </div>

            <button
              className="btn btn-secondary"
              onClick={fetchCatalog}
              disabled={isLoadingCatalog}
              style={{ fontSize: '0.78rem', padding: '0.35rem 0.75rem' }}
            >
              {isLoadingCatalog ? 'Yenileniyor...' : '🔄 Kataloğu Yenile'}
            </button>
          </div>

          {isLoadingCatalog ? (
            <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-muted)' }}>
              Katalog yükleniyor...
            </div>
          ) : !catalogData?.exists ? (
            <div style={{ padding: '2.5rem', textAlign: 'center', color: '#94a3b8' }}>
              <div style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>📑</div>
              <p style={{ fontSize: '0.85rem' }}>{catalogData?.content || 'Bu projede henüz multimodal katalog ihraç edilmedi.'}</p>
              <code style={{ fontSize: '0.75rem', background: '#1e293b', padding: '0.25rem 0.5rem', borderRadius: '4px', display: 'inline-block', marginTop: '0.5rem' }}>
                python run.py export_visual
              </code>
            </div>
          ) : (
            <div style={{ padding: '1rem', background: '#0b0f19', borderRadius: 'var(--radius-md)', border: '1px solid #1e293b' }}>
              <MathMarkdownRenderer content={catalogData.content} rawMode={!renderMathMode} />
            </div>
          )}
        </div>
      )}
    </div>
  );
};
