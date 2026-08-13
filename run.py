import argparse
import sys
import os
import json
import shutil
from pathlib import Path
from pipeline.extractor import ArchiveExtractor
from pipeline.analyzer import ArchiveAnalyzer
from pipeline.vector_store import ArchiveVectorStore
from pipeline.dataset_builder import DatasetBuilder
from pipeline.project_logger import setup_global_project_logging, get_project_logger

def parse_limit(limit_str):
    """Parses limit parameter. Supports integer (e.g. 5), range (e.g. '1000:2000'), or 'all'/'none' for no limit."""
    if limit_str is None:
        return None
    limit_str = str(limit_str).strip()
    if not limit_str or limit_str.lower() in ("none", "all", "0"):
        return None
    if ":" in limit_str:
        parts = limit_str.split(":")
        try:
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if parts[1] else None
            return (start, end)
        except ValueError:
            raise argparse.ArgumentTypeError(f"Invalid range format: {limit_str}. Use 'start:end' with integers.")
    else:
        try:
            val = int(limit_str)
            return None if val <= 0 else val
        except ValueError:
            raise argparse.ArgumentTypeError(f"Invalid limit: {limit_str}. Must be an integer, range 'start:end', or 'all'.")

def reset_pipeline_data(config_path="config.json"):
    """Resets SQLite DB, Qdrant DB folder, and all exported files (.jsonl, .parquet, .log, payloads)."""
    print("\n--- Resetting pipeline data (clean wipe) ---")
    if not Path(config_path).exists():
        print(f"Warning: Config file '{config_path}' not found. Skipping reset.")
        return
        
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
        
    # 1. Delete SQLite Database file
    db_file_str = config.get("db_path")
    if db_file_str:
        db_file = Path(db_file_str)
        if db_file.exists():
            print(f"Deleting SQLite database: {db_file}")
            try:
                db_file.unlink()
            except Exception as e:
                print(f"Warning: Could not delete SQLite database: {e}")
                
    # 2. Delete Qdrant Database folder
    qdrant_dir_str = config.get("qdrant_db_path")
    if qdrant_dir_str:
        qdrant_dir = Path(qdrant_dir_str)
        if qdrant_dir.exists():
            print(f"Deleting Qdrant database folder: {qdrant_dir}")
            try:
                shutil.rmtree(qdrant_dir)
            except Exception as e:
                print(f"Warning: Could not delete Qdrant folder: {e}")
            
    # 3. Clear Export Directory (JSONL, Parquet, Logs, Subdirectories)
    db_name = Path(config.get("db_path", "database/elektor_archive.db")).stem
    export_dir = Path("exports") / db_name
    if export_dir.exists():
        print(f"Clearing exports/{db_name} directory (JSONL, Parquet, Logs)...")
        for item in export_dir.glob("*"):
            try:
                if item.is_file() or item.is_symlink():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except Exception as e:
                print(f"Warning: Could not delete export item {item.name}: {e}")
    print("Reset completed successfully. Starting pipeline from clean state.\n")

def run_sharded_enrichment(config_path, limit, shards_count, shard_ports_str, enrich_pass="all"):
    import sqlite3
    import subprocess
    import shutil
    import tempfile
    import urllib.parse
    import threading
    
    ports = [p.strip() for p in shard_ports_str.split(",") if p.strip()]
    if not ports:
        print("Error: No ports provided for sharding.")
        sys.exit(1)
        
    with open(config_path, "r", encoding="utf-8") as f:
        base_config = json.load(f)
        
    db_path = base_config.get("db_path", "database/rapberry_pi_pico_all.db")
    
    # Get all article IDs to split range logically
    conn = sqlite3.connect(db_path, timeout=60.0)
    cur = conn.cursor()
    try:
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA busy_timeout=60000;")
    except sqlite3.OperationalError:
        pass
    cur.execute("SELECT id FROM articles ORDER BY id")
    all_ids = [r[0] for r in cur.fetchall()]
    conn.close()
    
    start, end = 0, len(all_ids)
    if isinstance(limit, tuple):
        start, end = limit
    elif isinstance(limit, int):
        start, end = 0, limit
    active_ids = all_ids[start:end]
    
    total_count = len(active_ids)
    if total_count == 0:
        print("No articles to process in the specified range.")
        return
        
    chunk_size = (total_count + shards_count - 1) // shards_count
    print(f"Parallel Sharding: Splitting {total_count} articles into {shards_count} shards (chunk size ~{chunk_size})...")
    
    # Determine passes to run
    passes_to_run = []
    if enrich_pass == "all":
        passes_to_run = ["english", "turkish"]
    else:
        passes_to_run = [enrich_pass]
        
    for p_mode in passes_to_run:
        print(f"\n--- Starting Sharded Enrichment Phase: {p_mode.upper()} ---")
        processes = []
        temp_files = []
        
        try:
            for i in range(shards_count):
                shard_start_idx = start + i * chunk_size
                shard_end_idx = min(start + (i + 1) * chunk_size, end)
                
                if shard_start_idx >= shard_end_idx:
                    break
                    
                port = ports[i % len(ports)]
                shard_config = base_config.copy()
                
                # Update Ollama URL port
                original_url = shard_config.get("ollama_url", "http://localhost:11434")
                parsed = urllib.parse.urlparse(original_url)
                netloc_parts = parsed.netloc.split(":")
                ip = netloc_parts[0]
                shard_config["ollama_url"] = f"{parsed.scheme}://{ip}:{port}"
                
                fd, temp_cfg_path = tempfile.mkstemp(suffix=f"_shard_{i}.json")
                temp_files.append(temp_cfg_path)
                with os.fdopen(fd, "w", encoding="utf-8") as tf:
                    json.dump(shard_config, tf, indent=2)
                    
                cmd_args = [
                    sys.executable, "run.py",
                    "--config", temp_cfg_path,
                    "enrich",
                    "--limit", f"{shard_start_idx}:{shard_end_idx}",
                    "--pass", p_mode
                ]
                print(f"Starting Shard {i} ({p_mode.upper()} on Port {port}): Range {shard_start_idx}:{shard_end_idx}...")
                p = subprocess.Popen(
                    cmd_args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )
                processes.append((i, p))
                
            def log_stream(shard_idx, proc):
                for line in iter(proc.stdout.readline, ''):
                    print(f"[Shard {shard_idx}] {line.rstrip()}")
                    
            threads = []
            for shard_idx, p in processes:
                t = threading.Thread(target=log_stream, args=(shard_idx, p))
                t.start()
                threads.append(t)
                
            for t in threads:
                t.join()
                
            for shard_idx, p in processes:
                p.wait()
                print(f"Shard {shard_idx} ({p_mode.upper()} Phase) completed with exit code: {p.returncode}")
                
        finally:
            for tf in temp_files:
                try:
                    os.unlink(tf)
                except Exception:
                    pass

def main():
    parser = argparse.ArgumentParser(
        description="Universal PDF & RAG Dataset Processing Pipeline CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py extract --limit 5
  python run.py extract --limit 1000:2000
  python run.py enrich --limit 5
  python run.py embed --limit 5
  python run.py query "ESP32 bluetooth low energy"
  python run.py export
  python run.py pipeline --limit 5 --reset
"""
    )
    
    parser.add_argument(
        "--config",
        type=str,
        default="config.json",
        help="Path to custom configuration JSON file (default: config.json)",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Pipeline commands")
    
    # Extract subcommand
    extract_parser = subparsers.add_parser("extract", help="Extract text and metadata from PDFs")
    extract_parser.add_argument("--limit", type=parse_limit, default=None, help="Limit the number of files to process (supports range 'start:end')")
    extract_parser.add_argument("--reset", action="store_true", help="Reset all databases and exported datasets before running")

    # Enrich subcommand
    enrich_parser = subparsers.add_parser("enrich", help="Enrich text using local Ollama model (Summary, Q&A, DPO, Turkish)")
    enrich_parser.add_argument("--limit", type=parse_limit, default=None, help="Limit the number of articles to enrich (supports range 'start:end')")
    enrich_parser.add_argument("--reset", action="store_true", help="Reset all databases and exported datasets before running")
    enrich_parser.add_argument("--shards", type=int, default=1, help="Number of parallel shards to run")
    enrich_parser.add_argument("--shard-ports", type=str, default=None, help="Comma-separated list of Ollama port numbers (e.g. 11434,11435)")
    enrich_parser.add_argument("--pass", dest="enrich_pass", type=str, choices=["all", "english", "turkish"], default="all", help="Enrichment pass to run (all, english, turkish)")

    # Embed subcommand
    embed_parser = subparsers.add_parser("embed", help="Chunk text, generate embeddings, and load to local Qdrant Vector DB")
    embed_parser.add_argument("--limit", type=parse_limit, default=None, help="Limit the number of articles to embed (supports range 'start:end')")
    embed_parser.add_argument("--reset", action="store_true", help="Reset all databases and exported datasets before running")

    # Query subcommand
    query_parser = subparsers.add_parser("query", help="Query the local Qdrant Vector DB (RAG search)")
    query_parser.add_argument("query_text", type=str, help="The search query string")
    query_parser.add_argument("--top_k", type=int, default=3, help="Number of results to return")
    
    # Export subcommand
    export_parser = subparsers.add_parser("export", help="Compile and export SFT, DPO, and Chat datasets to JSONL & Parquet")
    export_parser.add_argument("--reset", action="store_true", help="Reset all exported datasets before running")

    # Export Visual subcommand (FAZ-11)
    export_visual_parser = subparsers.add_parser("export_visual", help="Export FAZ-11 Multimodal Visual Dataset (LLaVA/Qwen2-VL format)")
    export_visual_parser.add_argument("--keep-raw", action="store_true", help="Keep raw PNG crops in downloads/extracted_images/ after WebP optimization")

    # HF Upload subcommand
    hf_parser = subparsers.add_parser("hf_upload", help="Upload exported dataset to Hugging Face Hub")
    hf_parser.add_argument("--repo_id", type=str, required=True, help="Target Hugging Face repo ID (e.g. username/repo-name)")
    hf_parser.add_argument("--project_id", type=str, default=None, help="Project ID to upload (defaults to active project)")
    hf_parser.add_argument("--token", type=str, default=None, help="Hugging Face Access Token (HF_TOKEN)")
    hf_parser.add_argument("--private", action="store_true", help="Set repository to private")

    # Pipeline subcommand
    pipeline_parser = subparsers.add_parser("pipeline", help="Run extract, enrich, embed, and export in a single run")
    pipeline_parser.add_argument("--limit", type=parse_limit, default=None, help="Limit the number of sample articles to process (default: all articles, supports range 'start:end' or integer)")
    pipeline_parser.add_argument("--reset", action="store_true", help="Reset all databases and exported datasets before running the pipeline")
    pipeline_parser.add_argument("--shards", type=int, default=1, help="Number of parallel shards to run")
    pipeline_parser.add_argument("--shard-ports", type=str, default=None, help="Comma-separated list of Ollama port numbers (e.g. 11434,11435)")
    pipeline_parser.add_argument("--pass", dest="enrich_pass", type=str, choices=["all", "english", "turkish"], default="all", help="Enrichment pass to run (all, english, turkish)")
    
    # API subcommand
    api_parser = subparsers.add_parser("api", help="Launch the unified web dashboard (FastAPI + React)")
    api_parser.add_argument("--port", type=int, default=3456, help="Port to run the API server on")
    api_parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to run the API server on")
    
    # Self-test subcommand
    self_test_parser = subparsers.add_parser("self_test", help="Run comprehensive system health self-test & diagnostics")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
        
    setup_global_project_logging()
        
    if getattr(args, "reset", False):
        reset_pipeline_data(args.config)

    if args.command == "extract":
        print("=== Step 1: Extraction & Preprocessing ===")
        extractor = ArchiveExtractor(config_path=args.config)
        try:
            extractor.process_all_articles(limit=args.limit)
        finally:
            extractor.close()
            
    elif args.command == "enrich":
        print("=== Step 2: Analysis & AI Model Enrichment ===")
        shards = getattr(args, "shards", 1)
        shard_ports = getattr(args, "shard_ports", None)
        enrich_pass = getattr(args, "enrich_pass", "all")
        
        if shards > 1 and shard_ports:
            run_sharded_enrichment(args.config, args.limit, shards, shard_ports, enrich_pass)
        else:
            analyzer = ArchiveAnalyzer(config_path=args.config)
            try:
                analyzer.enrich_all(limit=args.limit, enrich_pass=enrich_pass)
            finally:
                analyzer.close()
            
    elif args.command == "embed":
        print("=== Step 3: Embed & Load to Qdrant Vector DB ===")
        store = ArchiveVectorStore(config_path=args.config)
        store.load_to_vector_db(limit=args.limit)
        
    elif args.command == "query":
        print(f"=== Querying Vector DB for: '{args.query_text}' ===")
        store = ArchiveVectorStore(config_path=args.config)
        results = store.search(args.query_text, top_k=args.top_k)
        if not results:
            print("No matching documents found.")
        for i, match in enumerate(results):
            print(f"\n[{i+1}] Score: {match['score']:.4f} | {match['title']} ({match['year']}) | File: {match['filename']}")
            print("-" * 50)
            print(match['text'])
            print("-" * 50)
            
    elif args.command == "export":
        print("=== Step 4: Compiling and Exporting Datasets ===")
        builder = DatasetBuilder(config_path=args.config)
        builder.export_datasets()

    elif args.command == "export_visual":
        print("=== Step 4.5: Exporting Multimodal Visual Dataset (FAZ-11) ===")
        from pipeline.visual_dataset_builder import VisualDatasetBuilder
        builder = VisualDatasetBuilder(config_path=args.config)
        builder.export_multimodal_dataset(clean_raw_crops=not getattr(args, "keep_raw", False))

    elif args.command == "hf_upload":
        print("=== Step 5: Uploading Dataset to Hugging Face Hub ===")
        from pipeline.hf_deployer import HFDeployer
        deployer = HFDeployer()
        
        project_id = args.project_id
        if not project_id:
            try:
                with open(args.config, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    project_id = cfg.get("project_id", "sdr_engineers")
            except Exception:
                project_id = "sdr_engineers"

        res = deployer.upload_dataset(
            project_id=project_id,
            repo_id=args.repo_id,
            hf_token=args.token,
            private=args.private
        )
        print(f"✅ Successfully uploaded {len(res['uploaded_files'])} files to Hugging Face Datasets Hub!")
        print(f"🔗 Dataset URL: {res['repo_url']}")
        
    elif args.command == "pipeline":
        print("=== RUNNING FULL PIPELINE ===")
        limit = args.limit
        print(f"Processing sample limit: {limit} articles...\n")
        
        # 1. Extract
        print("\n--- Step 1: Extracting text ---")
        extractor = ArchiveExtractor(config_path=args.config)
        try:
            extractor.process_all_articles(limit=limit)
        finally:
            extractor.close()
            
        # 2. Enrich
        print("\n--- Step 2: Generating Q&A, DPO, and Turkish translation ---")
        shards = getattr(args, "shards", 1)
        shard_ports = getattr(args, "shard_ports", None)
        enrich_pass = getattr(args, "enrich_pass", "all")
        if shards > 1 and shard_ports:
            run_sharded_enrichment(args.config, limit, shards, shard_ports, enrich_pass)
        else:
            analyzer = ArchiveAnalyzer(config_path=args.config)
            try:
                analyzer.enrich_all(limit=limit, enrich_pass=enrich_pass)
            finally:
                analyzer.close()
            
        # 3. Embed
        print("\n--- Step 3: Generating embeddings and loading to Qdrant ---")
        store = ArchiveVectorStore(config_path=args.config)
        store.load_to_vector_db(limit=limit)
        
        # 4. Export
        print("\n--- Step 4: Exporting datasets ---")
        builder = DatasetBuilder(config_path=args.config)
        builder.export_datasets()
        
        print("\nPipeline execution complete!")

    elif args.command == "api":
        print(f"=== Starting Web UI Dashboard on http://{args.host}:{args.port} ===")
        import uvicorn
        uvicorn.run("api_server:app", host=args.host, port=args.port, reload=True)

    elif args.command == "self_test":
        from pipeline.self_test import run_self_test
        success = run_self_test(config_path=args.config)
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
