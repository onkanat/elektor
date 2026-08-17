import os
import json
from collections import Counter
from pathlib import Path

def inspect_archive(source_path, output_json):
    print(f"Scanning directory: {source_path}...")
    source = Path(source_path)
    
    if not source.exists():
        print(f"Error: Path '{source_path}' does not exist or is not mounted.")
        return

    file_counter = Counter()
    size_counter = Counter()
    total_files = 0
    total_size = 0
    structure = {}

    for root, dirs, files in os.walk(source):
        for file in files:
            file_path = Path(root) / file
            # Ignore hidden files
            if file.startswith('.'):
                continue
                
            ext = file_path.suffix.lower()
            if not ext:
                ext = 'no_extension'
                
            try:
                size = file_path.stat().st_size
            except Exception:
                size = 0
                
            file_counter[ext] += 1
            size_counter[ext] += size
            total_files += 1
            total_size += size
            
            # Record directory structure up to level 2
            try:
                rel_path = file_path.relative_to(source)
                parts = rel_path.parts
                if len(parts) >= 1:
                    year_or_folder = parts[0]
                    if year_or_folder not in structure:
                        structure[year_or_folder] = {"count": 0, "size": 0}
                    structure[year_or_folder]["count"] += 1
                    structure[year_or_folder]["size"] += size
            except Exception:
                pass

    report = {
        "summary": {
            "total_files": total_files,
            "total_size_gb": round(total_size / (1024**3), 2),
            "total_size_bytes": total_size
        },
        "by_extension": {
            ext: {
                "count": count,
                "size_mb": round(size_counter[ext] / (1024**2), 2)
            }
            for ext, count in file_counter.items()
        },
        "top_level_folders": {
            folder: {
                "count": data["count"],
                "size_mb": round(data["size"] / (1024**2), 2)
            }
            for folder, data in sorted(structure.items())
        }
    }

    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=4, ensure_ascii=False)

    print(f"\nScan completed successfully!")
    print(f"Total Files: {total_files}")
    print(f"Total Size: {report['summary']['total_size_gb']} GB")
    print(f"Report saved to: {output_json}")

if __name__ == "__main__":
    # You can run this script using python3 inspect_usb.py
    usb_path = "/Volumes/USB DISK"
    output_report = "usb_inventory_report.json"
    inspect_archive(usb_path, output_report)
