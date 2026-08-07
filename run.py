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
    
    subparsers = parser.add_subparsers(dest="command", help="Pipeline commands")
    
    # Extract subcommand
    extract_parser = subparsers.add_parser("extract", help="Extract text and metadata from PDFs")
    extract_parser.add_argument("--limit", type=parse_limit, default=None, help="Limit the number of files to process (supports range 'start:end')")
    extract_parser.add_argument("--reset", action="store_true", help="Reset all databases and exported datasets before running")

    # Enrich subcommand
    enrich_parser = subparsers.add_parser("enrich", help="Enrich text using local Ollama model (Summary, Q&A, DPO, Turkish)")
    enrich_parser.add_argument("--limit", type=parse_limit, default=None, help="Limit the number of articles to enrich (supports range 'start:end')")
    enrich_parser.add_argument("--reset", action="store_true", help="Reset all databases and exported datasets before running")

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
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
        
    setup_global_project_logging()
        
    if getattr(args, "reset", False):
        reset_pipeline_data()

    if args.command == "extract":
        print("=== Step 1: Extraction & Preprocessing ===")
        extractor = ArchiveExtractor()
        try:
            extractor.process_all_articles(limit=args.limit)
        finally:
            extractor.close()
            
    elif args.command == "enrich":
        print("=== Step 2: Analysis & AI Model Enrichment ===")
        analyzer = ArchiveAnalyzer()
        try:
            analyzer.enrich_all(limit=args.limit)
        finally:
            analyzer.close()
            
    elif args.command == "embed":
        print("=== Step 3: Embed & Load to Qdrant Vector DB ===")
        store = ArchiveVectorStore()
        store.load_to_vector_db(limit=args.limit)
        
    elif args.command == "query":
        print(f"=== Querying Vector DB for: '{args.query_text}' ===")
        store = ArchiveVectorStore()
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
        builder = DatasetBuilder()
        builder.export_datasets()

    elif args.command == "hf_upload":
        print("=== Step 5: Uploading Dataset to Hugging Face Hub ===")
        from pipeline.hf_deployer import HFDeployer
        deployer = HFDeployer()
        
        project_id = args.project_id
        if not project_id:
            try:
                with open("config.json", "r", encoding="utf-8") as f:
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
        extractor = ArchiveExtractor()
        try:
            extractor.process_all_articles(limit=limit)
        finally:
            extractor.close()
            
        # 2. Enrich
        print("\n--- Step 2: Generating Q&A, DPO, and Turkish translation ---")
        analyzer = ArchiveAnalyzer()
        try:
            analyzer.enrich_all(limit=limit)
        finally:
            analyzer.close()
            
        # 3. Embed
        print("\n--- Step 3: Generating embeddings and loading to Qdrant ---")
        store = ArchiveVectorStore()
        store.load_to_vector_db(limit=limit)
        
        # 4. Export
        print("\n--- Step 4: Exporting datasets ---")
        builder = DatasetBuilder()
        builder.export_datasets()
        
        print("\nPipeline execution complete!")

if __name__ == "__main__":
    main()
