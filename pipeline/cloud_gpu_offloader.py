import json
from pathlib import Path
from typing import Dict, Any

class CloudGPUOffloader:
    def __init__(self, exports_dir: str = "exports"):
        self.exports_dir = Path(exports_dir)

    def generate_unsloth_script(self, project_id: str, base_model: str, hf_dataset: str) -> str:
        """
        Generates a 5x faster Unsloth fine-tuning script for high-speed Cloud GPU offloading (RunPod / Modal / H100).
        """
        script = f"""# Unsloth High-Speed Cloud GPU Fine-Tuning Script
# Generated automatically for Project: {project_id}

import torch
from unsloth import FastLanguageModel
from datasets import load_dataset
from trl import SFTTrainer
from transformers import TrainingArguments

max_seq_length = 2048
dtype = None # Auto detection (Float16 / Bfloat16)
load_in_4bit = True # 4bit quantization for fast VRAM offloading

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="{base_model}",
    max_seq_length=max_seq_length,
    dtype=dtype,
    load_in_4bit=load_in_4bit,
)

# Target LoRA adapters
model = FastLanguageModel.get_peft_model(
    model,
    r=16,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    lora_alpha=16,
    lora_dropout=0,
    bias="none",
    use_gradient_checkpointing="unsloth",
    random_state=3407,
)

# Load dataset from Hugging Face or local JSONL
dataset_path = "{hf_dataset}" if "{hf_dataset}" else "tr_code_sft_dataset.jsonl"
dataset = load_dataset("json", data_files=dataset_path, split="train")

def formatting_prompts_func(examples):
    instructions = examples["instruction"]
    inputs       = examples["input"]
    outputs      = examples["output"]
    texts = []
    for inst, inp, out in zip(instructions, inputs, outputs):
        text = f"### Instruction:\\n{{inst}}\\n\\n### Input:\\n{{inp}}\\n\\n### Response:\\n{{out}}"
        texts.append(text)
    return {{ "text" : texts }}

dataset = dataset.map(formatting_prompts_func, batched=True)

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
    dataset_text_field="text",
    max_seq_length=max_seq_length,
    dataset_num_proc=2,
    packing=False,
    args=TrainingArguments(
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        warmup_steps=5,
        max_steps=60,
        learning_rate=2e-4,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        logging_steps=1,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="linear",
        seed=3407,
        output_dir="outputs",
    ),
)

trainer_stats = trainer.train()

# Save LoRA model
model.save_pretrained("lora_model")
tokenizer.save_pretrained("lora_model")
print("✅ Fine-tuning completed! LoRA adapter saved to lora_model/")
"""
        return script

    def generate_axolotl_config(self, project_id: str, hf_dataset: str) -> str:
        """
        Generates Axolotl multi-GPU training configuration.
        """
        yaml_config = f"""base_model: unsloth/Qwen2.5-Coder-7B-Instruct
model_type: AutoModelForCausalLM
tokenizer_type: AutoTokenizer

load_in_8bit: false
load_in_4bit: true
strict: false

datasets:
  - path: {hf_dataset if hf_dataset else 'tr_code_sft_dataset.jsonl'}
    type: alpaca

dataset_prepared_path: last_run_prepared
val_set_size: 0.05
output_dir: ./outputs/axolotl-out

adapter: lora
lora_r: 16
lora_alpha: 32
lora_dropout: 0.05
lora_target_linear: true

sequence_len: 2048
sample_packing: true
pad_to_sequence_len: true

gradient_accumulation_steps: 4
micro_batch_size: 2
num_epochs: 3
optimizer: adamw_torch
lr_scheduler: cosine
learning_rate: 0.0002

bf16: auto
fp16: false
tf32: false

gradient_checkpointing: true
early_stopping_patience:
local_rank:
logging_steps: 1
xformers_attention:
flash_attention: true

warmup_steps: 10
evals_per_epoch: 1
saves_per_epoch: 1
debug:
deepspeed:
weight_decay: 0.0
fsdp:
fsdp_config:
special_tokens:
"""
        return yaml_config

    def prepare_cloud_payload(self, project_id: str, base_model: str = "unsloth/Qwen2.5-Coder-7B-Instruct", hf_dataset: str = "") -> Dict[str, Any]:
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

        runpod_bash = f"""#!/bin/bash
# RunPod / Cloud GPU One-Click Fine-Tuning Execution Script
echo "🚀 Installing Fine-Tuning Dependencies..."
pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"
pip install --no-deps "xformers<0.0.27" "trl<0.9.0" peft accelerate bitsandbytes
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
