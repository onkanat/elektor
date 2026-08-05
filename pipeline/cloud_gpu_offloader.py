import json
import os
from pathlib import Path
from typing import Dict, Any

class CloudGPUOffloader:
    def __init__(self, exports_dir: str = "exports"):
        self.exports_dir = Path(exports_dir)

    def generate_unsloth_script(self, project_id: str, base_model: str, hf_dataset: str) -> str:
        """
        Generates a production-grade Unsloth fine-tuning script with:
        - Base model validation (Transformers PyTorch repo, avoiding quantized GGUF inputs)
        - BF16 LoRA vs 4-Bit QLoRA auto-tuning based on model size/architecture
        - Native Chat Template formatting via tokenizer
        - Train/Validation loss evaluation & best checkpoint loading
        - Automated GGUF export (q4_k_m) post-training
        """
        # Clean model name if user accidentally provided a GGUF repo
        clean_model = base_model.replace("-GGUF", "").replace("-gguf", "")
        if "gguf" in base_model.lower():
            clean_model = "Qwen/Qwen3.5-2B" if "2b" in base_model.lower() else "unsloth/Qwen2.5-Coder-7B-Instruct"

        script = f'''#!/usr/bin/env python3
"""
Unsloth High-Speed Cloud GPU Fine-Tuning & GGUF Export Script
Generated automatically for Project: {project_id}
Base Model Target: {clean_model}
"""

import os
from pathlib import Path
import torch
from datasets import Dataset, DatasetDict, load_dataset
from transformers import set_seed
from trl import SFTConfig, SFTTrainer
from unsloth import FastLanguageModel

MODEL_NAME = os.getenv("BASE_MODEL", "{clean_model}")
DATASET_ID = os.getenv("DATASET_ID", "{hf_dataset if hf_dataset else f"onkanat/{project_id}-dataset"}")

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "outputs/{project_id}-sft")
LORA_OUTPUT_DIR = os.getenv("LORA_OUTPUT_DIR", "outputs/{project_id}-lora")
GGUF_OUTPUT_DIR = os.getenv("GGUF_OUTPUT_DIR", "outputs/{project_id}-gguf")

MAX_SEQ_LENGTH = 2048
SEED = 3407
VALIDATION_RATIO = 0.05

set_seed(SEED)

if not torch.cuda.is_available():
    raise RuntimeError("CUDA GPU bulunamadı. Fine-tuning için CUDA destekli bir GPU gereklidir.")

gpu_name = torch.cuda.get_device_name(0)
bf16_supported = torch.cuda.is_bf16_supported()

print(f"🚀 GPU: {{gpu_name}}")
print(f"⚡ BF16 desteği: {{bf16_supported}}")
print(f"📦 Model: {{MODEL_NAME}}")
print(f"📊 Dataset: {{DATASET_ID}}")

def load_training_dataset(dataset_id: str) -> Dataset:
    """Load a Hugging Face dataset or local JSON/JSONL file safely."""
    local_path = Path(dataset_id)
    if local_path.exists():
        if local_path.suffix.lower() not in {{".json", ".jsonl"}}:
            raise ValueError(f"Yerel veri dosyası JSON veya JSONL olmalıdır: {{local_path}}")
        dataset = load_dataset("json", data_files={{"train": str(local_path)}}, split="train")
    else:
        dataset = load_dataset(dataset_id)
        if isinstance(dataset, DatasetDict):
            dataset = dataset["train"] if "train" in dataset else dataset[list(dataset.keys())[0]]
    return dataset

def build_chat_text(example: dict, tokenizer) -> dict:
    """Convert Alpaca schema fields into native Chat Template."""
    instruction = (example.get("instruction") or "").strip()
    user_input = (example.get("input") or "").strip()
    output = (example.get("output") or "").strip()

    user_content = instruction
    if user_input:
        user_content += f"\\n\\n{{user_input}}"

    messages = [
        {{"role": "user", "content": user_content}},
        {{"role": "assistant", "content": output}},
    ]

    try:
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
    except Exception:
        text = f"### Instruction:\\n{{user_content}}\\n\\n### Response:\\n{{output}}"

    return {{"text": text}}

dataset = load_training_dataset(DATASET_ID)

# Auto-detect precision: Small models (e.g. 2B/3B) use BF16 LoRA, larger models use 4-bit QLoRA
is_small_model = "2b" in MODEL_NAME.lower() or "3b" in MODEL_NAME.lower() or "0.5b" in MODEL_NAME.lower()
load_4bit = False if is_small_model else True

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=MODEL_NAME,
    max_seq_length=MAX_SEQ_LENGTH,
    dtype=None,
    load_in_4bit=load_4bit,
    load_in_16bit=not load_4bit,
    full_finetuning=False,
)

model = FastLanguageModel.get_peft_model(
    model,
    r=16,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    lora_alpha=16,
    lora_dropout=0.05,
    bias="none",
    use_gradient_checkpointing="unsloth",
    random_state=SEED,
    max_seq_length=MAX_SEQ_LENGTH,
)

split_dataset = dataset.train_test_split(test_size=VALIDATION_RATIO, seed=SEED, shuffle=True)
train_data = split_dataset["train"].map(lambda x: build_chat_text(x, tokenizer))
eval_data = split_dataset["test"].map(lambda x: build_chat_text(x, tokenizer))

training_args = SFTConfig(
    output_dir=OUTPUT_DIR,
    max_seq_length=MAX_SEQ_LENGTH,
    dataset_text_field="text",
    dataset_num_proc=2,
    per_device_train_batch_size=1 if is_small_model else 2,
    per_device_eval_batch_size=1,
    gradient_accumulation_steps=8 if is_small_model else 4,
    num_train_epochs=3,
    learning_rate=1e-4,
    lr_scheduler_type="cosine",
    warmup_ratio=0.03,
    weight_decay=0.01,
    bf16=bf16_supported,
    fp16=not bf16_supported,
    optim="adamw_8bit",
    logging_steps=10,
    eval_strategy="epoch",
    save_strategy="epoch",
    save_total_limit=2,
    load_best_model_at_end=True,
    metric_for_best_model="eval_loss",
    greater_is_better=False,
    seed=SEED,
    report_to="none",
)

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=train_data,
    eval_dataset=eval_data,
    args=training_args,
)

print(f"📊 Train Örnek Sayısı: {{len(train_data)}} | Validation: {{len(eval_data)}}")
trainer.train()

metrics = trainer.evaluate()
print(f"📈 Final Validation Loss: {{metrics.get('eval_loss', 'N/A')}}")

model.save_pretrained(LORA_OUTPUT_DIR)
tokenizer.save_pretrained(LORA_OUTPUT_DIR)
print(f"✅ LoRA Adapter Kaydedildi: {{LORA_OUTPUT_DIR}}")

if os.getenv("EXPORT_GGUF", "0") == "1":
    print("📦 GGUF Export Başlatılıyor (Quantization: Q4_K_M)...")
    model.save_pretrained_gguf(GGUF_OUTPUT_DIR, tokenizer, quantization_method="q4_k_m")
    print(f"🎉 GGUF Model Kaydedildi: {{GGUF_OUTPUT_DIR}}")
else:
    print("ℹ️ GGUF export atlandı. Export etmek için EXPORT_GGUF=1 ile çalıştırın.")
'''
        return script

    def generate_axolotl_config(self, project_id: str, hf_dataset: str) -> str:
        """
        Generates Axolotl multi-GPU training configuration.
        """
        yaml_config = f"""base_model: Qwen/Qwen3.5-2B
model_type: AutoModelForCausalLM
tokenizer_type: AutoTokenizer

load_in_8bit: false
load_in_4bit: false
strict: false

datasets:
  - path: {hf_dataset if hf_dataset else f'onkanat/{project_id}-dataset'}
    type: alpaca

dataset_prepared_path: last_run_prepared
val_set_size: 0.05
output_dir: ./outputs/axolotl-out

adapter: lora
lora_r: 16
lora_alpha: 16
lora_dropout: 0.05
lora_target_linear: true

sequence_len: 2048
sample_packing: true
pad_to_sequence_len: false

gradient_accumulation_steps: 8
micro_batch_size: 1
num_epochs: 3
optimizer: adamw_bnb_8bit
lr_scheduler: cosine
learning_rate: 0.0001

bf16: auto
fp16: false
tf32: true

gradient_checkpointing: true
early_stopping_patience: 2
flash_attention: true
logging_steps: 10
evals_per_epoch: 1
saves_per_epoch: 1
save_total_limit: 2
"""
        return yaml_config

    def prepare_cloud_payload(self, project_id: str, base_model: str = "Qwen/Qwen3.5-2B", hf_dataset: str = "") -> Dict[str, Any]:
        """
        Prepares cloud GPU offloading package in exports/<project_id>/cloud_payload/
        """
        target_dir = self.exports_dir / project_id / "cloud_payload"
        target_dir.mkdir(parents=True, exist_ok=True)

        unsloth_code = self.generate_unsloth_script(project_id, base_model, hf_dataset)
        axolotl_code = self.generate_axolotl_config(project_id, hf_dataset)

        unsloth_file = target_dir / "unsloth_finetune.py"
        axolotl_file = target_dir / "axolotl_config.yaml"

        with open(unsloth_file, "w", encoding="utf-8") as f:
            f.write(unsloth_code)

        with open(axolotl_file, "w", encoding="utf-8") as f:
            f.write(axolotl_code)

        runpod_bash = f"""#!/usr/bin/env bash
# Qwen3.5 / Unsloth High-Speed Cloud GPU Launcher
# Generated for Project: {project_id}

set -euo pipefail

export PYTHONUNBUFFERED=1
export TOKENIZERS_PARALLELISM=false
export HF_HOME="${{HF_HOME:-$HOME/.cache/huggingface}}"

echo "🚀 Cloud GPU Fine-Tuning Ortamı Hazırlanıyor..."

if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "❌ nvidia-smi bulunamadı. CUDA destekli NVIDIA GPU gereklidir."
    exit 1
fi

echo "GPU Bilgisi:"
nvidia-smi

echo "Unsloth ve Transformers v5 bağımlılıkları kuruluyor..."
python -m pip install --upgrade pip setuptools wheel
python -m pip install --upgrade --force-reinstall --no-cache-dir unsloth unsloth_zoo
python -m pip install --upgrade --no-cache-dir "transformers>=5.0.0" trl datasets accelerate peft bitsandbytes

echo "🎯 Fine-Tuning Başlatılıyor..."
python unsloth_finetune.py
"""
        runpod_file = target_dir / "run_cloud_gpu.sh"
        with open(runpod_file, "w", encoding="utf-8") as f:
            f.write(runpod_bash)

        return {
            "status": "success",
            "project_id": project_id,
            "payload_dir": str(target_dir),
            "generated_files": ["unsloth_finetune.py", "axolotl_config.yaml", "run_cloud_gpu.sh"]
        }
