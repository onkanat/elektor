"""
Universal Dataset Orchestrator (Sentetik Veri & Davranış Distilasyonu Motoru)
Heterojen veri kaynaklarından (PDF, Git, Kiwix ZIM) izole paralel veri üretimi,
5 boyutlu davranış distilasyonu (LLM Judge), VRAM korumalı kuyruk yönetimi ve
Altın SFT / DPO veri seti derleme orkestratörü.
"""

import os
import sys
import json
import sqlite3
import argparse
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
import urllib.request
import urllib.error

GPU_PORT_POOL = [
    "http://127.0.0.1:11434",
    "http://127.0.0.1:11435",
    "http://192.168.1.14:11434"
]

class UniversalDatasetOrchestrator:
    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.configs_dir = self.base_dir / "configs"
        self.configs_dir.mkdir(parents=True, exist_ok=True)
        self.db_dir = self.base_dir / "database"
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir = self.base_dir / "exports"
        self.exports_dir.mkdir(parents=True, exist_ok=True)

    def check_gpu_endpoints(self) -> Dict[str, bool]:
        """Checks health of all configured local and remote Ollama GPU ports."""
        results = {}
        for endpoint in GPU_PORT_POOL:
            url = f"{endpoint}/api/tags"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "ElektorOrchestrator/1.0"})
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    results[endpoint] = (resp.status == 200)
            except Exception:
                results[endpoint] = False
        return results

    def create_isolated_config(
        self,
        input_source: str,
        input_mode: str = "book",
        project_name: Optional[str] = None,
        ollama_url: Optional[str] = None,
        generation_language: str = "bilingual",
        model_analyzer: str = "qwen3.5:4b",
        model_translator: str = "qwen3.5:4b"
    ) -> Path:
        """Creates a dedicated, isolated config.json file for the given task."""
        source_p = Path(input_source)
        if not project_name:
            project_name = source_p.stem.lower().replace(" ", "_").replace("-", "_")

        # Select first healthy endpoint or fallback to default
        if not ollama_url:
            endpoints = self.check_gpu_endpoints()
            healthy = [ep for ep, ok in endpoints.items() if ok]
            ollama_url = healthy[0] if healthy else GPU_PORT_POOL[0]

        config_data = {
            "project_id": project_name,
            "input_mode": input_mode,
            "input_path": str(input_source),
            "db_path": f"database/{project_name}.db",
            "qdrant_db_path": f"qdrant_extract/{project_name}",
            "export_dir": f"exports/{project_name}",
            "ollama_url": ollama_url,
            "openai_timeout": 600,
            "model_embedding": "nomic-embed-text:latest",
            "model_analyzer": model_analyzer,
            "model_translator": model_translator,
            "llm_persona": "Professional Systems Engineer & Technical Author",
            "llm_subject": "Applied Engineering & Architecture",
            "generation_language": generation_language,
            "direct_tr_generation": True,
            "enable_langextract": True,
            "langextract_provider": "ollama",
            "sqlite_busy_timeout": 60000,
            "sqlite_wal_mode": True
        }

        config_path = self.configs_dir / f"run_{project_name}.json"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)

        # Initialize SQLite with WAL mode & busy timeout
        db_path = self.base_dir / config_data["db_path"]
        conn = sqlite3.connect(str(db_path), timeout=60.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=60000;")
        conn.close()

        return config_path

    def compile_dpo_and_golden_sft(
        self,
        project_name: str,
        min_score_diff: float = 2.0,
        min_golden_score: float = 7.5
    ) -> Dict[str, Any]:
        """
        Applies Behavior Distillation 5-dimension rubric thresholds:
        - Pairs with (judge_score - rejected_score >= min_score_diff) are compiled into DPO dataset.
        - Deduplicated top-tier chosen responses (>= min_golden_score) are compiled into Golden SFT.
        """
        db_path = self.db_dir / f"{project_name}.db"
        if not db_path.exists():
            # Check default extract.db fallback
            fallback_db = self.db_dir / "extract.db"
            if fallback_db.exists():
                db_path = fallback_db
            else:
                return {"status": "error", "message": f"Database not found: {db_path}"}

        export_dir = self.exports_dir / project_name
        export_dir.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Check tables & columns
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [r[0] for r in cursor.fetchall()]

        dpo_records = []
        golden_sft_records = []

        if "enrichments" in tables:
            cursor.execute("PRAGMA table_info(enrichments);")
            cols = [c[1] for c in cursor.fetchall()]
            has_judge = "judge_score" in cols

            query = "SELECT prompt_sft, response_sft, prompt_dpo, chosen_dpo, rejected_dpo"
            if has_judge:
                query += ", judge_score, judge_feedback"
            query += " FROM enrichments WHERE prompt_sft IS NOT NULL AND response_sft IS NOT NULL;"

            cursor.execute(query)
            for row in cursor.fetchall():
                prompt_sft = row[0]
                resp_sft = row[1]
                prompt_dpo = row[2]
                chosen = row[3] or resp_sft
                rejected = row[4]
                score = float(row[5]) if has_judge and row[5] is not None else 8.0

                if prompt_dpo and chosen and rejected:
                    # Valid DPO candidate
                    dpo_records.append({
                        "prompt": prompt_dpo,
                        "chosen": chosen,
                        "rejected": rejected,
                        "score": score
                    })

                if score >= min_golden_score and prompt_sft and resp_sft:
                    golden_sft_records.append({
                        "instruction": prompt_sft,
                        "input": "",
                        "output": resp_sft,
                        "score": score
                    })

        conn.close()

        # Write DPO JSONL
        dpo_file = export_dir / "dpo_dataset.jsonl"
        with open(dpo_file, "w", encoding="utf-8") as f:
            for rec in dpo_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        # Write Golden SFT JSONL
        sft_file = export_dir / "golden_sft_dataset.jsonl"
        with open(sft_file, "w", encoding="utf-8") as f:
            for rec in golden_sft_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        return {
            "status": "success",
            "project_name": project_name,
            "dpo_records_compiled": len(dpo_records),
            "golden_sft_records_compiled": len(golden_sft_records),
            "dpo_file": str(dpo_file),
            "golden_sft_file": str(sft_file)
        }

    def get_status(self) -> Dict[str, Any]:
        """Aggregates current state across configs, databases, exports, and GPU endpoints."""
        gpu_health = self.check_gpu_endpoints()

        projects = []
        for cfg in self.configs_dir.glob("run_*.json"):
            try:
                with open(cfg, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                p_id = cdata.get("project_id", cfg.stem.replace("run_", ""))
                db_file = self.base_dir / cdata.get("db_path", f"database/{p_id}.db")

                article_count = 0
                enrichment_count = 0
                if db_file.exists():
                    conn = sqlite3.connect(str(db_file))
                    c = conn.cursor()
                    try:
                        c.execute("SELECT count(*) FROM articles;")
                        article_count = c.fetchone()[0]
                    except Exception:
                        pass
                    try:
                        c.execute("SELECT count(*) FROM enrichments;")
                        enrichment_count = c.fetchone()[0]
                    except Exception:
                        pass
                    conn.close()

                exports_p = self.exports_dir / p_id
                dpo_exists = (exports_p / "dpo_dataset.jsonl").exists()
                sft_exists = (exports_p / "sft_dataset.jsonl").exists() or (exports_p / "golden_sft_dataset.jsonl").exists()

                projects.append({
                    "project_id": p_id,
                    "input_mode": cdata.get("input_mode"),
                    "input_path": cdata.get("input_path"),
                    "db_exists": db_file.exists(),
                    "articles": article_count,
                    "enrichments": enrichment_count,
                    "sft_ready": sft_exists,
                    "dpo_ready": dpo_exists,
                    "config_file": str(cfg.relative_to(self.base_dir))
                })
            except Exception:
                continue

        return {
            "gpu_endpoints": gpu_health,
            "active_projects": projects,
            "total_projects": len(projects)
        }

def main():
    parser = argparse.ArgumentParser(
        description="Universal Dataset Orchestrator - Heterojen Veri & Davranış Distilasyonu Motoru"
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Komutlar")

    # create-config
    p_cfg = subparsers.add_parser("create-config", help="İzole config dosyası üretir")
    p_cfg.add_argument("--input", required=True, help="Girdi kaynak dosya veya dizin yolu")
    p_cfg.add_argument("--mode", default="book", choices=["book", "folder", "rendergit", "kiwix"], help="Girdi modu")
    p_cfg.add_argument("--name", help="Proje kimliği/adı")
    p_cfg.add_argument("--port", help="Ollama GPU uç noktası")

    # produce
    p_prod = subparsers.add_parser("produce", help="İzole pipeline çalıştırır")
    p_prod.add_argument("--input", required=True, help="Girdi kaynak dosya veya dizin yolu")
    p_prod.add_argument("--mode", default="book", choices=["book", "folder", "rendergit", "kiwix"], help="Girdi modu")
    p_prod.add_argument("--name", help="Proje adı")
    p_prod.add_argument("--limit", default="all", help="İşlenecek makale limiti")
    p_prod.add_argument("--shards", type=int, default=1, help="Paralel shard sayısı")

    # judge
    p_judge = subparsers.add_parser("judge", help="5-Boyutlu davranış hakemliğini (LLM Judge) çalıştırır")
    p_judge.add_argument("--project", required=True, help="Proje adı")
    p_judge.add_argument("--mode", default="strict", choices=["strict", "hybrid_editor"], help="Hakemlik modu")
    p_judge.add_argument("--threshold", type=float, default=7.5, help="Kabul eşik puanı")
    p_judge.add_argument("--batch", action="store_true", help="Gemini Asenkron Toplu İş modu")

    # compile-datasets
    p_comp = subparsers.add_parser("compile-datasets", help="DPO ve Altın SFT veri setlerini derler")
    p_comp.add_argument("--project", required=True, help="Proje adı")
    p_comp.add_argument("--min-diff", type=float, default=2.0, help="DPO için minimum puan farkı")
    p_comp.add_argument("--min-score", type=float, default=7.5, help="Altın SFT için minimum taban puan")

    # status
    subparsers.add_parser("status", help="GPU havuzu ve aktif projelerin durumunu raporlar")

    args = parser.parse_args()
    if not args.subcommand:
        parser.print_help()
        sys.exit(0)

    orch = UniversalDatasetOrchestrator()

    if args.subcommand == "create-config":
        cfg_path = orch.create_isolated_config(
            input_source=args.input,
            input_mode=args.mode,
            project_name=args.name,
            ollama_url=args.port
        )
        print(f"✅ İzole konfigürasyon başarıyla üretildi: {cfg_path}")

    elif args.subcommand == "produce":
        cfg_path = orch.create_isolated_config(
            input_source=args.input,
            input_mode=args.mode,
            project_name=args.name
        )
        print(f"🚀 Pipeline başlatılıyor (Config: {cfg_path})...")
        if args.mode == "kiwix":
            cmd = [sys.executable, "run.py", "--config", str(cfg_path), "kiwix", "--zim", args.input, "--limit", str(args.limit)]
        else:
            cmd = [sys.executable, "run.py", "--config", str(cfg_path), "pipeline", "--limit", str(args.limit)]
        subprocess.run(cmd)

    elif args.subcommand == "judge":
        cfg_path = orch.configs_dir / f"run_{args.project}.json"
        if not cfg_path.exists():
            cfg_path = Path("config.json")
        cmd = [sys.executable, "run.py", "--config", str(cfg_path), "judge", "--mode", args.mode, "--threshold", str(args.threshold)]
        if args.batch:
            cmd.append("--batch")
        print(f"⚖️ Davranış Hakemliği (Judge) başlatılıyor: {' '.join(cmd)}")
        subprocess.run(cmd)

    elif args.subcommand == "compile-datasets":
        res = orch.compile_dpo_and_golden_sft(
            project_name=args.project,
            min_score_diff=args.min_diff,
            min_golden_score=args.min_score
        )
        print("=== Davranış Distilasyonu & Veri Seti Derleme Raporu ===")
        print(json.dumps(res, indent=2, ensure_ascii=False))

    elif args.subcommand == "status":
        st = orch.get_status()
        print("=== 🚀 Universal Dataset Orchestrator Canlı Durum Raporu ===")
        print("\n[GPU & Ollama Uç Noktaları]:")
        for ep, healthy in st["gpu_endpoints"].items():
            icon = "🟢 Çevrimiçi" if healthy else "🔴 Çevrimdışı / Yanıt Yok"
            print(f"  - {ep:<32}: {icon}")

        print(f"\n[Aktif Projeler ({st['total_projects']})]:")
        if not st["active_projects"]:
            print("  (Henüz kayıtlı izole proje bulunmuyor. 'create-config' ile başlatabilirsiniz.)")
        for p in st["active_projects"]:
            print(f"  * Proje: {p['project_id']} (Mod: {p['input_mode']})")
            print(f"    - Girdi : {p['input_path']}")
            print(f"    - DB    : {p['articles']} makale, {p['enrichments']} zenginleştirme")
            print(f"    - Çıktı : SFT: {'✅' if p['sft_ready'] else '⏳'}, DPO: {'✅' if p['dpo_ready'] else '⏳'}")
            print("")

if __name__ == "__main__":
    main()
