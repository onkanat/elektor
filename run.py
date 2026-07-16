import argparse
import sys
from pipeline.extractor import ArchiveExtractor
from pipeline.analyzer import ArchiveAnalyzer
from pipeline.vector_store import ArchiveVectorStore
from pipeline.dataset_builder import DatasetBuilder

def main():
    parser = argparse.ArgumentParser(
        description="Elektor Magazine Archive Processing Pipeline CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py extract --limit 5
  python run.py enrich --limit 5
  python run.py embed --limit 5
  python run.py query "ESP32 bluetooth low energy"
  python run.py export
  python run.py pipeline --limit 5
"""
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Pipeline commands")
    
    # Extract subcommand
    extract_parser = subparsers.add_parser("extract", help="Extract text and metadata from PDFs")
    extract_parser.add_argument("--limit", type=int, default=None, help="Limit the number of files to process")
    
    # Enrich subcommand
    enrich_parser = subparsers.add_parser("enrich", help="Enrich text using local Ollama model (Summary, Q&A, DPO, Turkish)")
    enrich_parser.add_argument("--limit", type=int, default=None, help="Limit the number of articles to enrich")
    
    # Embed subcommand
    embed_parser = subparsers.add_parser("embed", help="Chunk text, generate embeddings, and load to local Qdrant Vector DB")
    embed_parser.add_argument("--limit", type=int, default=None, help="Limit the number of articles to embed")
    
    # Query subcommand
    query_parser = subparsers.add_parser("query", help="Query the local Qdrant Vector DB (RAG search)")
    query_parser.add_argument("query_text", type=str, help="The search query string")
    query_parser.add_argument("--top_k", type=int, default=3, help="Number of results to return")
    
    # Export subcommand
    subparsers.add_parser("export", help="Compile and export SFT, DPO, and Chat datasets to JSONL")
    
    # Pipeline subcommand
    pipeline_parser = subparsers.add_parser("pipeline", help="Run extract, enrich, embed, and export in a single run")
    pipeline_parser.add_argument("--limit", type=int, default=5, help="Limit the number of sample articles to process")
    
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
