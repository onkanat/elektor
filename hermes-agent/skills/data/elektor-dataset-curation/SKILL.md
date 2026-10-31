---
name: elektor-dataset-curation
description: "Curate, judge, and export Turkish SFT/DPO datasets."
version: 1.0.0
author: Hakan KILICASLAN (onkanat), Hermes Agent
license: MIT
platforms: [linux, macos]
required_environment_variables:
  - name: GEMINI_API_KEY
    prompt: "Google Gemini API Key (optional for hybrid Judge arbitration)"
    help: "Used when running LLM-as-a-Judge (judge_engine.py) with Gemini Flash"
    required_for: "Hybrid Gemini Judge arbitration"
  - name: HF_TOKEN
    prompt: "Hugging Face Write Token (optional for hub upload)"
    help: "Used by run.py hf_upload to push curated JSONL datasets"
    required_for: "Uploading datasets to Hugging Face Hub"
metadata:
  hermes:
    tags: [sft, dpo, unsloth, judge, turkish-llm, elektor]
    category: data
    requires_toolsets: [terminal]
    config:
      - key: elektor.repo_path
        description: "Absolute path to the Elektor repository"
        default: "/home/hakan/Git/elektor"
        prompt: "Elektor repository path"
    blueprint:
      schedule: "0 3 * * *"
      deliver: "local"
      prompt: "Run Elektor boilerplate cleaning, Judge audit, and SFT/DPO dataset export."
      no_agent: false
---

# Elektor SFT/DPO Dataset Curation & Judge Skill

Dataset quality assurance, Turkish technical synthesis, boilerplate filtering, and Unsloth/TRL export skill for Hermes agents. It guarantees that exported `sft_dataset.jsonl`, `tr_sft_dataset.jsonl`, `dpo_dataset.jsonl`, and `tr_dpo_dataset.jsonl` files in `exports/<project_id>/` have zero static metadata/context leakage (`"input": ""`), zero copyright/license noise, and verified LLM-as-a-Judge quality scores.

## When to Use

- The user wants to export or clean SFT (`sft_dataset.jsonl`, `tr_sft_dataset.jsonl`), DPO (`dpo_dataset.jsonl`, `tr_dpo_dataset.jsonl`), Chat (`chat_dataset.jsonl`, `tr_chat_dataset.jsonl`), or Multimodal (`multimodal_visual_dataset.jsonl`) fine-tuning datasets for Unsloth Desktop, TRL, or LLaMA-Factory.
- You need to strip static metadata tags (`Context: ...`, `Bağlam: ...`) or legal/license/copyright questions (`clean_boilerplate`) that cause shortcut memorization during LoRA/QLoRA fine-tuning.
- You want to run `pipeline/judge_engine.py` (`judge` or `trigger`) in `strict` or `hybrid_editor` mode to score dataset pairs on accuracy, Turkish technical fluency, and completeness.
- You want to generate ready-to-run Unsloth Colab/Antigravity-IDE notebooks (`colab`) or schedule nightly dataset audits via Hermes cron blueprints.

## Prerequisites

- Repository virtualenv (`.venv/bin/python`) or `python3`.
- Populated SQLite `enrichments` table in the active project (`db_path`, e.g., `database/rp01.db`).
- `terminal` toolset enabled in Hermes Agent.

## How to Run

Clean legal/license boilerplate and re-export leak-free SFT/DPO datasets via `terminal`:

```python
terminal(
    command="python3 ${HERMES_SKILL_DIR}/scripts/elektor_hermes_cli.py run-stage clean_boilerplate",
    timeout=60
)
```

For exact JSONL schema contracts, Judge rubrics, and cron automation blueprints, load:
- `skill_view("elektor-dataset-curation", "references/sft-dpo-schemas.md")`
- `skill_view("elektor-dataset-curation", "references/judge-and-autonomous-cron.md")`
- `skill_view("elektor-dataset-curation", "templates/hermes_cron_blueprint.yaml")`

## Quick Reference

| Action | Command (`elektor_hermes_cli.py`) | Artifact Produced in `exports/<project_id>/` |
| :--- | :--- | :--- |
| Purge License/Copyright/TOC Noise | `elektor_hermes_cli.py run-stage clean_boilerplate` | Cleans SQLite `articles`/`enrichments` + re-exports JSONL |
| Export Text SFT, DPO & Chat Datasets | `elektor_hermes_cli.py run-stage export` | `sft_dataset.jsonl`, `tr_sft_dataset.jsonl`, `dpo_dataset.jsonl`, `tr_dpo_dataset.jsonl`, `chat_dataset.jsonl` |
| Export Multimodal Vision Datasets | `elektor_hermes_cli.py run-stage export_visual` | `multimodal_visual_dataset.jsonl`, `multimodal_catalog.md`, `images/*.webp` |
| Run LLM-as-a-Judge Audit | `elektor_hermes_cli.py run-stage judge --mode strict --threshold 7.0 --limit 30` | Updates quality status & scores in SQLite |
| Run Editor-in-Chief Surgical Rewrite | `elektor_hermes_cli.py run-stage judge --mode hybrid_editor --threshold 7.0 --limit 30` | Rewrites borderline SFT/DPO records |
| Autonomous Batch Trigger Audit | `elektor_hermes_cli.py run-stage trigger --mode strict --threshold 7.0 --limit 50` | Runs scheduled audit pass |
| Generate Unsloth Notebooks | `elektor_hermes_cli.py run-stage colab --project rp01 --type all` | `cloud_payload/unsloth_colab_<type>_<project_id>.ipynb` |

## Procedure

1. **Purge Boilerplate and Legal Noise (`clean_boilerplate`)**
   Run `elektor_hermes_cli.py run-stage clean_boilerplate` via `terminal`.
   - *Completion criterion*: Marks Colophon/TOC articles as `is_excluded = 1` and removes non-technical Q&A pairs about Creative Commons licenses, Synopsys/DesignWare copyrights, and disclaimers from SQLite `enrichments`.

2. **Compile Leak-Free SFT & DPO JSONL Files (`export`)**
   Run `elektor_hermes_cli.py run-stage export` via `terminal`.
   - *Completion criterion*:
     - `exports/<project_id>/sft_dataset.jsonl` and `tr_sft_dataset.jsonl` records strictly follow `{"instruction": "...", "input": "", "output": "..."}` with `"input": ""` and zero `Context:` / `Bağlam:` template leakage.
     - `exports/<project_id>/dpo_dataset.jsonl` and `tr_dpo_dataset.jsonl` records strictly follow `{"prompt": "...", "chosen": "...", "rejected": "..."}` with no extraneous `input` field.

3. **Run LLM-as-a-Judge Evaluation (`judge` or `trigger`)**
   Run `elektor_hermes_cli.py run-stage judge --mode strict --threshold 7.0 --limit 30` (or `--mode hybrid_editor` to surgically rewrite borderline pairs).
   - *Completion criterion*: `returncode == 0` and evaluated records in SQLite are scored on a `1.0 - 10.0` rubric.

4. **Generate Unsloth Training Notebooks (`colab`)**
   If the user is preparing a GPU training run, execute `elektor_hermes_cli.py run-stage colab --project <project_id> --type all`.
   - *Completion criterion*: `unsloth_colab_sft_<project_id>.ipynb`, `unsloth_colab_dpo_<project_id>.ipynb`, `unsloth_colab_chat_<project_id>.ipynb`, and `unsloth_colab_langextract_<project_id>.ipynb` are generated in `exports/<project_id>/cloud_payload/`.

## Pitfalls

- **Static `input` tag memorization in Unsloth**: Keep `clean_alpaca_input: true` in `config.json` so `"input"` in `sft_dataset.jsonl` / `tr_sft_dataset.jsonl` is always `""`. Injecting `"Context: rp_pico (2026)..."` causes LoRA adapters to memorize headers instead of electronics concepts.
- **Unbounded Judge runs**: Always pass `--limit <N>` to `run-stage judge` or `run-stage trigger` during interactive runs so you do not inadvertently audit thousands of rows at once.

## Verification

Verify the dataset context and export pipeline:

```python
terminal(
    command="python3 ${HERMES_SKILL_DIR}/scripts/elektor_hermes_cli.py dataset-context --topic 'RP2040' --format-type sft --max-samples 2 --json",
    timeout=20
)
```
