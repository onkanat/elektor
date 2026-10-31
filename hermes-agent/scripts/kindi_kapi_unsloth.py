#!/usr/bin/env python3
"""Kapi — egitilmis adaptor, UNSLOTH yukleyicisiyle (ad eslesmesi icin sart).

Duz `peft.PeftModel.from_pretrained` Unsloth'un kaydettigi anahtar adlariyla
eslesmiyor ("Found missing adapter keys" -> adaptor ETKISIZ, temel model olculur).
Bu betik modeli Unsloth ile acar, 20 gorevi kosar, kindi_kapi.py'nin programatik
puaniyla degerlendirir.

    E:\\egitim\\venv-unsloth\\Scripts\\python.exe kindi_kapi_unsloth.py ^
        --model C:/models/Ornith-1.5-9B --adapter E:/egitim/cikti/kindi-v1 ^
        --rapor E:/egitim/kapi_v1_unsloth.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time

import torch
from unsloth import FastLanguageModel

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("kk", os.path.join(HERE, "kindi_kapi.py"))
kk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kk)


def tool_call_ayikla(text: str) -> list[dict]:
    """<tool_call>…</tool_call> ya da düz JSON bloğundan araç çağrısı çıkarır."""
    import re
    bloklar = re.findall(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", text, re.S)
    if not bloklar:
        m = re.search(r'\{[^{}]*"name"\s*:[^{}]*\}', text, re.S)
        bloklar = [m.group(0)] if m else []
    out = []
    for b in bloklar:
        try:
            o = json.loads(b)
        except Exception:  # noqa: BLE001
            continue
        ad = o.get("name") or (o.get("function") or {}).get("name")
        arg = o.get("arguments") or (o.get("function") or {}).get("arguments") or {}
        if isinstance(arg, str):
            try:
                arg = json.loads(arg)
            except Exception:  # noqa: BLE001
                arg = {}
        out.append({"function": {"name": ad, "arguments": arg}})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="C:/models/Ornith-1.5-9B")
    ap.add_argument("--adapter", default="")
    ap.add_argument("--gorevler", default=os.path.join(HERE, "kindi_gorev_seti.jsonl"))
    ap.add_argument("--rapor", default="")
    ap.add_argument("--max-new", type=int, default=400)
    args = ap.parse_args()

    t0 = time.time()
    model, tok = FastLanguageModel.from_pretrained(
        model_name=args.model, max_seq_length=4096, load_in_4bit=True,
        dtype=None, trust_remote_code=True)
    # Unsloth kaydini kendi yukleyicisiyle birlestir
    if args.adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, args.adapter)
    FastLanguageModel.for_inference(model)
    model.eval()
    # fast_tokenizer: Unsloth'un dondurdugu nesne bir PROCESSOR'dur; duz string
    # verilince metni gorsel sanip decode etmeye calisir ("Unsupported image file").
    ftok = getattr(tok, "tokenizer", tok)
    print(f"model+adaptor (unsloth): {time.time()-t0:.1f} s | VRAM "
          f"{torch.cuda.memory_allocated()/1e9:.2f} GB", flush=True)

    gorevler = [json.loads(x) for x in open(args.gorevler, encoding="utf-8") if x.strip()]
    sonuc, gecti, sureler = [], 0, []
    for g in gorevler:
        msgs = [{"role": "system", "content": kk.SYS_V2}, {"role": "user", "content": g["prompt"]}]
        prompt = tok.apply_chat_template(msgs, tools=kk.TOOLS, tokenize=False,
                                         add_generation_prompt=True)
        ids = ftok(prompt, return_tensors="pt").to(model.device)
        t1 = time.time()
        with torch.no_grad():
            out = model.generate(**ids, max_new_tokens=args.max_new, do_sample=False,
                                 pad_token_id=ftok.eos_token_id)
        dt = time.time() - t1
        text = ftok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
        calls = kk.tool_calls_ayikla(text)
        yanit = {"message": {"content": "" if calls else text, "tool_calls": calls}}
        ok, neden, detay = kk.puanla(g, yanit)
        gecti += ok
        sureler.append(dt)
        sonuc.append({"id": g["id"], "kategori": g["kategori"], "ok": ok, "neden": neden,
                      "sure_s": round(dt, 2), "detay": detay, "ham": text[:200]})
        print(f"{'GECTI' if ok else 'KALDI'} {g['id']:4s} {g['kategori']:8s} {dt:5.1f}s  {neden}", flush=True)

    n = len(sonuc)
    rapor = {"model": args.model, "adapter": args.adapter, "gorev": n, "gecti": gecti,
             "skor": f"{gecti}/{n} ({100*gecti/n:.0f}%)",
             "ortalama_sure_s": round(sum(sureler)/max(n, 1), 2), "sonuclar": sonuc}
    print(f"\nSKOR (unsloth adaptor): {rapor['skor']} | ort {rapor['ortalama_sure_s']} s", flush=True)
    if args.rapor:
        with open(args.rapor, "w", encoding="utf-8") as fh:
            json.dump(rapor, fh, ensure_ascii=False, indent=2)
        print("rapor:", args.rapor, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
