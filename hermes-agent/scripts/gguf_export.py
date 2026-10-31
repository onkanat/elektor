#!/usr/bin/env python3
"""Adaptoru birlestir (16-bit) ve GGUF'a cevir — ollama'ya vermek icin.

Iki adim:
  1) merge: Unsloth `save_pretrained_merged(..., save_method="merged_16bit")`
  2) GGUF: Unsloth `save_pretrained_gguf(..., quantization_method="q4_k_m")`
     (llama.cpp'yi kendi indirir/derler; Windows'ta derleme yoksa indirilen
     hazir binary gerekir — bu yuzden hatayi yakalayip yalniz merge ile doneriz.)

    E:\\egitim\\venv-unsloth\\Scripts\\python.exe gguf_export.py ^
        --model C:/models/Ornith-1.5-9B --adapter E:/egitim/cikti/kindi-v1 ^
        --out E:/egitim/cikti/kindi-gguf
"""
from __future__ import annotations

import argparse
import sys
import time

from unsloth import FastLanguageModel


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="C:/models/Ornith-1.5-9B")
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sadece-merge", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    # Unsloth kurali: LoRA'yi peft ile EKLEME; adaptor klasorunu dogrudan ac.
    # Aksi halde "save method was called on the base model" hatasi verir.
    model, tok = FastLanguageModel.from_pretrained(
        model_name=args.adapter, max_seq_length=4096, load_in_4bit=True,
        dtype=None, trust_remote_code=True)
    print(f"adaptor (unsloth yukleyici) yuklendi: {time.time()-t0:.1f} s", flush=True)

    # 4-bit modeli dogrudan merge edemeyiz: Unsloth dequantize edip birlestirir.
    try:
        model.save_pretrained_merged(args.out + "-merged", tok, save_method="merged_16bit")
        print(f"MERGE OK -> {args.out}-merged ({time.time()-t0:.1f} s)", flush=True)
    except Exception as exc:  # noqa: BLE001
        print("MERGE HATASI:", type(exc).__name__, str(exc)[:300], flush=True)
        return 2

    if args.sadece_merge:
        return 0

    try:
        model.save_pretrained_gguf(args.out, tok, quantization_method="q4_k_m")
        print(f"GGUF OK -> {args.out} ({time.time()-t0:.1f} s)", flush=True)
    except Exception as exc:  # noqa: BLE001
        print("GGUF HATASI:", type(exc).__name__, str(exc)[:400], flush=True)
        print("(merge basarili; GGUF icin llama.cpp binary'si gerekiyor)", flush=True)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
