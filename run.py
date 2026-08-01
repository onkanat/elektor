import argparse
import sys
from pipeline.extractor import ArchiveExtractor
from pipeline.analyzer import ArchiveAnalyzer
from pipeline.vector_store import ArchiveVectorStore
from pipeline.dataset_builder import DatasetBuilder

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

def main():
    parser = argparse.ArgumentParser(
        description="Elektor Magazine Archive Processing Pipeline CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py extract --limit 5
  python run.py extract --limit 1000:2000
  python run.py enrich --limit 5
  python run.py embed --limit 5
  python run.py query "ESP32 bluetooth low energy"
  python run.py export
  python run.py pipeline --limit 5
  python run.py pipeline --limit 1000:2000
"""
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Pipeline commands")
    
    # Extract subcommand
    extract_parser = subparsers.add_parser("extract", help="Extract text and metadata from PDFs")
    extract_parser.add_argument("--limit", type=parse_limit, default=None, help="Limit the number of files to process (supports range 'start:end')")
    
    # Enrich subcommand
    enrich_parser = subparsers.add_parser("enrich", help="Enrich text using local Ollama model (Summary, Q&A, DPO, Turkish)")
    enrich_parser.add_argument("--limit", type=parse_limit, default=None, help="Limit the number of articles to enrich (supports range 'start:end')")
    
    # Embed subcommand
    embed_parser = subparsers.add_parser("embed", help="Chunk text, generate embeddings, and load to local Qdrant Vector DB")
    embed_parser.add_argument("--limit", type=parse_limit, default=None, help="Limit the number of articles to embed (supports range 'start:end')")
    
    # Query subcommand
    query_parser = subparsers.add_parser("query", help="Query the local Qdrant Vector DB (RAG search)")
    query_parser.add_argument("query_text", type=str, help="The search query string")
    query_parser.add_argument("--top_k", type=int, default=3, help="Number of results to return")
    
    # Export subcommand
    subparsers.add_parser("export", help="Compile and export SFT, DPO, and Chat datasets to JSONL")
    
    # Pipeline subcommand
    pipeline_parser = subparsers.add_parser("pipeline", help="Run extract, enrich, embed, and export in a single run")
    pipeline_parser.add_argument("--limit", type=parse_limit, default=None, help="Limit the number of sample articles to process (default: all articles, supports range 'start:end' or integer)")
    pipeline_parser.add_argument("--reset", action="store_true", help="Reset all databases and exported datasets before running the pipeline")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
        
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
        
    elif args.command == "pipeline":
        print("=== RUNNING FULL PIPELINE ===")
        limit = args.limit
        
        if args.reset:
            print("\n--- Resetting pipeline data (clean wipe) ---")
            import os
            from pathlib import Path
            import json
            
            config_path = "config.json"
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                
            # 1. Delete SQLite Database file
            db_file = Path(config["db_path"])
            if db_file.exists():
                print(f"Deleting SQLite database: {db_file}")
                try:
                    db_file.unlink()
                except Exception as e:
                    print(f"Warning: Could not delete SQLite database: {e}")
                    
            # 2. Delete Qdrant Database folder
            import shutil
            qdrant_dir = Path(config["qdrant_db_path"])
            if qdrant_dir.exists():
                print(f"Deleting Qdrant database folder: {qdrant_dir}")
                try:
                    shutil.rmtree(qdrant_dir)
                except Exception as e:
                    print(f"Warning: Could not delete Qdrant folder: {e}")
                
            # 3. Clear Export JSONL files
            with open("config.json", "r", encoding="utf-8") as f:
                cfg = json.load(f)
            db_name = Path(cfg.get("db_path", "elektor_archive.db")).stem
            export_dir = Path("exports") / db_name
            if export_dir.exists():
                print(f"Clearing exports/{db_name} directory...")
                for file in export_dir.glob("*.jsonl"):
                    try:
                        file.unlink()
                    except Exception as e:
                        print(f"Warning: Could not delete export file {file.name}: {e}")
            print("Reset completed successfully. Starting pipeline from clean state.\n")
            
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
