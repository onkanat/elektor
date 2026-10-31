#!/usr/bin/env python3
"""Kindi LoRA egitimi — UNSLOTH yolu (ECE_PC, 3.12 venv-unsloth).

Neden ayri betik: duz PEFT/TRL yolunda `qwen3_5` hibrit katmanlari Windows'ta
referans (yavas) cekirdeklere dusuyor ve adim basina dakikalar harciyor.
Unsloth kendi Triton cekirdeklerini getiriyor; ayni veri/betik mantigiyla
karsilastirma yapabilmek icin metin hazirligini train_lora.py'den AYNEN alir.

    E:\\egitim\\venv-unsloth\\Scripts\\python.exe train_unsloth.py ^
        --model E:/models/Ornith-1.5-9B --train E:/egitim/veri/agentic_train_all.jsonl ^
        --out E:/egitim/cikti/kindi-unsloth --max-steps 10 --limit 80
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time

import torch

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("tl", os.path.join(HERE, "train_lora.py"))
tl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tl)  # load_rows + to_text yeniden kullanilir

from unsloth import FastLanguageModel  # noqa: E402
from trl import SFTConfig, SFTTrainer  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="E:/models/Ornith-1.5-9B")
    ap.add_argument("--train", required=True)
    ap.add_argument("--val", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--max-len", type=int, default=4096)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--accum", type=int, default=8)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--max-steps", type=int, default=-1)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    print(f"torch {torch.__version__} | cuda {torch.cuda.is_available()} | "
          f"gpu {os.environ.get('CUDA_VISIBLE_DEVICES', 'hepsi')}", flush=True)

    t0 = time.time()
    model, tok = FastLanguageModel.from_pretrained(
        model_name=args.model, max_seq_length=args.max_len, load_in_4bit=True,
        dtype=None, trust_remote_code=True)
    print(f"model yuklendi: {time.time()-t0:.1f} s | "
          f"VRAM {torch.cuda.memory_allocated()/1e9:.2f} GB", flush=True)
    model = FastLanguageModel.get_peft_model(
        model, r=args.r, lora_alpha=args.alpha, lora_dropout=0.05, bias="none",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth", random_state=0)
    model.print_trainable_parameters()

    rows = tl.load_rows(args.train)
    if args.limit:
        rows = rows[: args.limit]
    t1 = time.time()
    data = [tl.to_text(tok, r, args.max_len) for r in rows]
    print(f"metne cevirme: {time.time()-t1:.1f} s | {len(data)} satir | "
          f"ort token {sum(d['tokens'] for d in data)/len(data):.0f}", flush=True)

    from datasets import Dataset
    ds = Dataset.from_list([{"text": d["text"]} for d in data])

    cfg = SFTConfig(output_dir=args.out, per_device_train_batch_size=args.batch,
                    gradient_accumulation_steps=args.accum, num_train_epochs=args.epochs,
                    learning_rate=args.lr, lr_scheduler_type="cosine", warmup_steps=0.03,
                    logging_steps=1, save_strategy="no", bf16=True,
                    optim="paged_adamw_8bit", report_to=[], max_steps=args.max_steps,
                    max_length=args.max_len,
                    gradient_checkpointing=True,
                    gradient_checkpointing_kwargs={"use_reentrant": False})
    trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds, processing_class=tok)
    trainer.train()
    model.save_pretrained(args.out)
    tok.save_pretrained(args.out)
    with open(os.path.join(args.out, "egitim_ozet.json"), "w", encoding="utf-8") as fh:
        json.dump({"model": args.model, "train": len(data), "epochs": args.epochs,
                   "max_len": args.max_len, "max_steps": args.max_steps,
                   "sure_s": round(time.time() - t0, 1),
                   "vram_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2)}, fh, indent=2)
    print(f"BITTI -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
