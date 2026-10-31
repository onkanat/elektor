# LLM-as-a-Judge & Autonomous Hermes Cron Automation

## 1. Judge Engine (`pipeline/judge_engine.py`)

The Elektor Judge Engine (`pipeline/judge_engine.py`) evaluates SFT and DPO pairs on a `1.0 – 10.0` scale across technical accuracy, self-contained clarity, and Turkish/English engineering syntax. It supports two execution modes:
1. **`strict` Mode (Fast Scoring & Filtering)**:
   - Scores records against `--threshold` (default `7.0`) and marks low-scoring items in SQLite.
2. **`hybrid_editor` Mode (Editor-in-Chief Surgical Rewrite)**:
   - Borderline records below `--threshold` are surgically rewritten into gold-standard `chosen` responses while preserving the original flawed response as `rejected` for DPO training.

### Running the Judge via CLI Bridge or `run.py`
```bash
# Via Hermes CLI bridge:
python3 hermes-agent/scripts/elektor_hermes_cli.py run-stage judge --mode strict --threshold 7.0 --limit 30

# Or surgical rewrite mode:
python3 hermes-agent/scripts/elektor_hermes_cli.py run-stage judge --mode hybrid_editor --threshold 7.0 --limit 30
```

### Running Autonomous Scheduled Trigger (`pipeline/scheduled_triggers.py`)
```bash
python3 hermes-agent/scripts/elektor_hermes_cli.py run-stage trigger --mode strict --threshold 7.0 --limit 50
```

---

## 2. Scheduling Nightly Curation in Hermes Agent

Hermes Agent supports scheduled background execution via `cronjob` tool calls or `metadata.hermes.blueprint` in `SKILL.md`. See `templates/hermes_cron_blueprint.yaml` for a ready-to-use configuration.
