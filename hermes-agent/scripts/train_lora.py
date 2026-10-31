#!/usr/bin/env python3
"""Kindi ajan LoRA (QLoRA) egitimi — ECE_PC, PEFT + TRL.

Girdi: hermes_agentic_export.py ciktisi (satir basina bir yorunge; `tools` +
`messages`). Yorunge `tokenizer.apply_chat_template(..., tools=...)` ile metne
cevrilir; cok uzun yorungelerde ORTADAKI arac sonuclari kisaltilir (ilk cagrilar
ve nihai yanit korunur — ogrenilmesi gereken sinyal orada).

Kullanim (Windows, ECE_PC):
    set CUDA_VISIBLE_DEVICES=1
    E:\\egitim\\venv\\Scripts\\python.exe train_lora.py ^
        --model E:/models/Ornith-1.5-9B ^
        --train exports/hermes_agentic/train/agentic_dataset.jsonl ^
        --val exports/hermes_agentic/val/agentic_dataset.jsonl ^
        --out E:/egitim/cikti/kindi-v1 --epochs 2 --max-len 4096
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import (AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig,
                          TrainingArguments)
from trl import SFTConfig, SFTTrainer

TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def load_rows(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _say(tok, text: str) -> int:
    """Token sayisi. Qwen3.5 gibi VLM'lerde `tok` bir PROCESSOR'dur: duz string
    verilince onu gorsel URL'i sanip decode etmeye calisiyor (Unsloth yolunda
    'Unsupported image file' hatasi). Once alt tokenizer'a in."""
    inner = getattr(tok, "tokenizer", None) or tok
    try:
        return len(inner(text)["input_ids"])
    except Exception:  # noqa: BLE001
        return len(inner.encode(text))


def normalize_calls(msgs: list[dict]) -> list[dict]:
    """Chat sablonu `arguments` alanini SOZLUK bekler (JSON metni degil)."""
    out = []
    for m in msgs:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            m = dict(m)
            calls = []
            for c in m["tool_calls"]:
                fn = c.get("function", c)
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:  # noqa: BLE001
                        args = {"_raw": args}
                calls.append({"name": fn.get("name"), "arguments": args})
            m["tool_calls"] = calls
        out.append(m)
    return out


def to_text(tok, row: dict, max_len: int) -> dict:
    msgs = normalize_calls(row["messages"])
    # Yalniz bu yorungede KULLANILAN araclarin semasini ver: 39 aracin tamami
    # her satira ~3-4k token ekliyor ve baglami yiyor.
    kullanilan = {c["name"] for m in msgs if m.get("tool_calls") for c in m["tool_calls"]}
    tools = [t for t in (row.get("tools") or []) if t["function"]["name"] in kullanilan] or None
    def render(ms):
        try:
            return tok.apply_chat_template(ms, tools=tools, tokenize=False, add_generation_prompt=False)
        except Exception:
            return tok.apply_chat_template(ms, tokenize=False, add_generation_prompt=False)

    text = render(msgs)
    n = _say(tok, text)
    if n <= max_len:
        return {"text": text, "tokens": n, "kisaltildi": 0}

    # Ortadaki tool sonuclarini kisalt: ilk 3 ve son 3 mesaj aynen kalir.
    trimmed = 0
    for i in range(3, len(msgs) - 3):
        if msgs[i]["role"] == "tool" and len(msgs[i]["content"]) > 200:
            msgs[i] = dict(msgs[i])
            msgs[i]["content"] = msgs[i]["content"][:160] + " [... kisaltildi ...]"
            trimmed += 1
    text = render(msgs)
    n = _say(tok, text)

    # Hala uzunsa ORTADAN MESAJ DUSUR (ilk 3 + son 3 korunur). Sondan kirpmak
    # nihai yaniti siler; ogrenilmesi gereken sinyal tam olarak o.
    # Verim: her turda ortadaki mesajlarin en buyuk %30'unu birden dusur
    # (tek tek dusurmek satir basina ~0,6 s yiyordu).
    while n > max_len and len(msgs) > 8:
        ort_idx = list(range(3, len(msgs) - 3))
        if not ort_idx:
            break
        ort_idx.sort(key=lambda k: len(msgs[k].get("content") or ""), reverse=True)
        at = max(1, int(len(ort_idx) * 0.3))
        atilacak = set(ort_idx[:at])
        msgs = [m for i, m in enumerate(msgs) if i not in atilacak]
        text = render(msgs)
        n = _say(tok, text)
        trimmed += at
    return {"text": text, "tokens": n, "kisaltildi": trimmed}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="E:/models/Ornith-1.5-9B")
    ap.add_argument("--train", required=True)
    ap.add_argument("--val", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--max-len", type=int, default=6144)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--accum", type=int, default=8)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--max-steps", type=int, default=-1)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print(f"torch {torch.__version__} | cuda {torch.cuda.is_available()} | visible "
          f"{os.environ.get('CUDA_VISIBLE_DEVICES', 'hepsi')}", flush=True)

    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    tr_rows = load_rows(args.train)
    if args.limit:
        tr_rows = tr_rows[: args.limit]
    print(f"egitim yorungesi: {len(tr_rows)}", flush=True)
    t0 = time.time()
    tr = [to_text(tok, r, args.max_len) for r in tr_rows]
    kirp = sum(1 for r in tr if r["kisaltildi"])
    print(f"metne cevirme: {time.time()-t0:.1f} s | kisaltilan: {kirp} | "
          f"ort token {sum(r['tokens'] for r in tr)/len(tr):.0f} | "
          f"tavana dayanan: {sum(1 for r in tr if r['tokens'] >= args.max_len)}", flush=True)
    if args.dry_run:
        print("ornek (ilk 400 karakter):", tr[0]["text"][:400].replace("\n", " "), flush=True)
        return 0

    # --- yapilandirma ONCE kurulur: model yukleme 13 dk suruyor, yapilandirma
    # hatasi o maliyeti odemeden gorulmeli.
    kw = dict(output_dir=args.out, per_device_train_batch_size=args.batch,
              gradient_accumulation_steps=args.accum, num_train_epochs=args.epochs,
              learning_rate=args.lr, lr_scheduler_type="cosine", warmup_steps=0.03,
              logging_steps=5, save_strategy="no", eval_strategy="no",
              bf16=True, optim="paged_adamw_8bit", report_to=[], max_steps=args.max_steps,
              gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False})
    try:
        targs = SFTConfig(**kw, max_length=args.max_len)
    except TypeError as exc:
        raise SystemExit(f"SFTConfig hatasi: {exc}") from exc
    print(f"SFTConfig: max_length={args.max_len} | epochs={args.epochs} | "
          f"batch={args.batch}x{args.accum}", flush=True)

    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
    model = AutoModelForCausalLM.from_pretrained(args.model, quantization_config=bnb,
                                                 device_map={"": 0}, trust_remote_code=True)
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    lora = LoraConfig(r=args.r, lora_alpha=args.alpha, lora_dropout=0.05,
                      target_modules=TARGETS, bias="none", task_type="CAUSAL_LM")
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    ds_tr = Dataset.from_list([{"text": r["text"]} for r in tr])
    ds_va = None
    if args.val:
        va_rows = load_rows(args.val)[:200]
        ds_va = Dataset.from_list([{"text": to_text(tok, r, args.max_len)["text"]} for r in va_rows])


    trainer = SFTTrainer(model=model, args=targs, train_dataset=ds_tr,
                         eval_dataset=ds_va, processing_class=tok)
    trainer.train()
    trainer.save_model(args.out)
    tok.save_pretrained(args.out)
    with open(os.path.join(args.out, "egitim_ozet.json"), "w", encoding="utf-8") as fh:
        json.dump({"model": args.model, "train": len(tr), "epochs": args.epochs,
                   "max_len": args.max_len, "r": args.r, "alpha": args.alpha,
                   "lr": args.lr, "batch": args.batch, "accum": args.accum,
                   "kisaltilan": kirp, "sure_s": round(time.time() - t0, 1)}, fh, indent=2)
    print(f"BITTI -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
