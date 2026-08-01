export interface PipelineConfig {
  input_mode: 'folder' | 'book';
  input_path: string;
  db_path: string;
  qdrant_db_path: string;
  ollama_url: string;
  model_embedding: string;
  model_analyzer: string;
  model_translator: string;
  llm_persona: string;
  llm_subject: string;
  generation_language: string;
  translation_target: string;
  sft_qa_count: number;
  dataset_name: string;
  dataset_name_tr: string;
  qdrant_collection_name: string;
  chunk_size: number;
  chunk_overlap: number;
  ocr_threshold_chars: number;
  tesseract_cmd: string;
}

export interface HealthInfo {
  status: string;
  port: number;
  ollama_status: string;
  ollama_url: string;
  available_models: string[];
  sqlite_exists: boolean;
  qdrant_exists: boolean;
  config: PipelineConfig;
}

export interface PipelineState {
  status: 'idle' | 'running' | 'completed' | 'failed';
  command: string | null;
  start_time: number | null;
  end_time: number | null;
  exit_code: number | null;
  logs: string[];
}

export interface DatasetItem {
  filename: string;
  relative_path: string;
  full_path: string;
  size_bytes: number;
  modified_at: number;
  sample_count: number;
}

export interface SQLiteTableInfo {
  name: string;
  count: number;
}

export interface QdrantInfo {
  exists: boolean;
  path: string;
  collection: string;
  all_collections?: string[];
  points_count: number;
  error?: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}
