import json
import os
from pathlib import Path
from typing import Dict, Any, List

class CloudGPUOffloader:
    def __init__(self, exports_dir: str = "exports"):
        self.exports_dir = Path(exports_dir)

    def generate_unsloth_script(self, project_id: str, base_model: str, hf_dataset: str, dataset_file: str = "") -> str:
        """
        Generates a production-grade Unsloth fine-tuning script with:
        - Base model validation (Transformers PyTorch repo, avoiding quantized GGUF inputs)
        - BF16 LoRA vs 4-Bit QLoRA auto-tuning based on model size/architecture
        - Robust Hugging Face dataset loader with split/subfile auto-detection
        - Multi-schema field mapper (instruction/prompt/question -> user, output/response/answer -> assistant)
        - Tokenizer pad_token & padding_side safety fixes
        - Train/Validation loss evaluation & best checkpoint loading
        - Automated GGUF export (q4_k_m) & Ollama Modelfile generation post-training
        """
        clean_model = base_model.replace("-GGUF", "").replace("-gguf", "")
        if "gguf" in base_model.lower():
            clean_model = "Qwen/Qwen3.5-2B" if "2b" in base_model.lower() else "unsloth/Qwen2.5-Coder-7B-Instruct"

        script = f'''#!/usr/bin/env python3
"""
Unsloth High-Speed Cloud & Remote GPU Fine-Tuning & GGUF Export Script
Generated automatically for Project: {project_id}
Base Model Target: {clean_model}
Designed for Remote JupyterLab & GPU Servers
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
DATASET_FILE = os.getenv("DATASET_FILE", "{dataset_file}")

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
print(f"⚡ BF16 Desteği: {{bf16_supported}}")
print(f"📦 Model: {{MODEL_NAME}}")
print(f"📊 Dataset: {{DATASET_ID}} (Alt dosya: {{DATASET_FILE if DATASET_FILE else 'otomatik'}})")

def load_training_dataset(dataset_id: str, subfile: str = "") -> Dataset:
    """Load a Hugging Face dataset or local JSON/JSONL file safely with split fallbacks."""
    local_path = Path(dataset_id)
    if local_path.exists():
        if local_path.suffix.lower() not in {{".json", ".jsonl"}}:
            raise ValueError(f"Yerel veri dosyası JSON veya JSONL olmalıdır: {{local_path}}")
        return load_dataset("json", data_files={{"train": str(local_path)}}, split="train")

    # Hugging Face Hub Dataset Loading Logic
    try:
        if subfile and subfile != "auto":
            return load_dataset(dataset_id, data_files=subfile, split="train")
        
        ds = load_dataset(dataset_id)
        if isinstance(ds, DatasetDict):
            # Prefer code_sft, tr_code_sft, sft or train splits
            for pref in ["train", "code_sft", "tr_code_sft", "sft"]:
                if pref in ds:
                    return ds[pref]
            return ds[list(ds.keys())[0]]
        return ds
    except Exception as err:
        print(f"⚠️ Dorudan HF yükleme uyarısı: {{err}}. Alt dosya aranıyor...")
        for target_file in ["code_sft_dataset.jsonl", "tr_code_sft_dataset.jsonl", "sft_dataset.jsonl"]:
            try:
                return load_dataset(dataset_id, data_files=target_file, split="train")
            except Exception:
                continue
        # Fallback to all jsonl files
        return load_dataset(dataset_id, data_files="*.jsonl", split="train")

def build_chat_text(example: dict, tokenizer) -> dict:
    """Convert multi-schema fields (instruction/prompt/question, output/response/answer) into native Chat Template."""
    instruction = (
        example.get("instruction") or
        example.get("prompt") or
        example.get("question") or
        ""
    ).strip()

    user_input = (
        example.get("input") or
        example.get("context") or
        ""
    ).strip()

    output = (
        example.get("output") or
        example.get("response") or
        example.get("answer") or
        example.get("chosen") or
        ""
    ).strip()

    user_content = instruction
    if user_input:
        user_content += f"\\n\\n{{user_input}}"

    if not user_content:
        user_content = "Lütfen aşağıdaki görevi yapın."
    if not output:
        output = "Yanıt mevcut değil."

    messages = [
        {{"role": "user", "content": user_content}},
        {{"role": "assistant", "content": output}},
    ]

    try:
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
    except Exception:
        text = f"### Instruction:\\n{{user_content}}\\n\\n### Response:\\n{{output}}"

    return {{"text": text}}

dataset = load_training_dataset(DATASET_ID, DATASET_FILE)
print(f"✅ Yüklenen Toplam Örnek Sayısı: {{len(dataset)}} | Sütunlar: {{dataset.column_names}}")

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

# Tokenizer Safety Fixes for Qwen3.5 & Batching
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token
tokenizer.padding_side = "right"

model = FastLanguageModel.get_peft_model(
    model,
    r=16,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    lora_alpha=16,
    lora_dropout=0,
    bias="none",
    use_gradient_checkpointing="unsloth",
    random_state=SEED,
    max_seq_length=MAX_SEQ_LENGTH,
)

split_dataset = dataset.train_test_split(test_size=VALIDATION_RATIO, seed=SEED, shuffle=True)
train_data = split_dataset["train"].map(lambda x: build_chat_text(x, tokenizer), remove_columns=dataset.column_names)
eval_data = split_dataset["test"].map(lambda x: build_chat_text(x, tokenizer), remove_columns=dataset.column_names)

training_args = SFTConfig(
    output_dir=OUTPUT_DIR,
    max_seq_length=MAX_SEQ_LENGTH,
    dataset_text_field="text",
    dataset_num_proc=1,
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
    dataset_text_field="text",
    max_seq_length=MAX_SEQ_LENGTH,
    dataset_num_proc=1,
    packing=False,
    args=training_args,
)

print(f"📊 Train Örnek Sayısı: {{len(train_data)}} | Validation: {{len(eval_data)}}")
trainer.train()

metrics = trainer.evaluate()
print(f"📈 Final Validation Loss: {{metrics.get('eval_loss', 'N/A')}}")

model.save_pretrained(LORA_OUTPUT_DIR)
tokenizer.save_pretrained(LORA_OUTPUT_DIR)
print(f"✅ LoRA Adapter Kaydedildi: {{LORA_OUTPUT_DIR}}")

if os.getenv("EXPORT_GGUF", "1") == "1":
    print("📦 GGUF Export Başlatılıyor (Quantization: Q4_K_M)...")
    model.save_pretrained_gguf(GGUF_OUTPUT_DIR, tokenizer, quantization_method="q4_k_m")
    print(f"🎉 GGUF Model Kaydedildi: {{GGUF_OUTPUT_DIR}}")
    
    # Generate Ollama Modelfile for 1-click Ollama import on local server
    modelfile_path = Path(GGUF_OUTPUT_DIR) / "Modelfile"
    gguf_file = f"unsloth.Q4_K_M.gguf"
    modelfile_content = f"""FROM ./{{gguf_file}}
PARAMETER temperature 0.2
PARAMETER top_p 0.95
SYSTEM "Sen kıdemli bir yazılım mimarı ve yapay zekâ kodlama uzmanısın."
"""
    try:
        with open(modelfile_path, "w", encoding="utf-8") as f:
            f.write(modelfile_content)
        print(f"📄 Ollama Modelfile Oluşturuldu: {{modelfile_path}}")
        print(f"💡 Ollama'ya Yüklemek İçin: ollama create {project_id}-custom -f {{modelfile_path}}")
    except Exception as e:
        print(f"Modelfile yazma uyarısı: {{e}}")
else:
    print("ℹ️ GGUF export atlandı. Export etmek için EXPORT_GGUF=1 ile çalıştırın.")
'''
        return script

    def generate_jupyter_notebook(self, project_id: str, base_model: str, hf_dataset: str, dataset_file: str = "") -> dict:
        """
        Generates a 6-cell modular Jupyter Notebook (.ipynb) payload tailored for JupyterLab at http://192.168.1.14:8888/lab
        """
        clean_model = base_model.replace("-GGUF", "").replace("-gguf", "")
        if "gguf" in base_model.lower():
            clean_model = "Qwen/Qwen3.5-2B" if "2b" in base_model.lower() else "unsloth/Qwen2.5-Coder-7B-Instruct"

        ds_target = hf_dataset if hf_dataset else f"onkanat/{project_id}-dataset"

        gguf_dir = f"outputs/{project_id}-gguf"
        notebook_json = {
            "cells": [
                {
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": [
                        f"# ⚡ Qwen3.5-2B Unsloth Fine-Tuning & GGUF Export Notebook\n",
                        f"**Proje Kimliği**: `{project_id}`  \n",
                        f"**Hedef Taban Model**: `{clean_model}` (BF16 Precision)  \n",
                        f"**Veri Seti (Dataset)**: `{ds_target}` (Alt dosya: `{dataset_file if dataset_file else 'otomatik'}`)  \n",
                        f"**JupyterLab Sunucusu**: `http://192.168.1.14:8888/lab`  \n\n",
                        "---"
                    ]
                },
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": [
                        "# 🧪 HÜCRE 1: GPU & CUDA Ortam Kontrolü\n",
                        "!nvidia-smi\n\n",
                        "import torch\n",
                        "print('PyTorch Sürümü:', torch.__version__)\n",
                        "print('CUDA Kullanılabilir:', torch.cuda.is_available())\n",
                        "if torch.cuda.is_available():\n",
                        "    print('GPU Modeli:', torch.cuda.get_device_name(0))\n",
                        "    print('BF16 Desteği (Ampere+):', torch.cuda.is_bf16_supported())\n",
                        "    print('Toplam VRAM (GB):', round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 2))"
                    ]
                },
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": [
                        "# ⚙️ HÜCRE 2: Bağımlılıkların Kurulumu (Unsloth & Transformers v5)\n",
                        "!pip install --upgrade pip setuptools wheel --quiet\n",
                        "!pip install --upgrade --force-reinstall --no-cache-dir unsloth unsloth_zoo --quiet\n",
                        "!pip install --upgrade --no-cache-dir \"transformers>=5.0.0\" trl datasets accelerate peft bitsandbytes --quiet\n",
                        "print('✅ Tüm eğitim kütüphaneleri başarıyla güncellendi!')"
                    ]
                },
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": [
                        "# 📊 HÜCRE 3: Veri Seti Yükleme ve Sütun Doğrulama\n",
                        "from datasets import load_dataset, DatasetDict\n",
                        "from pathlib import Path\n\n",
                        f"DATASET_ID = '{ds_target}'\n",
                        f"DATASET_FILE = '{dataset_file}'\n\n",
                        "def load_training_dataset(dataset_id: str, subfile: str = ''):\n",
                        "    local_path = Path(dataset_id)\n",
                        "    if local_path.exists():\n",
                        "        return load_dataset('json', data_files={'train': str(local_path)}, split='train')\n",
                        "    try:\n",
                        "        if subfile and subfile != 'auto':\n",
                        "            return load_dataset(dataset_id, data_files=subfile, split='train')\n",
                        "        ds = load_dataset(dataset_id)\n",
                        "        if isinstance(ds, DatasetDict):\n",
                        "            for pref in ['train', 'code_sft', 'tr_code_sft', 'sft']:\n",
                        "                if pref in ds: return ds[pref]\n",
                        "            return ds[list(ds.keys())[0]]\n",
                        "        return ds\n",
                        "    except Exception:\n",
                        "        return load_dataset(dataset_id, data_files='*.jsonl', split='train')\n\n",
                        "dataset = load_training_dataset(DATASET_ID, DATASET_FILE)\n",
                        "print(f'✅ Veri seti başarıyla yüklendi! Örnek sayısı: {len(dataset)}')\n",
                        "print('Sütunlar:', dataset.column_names)\n",
                        "print('İlk Örnek Önizleme:', dataset[0])"
                    ]
                },
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": [
                        "# 🚀 HÜCRE 4: Unsloth Model & LoRA Yapılandırması (BF16 LoRA)\n",
                        "import os, torch\n",
                        "from unsloth import FastLanguageModel\n\n",
                        f"MODEL_NAME = '{clean_model}'\n",
                        "MAX_SEQ_LENGTH = 2048\n\n",
                        "is_small_model = any(k in MODEL_NAME.lower() for k in ['2b', '3b', '0.5b'])\n",
                        "load_4bit = False if is_small_model else True\n\n",
                        "model, tokenizer = FastLanguageModel.from_pretrained(\n",
                        "    model_name=MODEL_NAME,\n",
                        "    max_seq_length=MAX_SEQ_LENGTH,\n",
                        "    dtype=None,\n",
                        "    load_in_4bit=load_4bit,\n",
                        "    load_in_16bit=not load_4bit,\n",
                        "    full_finetuning=False,\n",
                        ")\n\n",
                        "if tokenizer.pad_token is None:\n",
                        "    tokenizer.pad_token = tokenizer.eos_token\n",
                        "tokenizer.padding_side = 'right'\n\n",
                        "model = FastLanguageModel.get_peft_model(\n",
                        "    model,\n",
                        "    r=16,\n",
                        "    target_modules=['q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj'],\n",
                        "    lora_alpha=16,\n",
                        "    lora_dropout=0,\n",
                        "    bias='none',\n",
                        "    use_gradient_checkpointing='unsloth',\n",
                        "    random_state=3407,\n",
                        "    max_seq_length=MAX_SEQ_LENGTH,\n",
                        ")\n",
                        "print('✅ Unsloth LoRA modeli hazırlandı!')"
                    ]
                },
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": [
                        "# 🎯 HÜCRE 5: Fine-Tuning Eğitimi ve Değerlendirme (Validation Loss)\n",
                        "from trl import SFTConfig, SFTTrainer\n\n",
                        "def build_chat_text(example: dict, tokenizer) -> dict:\n",
                        "    instruction = (example.get('instruction') or example.get('prompt') or example.get('question') or '').strip()\n",
                        "    user_input = (example.get('input') or example.get('context') or '').strip()\n",
                        "    output = (example.get('output') or example.get('response') or example.get('answer') or example.get('chosen') or '').strip()\n",
                        "    user_content = f'{instruction}\\n\\n{user_input}' if user_input else instruction\n",
                        "    if not user_content: user_content = 'Lütfen aşağıdaki görevi yapın.'\n",
                        "    if not output: output = 'Yanıt mevcut değil.'\n",
                        "    messages = [{'role': 'user', 'content': user_content}, {'role': 'assistant', 'content': output}]\n",
                        "    try:\n",
                        "        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)\n",
                        "    except Exception:\n",
                        "        text = f'### Instruction:\\n{user_content}\\n\\n### Response:\\n{output}'\n",
                        "    return {'text': text}\n\n",
                        "split_dataset = dataset.train_test_split(test_size=0.05, seed=3407, shuffle=True)\n",
                        "train_data = split_dataset['train'].map(lambda x: build_chat_text(x, tokenizer), remove_columns=dataset.column_names)\n",
                        "eval_data = split_dataset['test'].map(lambda x: build_chat_text(x, tokenizer), remove_columns=dataset.column_names)\n\n",
                        f"OUTPUT_DIR = 'outputs/{project_id}-sft'\n",
                        f"LORA_OUTPUT_DIR = 'outputs/{project_id}-lora'\n\n",
                        "training_args = SFTConfig(\n",
                        "    output_dir=OUTPUT_DIR,\n",
                        "    max_seq_length=MAX_SEQ_LENGTH,\n",
                        "    dataset_text_field='text',\n",
                        "    dataset_num_proc=1,\n",
                        "    per_device_train_batch_size=1 if is_small_model else 2,\n",
                        "    per_device_eval_batch_size=1,\n",
                        "    gradient_accumulation_steps=8 if is_small_model else 4,\n",
                        "    num_train_epochs=3,\n",
                        "    learning_rate=1e-4,\n",
                        "    lr_scheduler_type='cosine',\n",
                        "    warmup_ratio=0.03,\n",
                        "    weight_decay=0.01,\n",
                        "    bf16=torch.cuda.is_bf16_supported(),\n",
                        "    fp16=not torch.cuda.is_bf16_supported(),\n",
                        "    optim='adamw_8bit',\n",
                        "    logging_steps=10,\n",
                        "    eval_strategy='epoch',\n",
                        "    save_strategy='epoch',\n",
                        "    save_total_limit=2,\n",
                        "    load_best_model_at_end=True,\n",
                        "    metric_for_best_model='eval_loss',\n",
                        "    greater_is_better=False,\n",
                        "    seed=3407,\n",
                        "    report_to='none',\n",
                        ")\n\n",
                        "trainer = SFTTrainer(\n",
                        "    model=model,\n",
                        "    tokenizer=tokenizer,\n",
                        "    train_dataset=train_data,\n",
                        "    eval_dataset=eval_data,\n",
                        "    dataset_text_field='text',\n",
                        "    max_seq_length=MAX_SEQ_LENGTH,\n",
                        "    dataset_num_proc=1,\n",
                        "    packing=False,\n",
                        "    args=training_args,\n",
                        ")\n\n",
                        "print('🔥 Fine-Tuning Eğitimi Başlatılıyor...')\n",
                        "trainer.train()\n\n",
                        "metrics = trainer.evaluate()\n",
                        "print('📈 Final Validation Loss:', metrics.get('eval_loss', 'N/A'))\n\n",
                        "model.save_pretrained(LORA_OUTPUT_DIR)\n",
                        "tokenizer.save_pretrained(LORA_OUTPUT_DIR)\n",
                        "print(f'✅ LoRA Adapter Kaydedildi: {LORA_OUTPUT_DIR}')"
                    ]
                },
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": [
                        "# 📦 HÜCRE 6: GGUF (Q4_K_M) Export ve Ollama Modelfile Üretimi\n",
                        f"GGUF_OUTPUT_DIR = '{gguf_dir}'\n",
                        "print('📦 GGUF Export Başlatılıyor (Quantization: Q4_K_M)...')\n",
                        "model.save_pretrained_gguf(GGUF_OUTPUT_DIR, tokenizer, quantization_method='q4_k_m')\n",
                        "print(f'🎉 GGUF Model Başarıyla Kaydedildi: {GGUF_OUTPUT_DIR}')\n\n",
                        "# Modelfile oluşturma\n",
                        "modelfile_content = f'''FROM ./unsloth.Q4_K_M.gguf\n",
                        "PARAMETER temperature 0.2\n",
                        "PARAMETER top_p 0.95\n",
                        "SYSTEM \"Sen kıdemli bir yazılım mimarı ve yapay zekâ kodlama uzmanısın.\"\n",
                        "'''\n",
                        "with open(f'{GGUF_OUTPUT_DIR}/Modelfile', 'w', encoding='utf-8') as f:\n",
                        "    f.write(modelfile_content)\n",
                        "print(f'📄 Ollama Modelfile Oluşturuldu: {GGUF_OUTPUT_DIR}/Modelfile')\n",
                        f"print('💡 Sunucuda çalıştırmak için: ollama create {project_id}-custom -f {gguf_dir}/Modelfile')"
                    ]
                }
            ],
            "metadata": {
                "language_info": {
                    "name": "python"
                }
            },
            "nbformat": 4,
            "nbformat_minor": 2
        }
        return notebook_json

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

    def prepare_cloud_payload(
        self,
        project_id: str,
        base_model: str = "Qwen/Qwen3.5-2B",
        hf_dataset: str = "",
        dataset_file: str = ""
    ) -> Dict[str, Any]:
        """
        Prepares cloud GPU offloading package in exports/<project_id>/cloud_payload/
        Includes Python script, 6-cell Jupyter Notebook (.ipynb), Axolotl YAML, and RunPod shell script.
        """
        target_dir = self.exports_dir / project_id / "cloud_payload"
        target_dir.mkdir(parents=True, exist_ok=True)

        unsloth_code = self.generate_unsloth_script(project_id, base_model, hf_dataset, dataset_file)
        notebook_json = self.generate_jupyter_notebook(project_id, base_model, hf_dataset, dataset_file)
        axolotl_code = self.generate_axolotl_config(project_id, hf_dataset)

        unsloth_file = target_dir / "unsloth_finetune.py"
        notebook_filename = f"unsloth_finetune_{project_id}.ipynb"
        notebook_file = target_dir / notebook_filename
        axolotl_file = target_dir / "axolotl_config.yaml"

        with open(unsloth_file, "w", encoding="utf-8") as f:
            f.write(unsloth_code)

        with open(notebook_file, "w", encoding="utf-8") as f:
            json.dump(notebook_json, f, indent=2, ensure_ascii=False)

        with open(axolotl_file, "w", encoding="utf-8") as f:
            f.write(axolotl_code)

        runpod_bash = f"""#!/usr/bin/env bash
# Qwen3.5 / Unsloth High-Speed GPU Launcher for JupyterLab & Remote GPU
# Generated for Project: {project_id}

set -euo pipefail

export PYTHONUNBUFFERED=1
export TOKENIZERS_PARALLELISM=false
export HF_HOME="${{HF_HOME:-$HOME/.cache/huggingface}}"

echo "🚀 GPU Fine-Tuning Ortamı Hazırlanıyor..."

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

        # Google Vertex AI / Gemini Supervised Fine-Tuning Recipe
        vertex_config = {
            "tuning_job_name": f"{project_id}-gemini-sft",
            "base_model": "gemini-2.5-flash",
            "training_dataset_uri": f"gs://elektor-datasets/{project_id}/sft_dataset.jsonl",
            "validation_dataset_uri": f"gs://elektor-datasets/{project_id}/validation_dataset.jsonl",
            "hyperparameters": {
                "epoch_count": 3,
                "learning_rate_multiplier": 1.0,
                "adapter_size": 16
            },
            "export_target": "vertex_model_registry"
        }
        vertex_file = target_dir / "vertex_ai_tuning.json"
        with open(vertex_file, "w", encoding="utf-8") as f:
            json.dump(vertex_config, f, indent=2, ensure_ascii=False)

        return {
            "status": "success",
            "project_id": project_id,
            "payload_dir": str(target_dir),
            "notebook_filename": notebook_filename,
            "generated_files": [
                "unsloth_finetune.py",
                notebook_filename,
                "axolotl_config.yaml",
                "run_cloud_gpu.sh",
                "vertex_ai_tuning.json"
            ]
        }

    # Alias for API consistency
    generate_payload = prepare_cloud_payload
