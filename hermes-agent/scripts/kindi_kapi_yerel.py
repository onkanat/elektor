#!/usr/bin/env python3
"""Kapi — YEREL adaptor ile: temel model + LoRA adaptoru, transformers uzerinde.

GGUF/llama.cpp derlemesi gerekmeden egitilmis modeli olcmek icin. Ayni 20 gorev,
ayni sistem istemi, ayni araclar, ayni programatik puanlama (kindi_kapi.py'den
alinir) — karsilastirma tek degiskenli kalir.

    E:\\egitim\\venv-unsloth\\Scripts\\python.exe kindi_kapi_yerel.py ^
        --model C:/models/Ornith-1.5-9B --adapter E:/egitim/cikti/kindi-v1 ^
        --rapor E:/egitim/kapi_v1.json
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
spec = importlib.util.spec_from_file_location("kk", os.path.join(HERE, "kindi_kapi.py"))
kk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kk)  # TOOLS, SYS_V2, puanla


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="C:/models/Ornith-1.5-9B")
    ap.add_argument("--adapter", default="")
    ap.add_argument("--gorevler", default=os.path.join(HERE, "kindi_gorev_seti.jsonl"))
    ap.add_argument("--rapor", default="")
    ap.add_argument("--max-new", type=int, default=512)
    args = ap.parse_args()

    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
    t0 = time.time()
    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(args.model, quantization_config=bnb,
                                                 device_map={"": 0}, trust_remote_code=True)
    if args.adapter:
        model = PeftModel.from_pretrained(model, args.adapter)
    model.eval()
    print(f"model+adaptor yuklendi: {time.time()-t0:.1f} s | VRAM "
          f"{torch.cuda.memory_allocated()/1e9:.2f} GB", flush=True)

    gorevler = [json.loads(x) for x in open(args.gorevler, encoding="utf-8") if x.strip()]
    sonuc, gecti, sureler = [], 0, []
    for g in gorevler:
        msgs = [{"role": "system", "content": kk.SYS_V2}, {"role": "user", "content": g["prompt"]}]
        # Araclar sablonda 'tools=' ile verilir; model <tool_call> blogu uretir.
        try:
            prompt = tok.apply_chat_template(msgs, tools=kk.TOOLS, tokenize=False,
                                             add_generation_prompt=True)
        except Exception:
            prompt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        ids = tok(prompt, return_tensors="pt").to(model.device)
        t1 = time.time()
        with torch.no_grad():
            out = model.generate(**ids, max_new_tokens=args.max_new, do_sample=False,
                                 pad_token_id=tok.eos_token_id)
        dt = time.time() - t1
        text = tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)

        # <tool_call>{"name":..,"arguments":{..}}</tool_call> ya da JSON blogu
        calls = []
        try:
            if "<tool_call>" in text:
                ic = text.split("<tool_call>")[1].split("</tool_call>")[0].strip()
                o = json.loads(ic)
                calls = [{"function": {"name": o.get("name"), "arguments": o.get("arguments") or {}}}]
        except Exception:
            calls = []
        yanit = {"message": {"content": text if not calls else "", "tool_calls": calls}}
        ok, neden, detay = kk.puanla(g, yanit)
        gecti += ok
        sureler.append(dt)
        sonuc.append({"id": g["id"], "kategori": g["kategori"], "ok": ok, "neden": neden,
                      "sure_s": round(dt, 2), "detay": detay, "ham": text[:160]})
        print(f"{'GECTI' if ok else 'KALDI'} {g['id']:4s} {g['kategori']:8s} {dt:5.1f}s  {neden}", flush=True)

    n = len(sonuc)
    rapor = {"model": args.model, "adapter": args.adapter or None, "gorev": n, "gecti": gecti,
             "skor": f"{gecti}/{n} ({100*gecti/n:.0f}%)",
             "ortalama_sure_s": round(sum(sureler) / max(n, 1), 2), "sonuclar": sonuc}
    print(f"\nSKOR (yerel adaptor): {rapor['skor']} | ort {rapor['ortalama_sure_s']} s", flush=True)
    if args.rapor:
        with open(args.rapor, "w", encoding="utf-8") as fh:
            json.dump(rapor, fh, ensure_ascii=False, indent=2)
        print("rapor:", args.rapor, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
