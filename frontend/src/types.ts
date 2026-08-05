export interface PipelineConfig {
  project_id?: string;
  project_name?: string;
  input_mode: 'folder' | 'book' | 'rendergit' | 'github';
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
  pragmatic_ratio?: number;
  direct_tr_generation?: boolean;
  enable_dpo_verification?: boolean;
  generate_multi_turn_chat?: boolean;
  code_cat_explanation?: boolean;
  code_cat_completion?: boolean;
  code_cat_bug_fix?: boolean;
  code_cat_unit_test?: boolean;
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

export interface VramModel {
  name: string;
  param_size: string;
  quant: string;
  vram_mb: number;
  vram_gb: number;
  expires_at?: string;
}

export interface SystemMetrics {
  cpu_percent: number;
  memory: {
    total_mb: number;
    used_mb: number;
    available_mb: number;
    percent: number;
  };
  ollama_online: boolean;
  vram_models: VramModel[];
}
