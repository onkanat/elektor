import json, statistics, threading, time, urllib.request

import sys
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://192.168.1.26:11434"
MODEL = sys.argv[2] if len(sys.argv) > 2 else "ornith-1.5:9b"
PROMPTLAR = [
    "Kisa cevap ver: disk dolulugu nasil olculur?",
    "Kisa cevap ver: cron nedir, ne ise yarar?",
    "Kisa cevap ver: yedek tazeligi neden onemli?",
    "Kisa cevap ver: journalctl ne yapar?",
]


def ps():
    try:
        with urllib.request.urlopen(BASE + "/api/ps", timeout=10) as fh:
            d = json.load(fh)
        for m in d.get("models", []):
            if m["name"].startswith(MODEL.split(":")[0]):
                return round(m.get("size", 0) / 1e9, 2), round(m.get("size_vram", 0) / 1e9, 2), m.get("context_length")
    except Exception:  # noqa: BLE001
        pass
    return None, None, None


def bir(prompt, sonuc, i):
    body = {"model": MODEL, "stream": False, "think": False,
            "options": {"temperature": 0, "num_predict": 120},
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(BASE + "/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as fh:
        d = json.load(fh)
    dt = time.time() - t0
    sonuc[i] = {"sure": dt, "tok": d.get("eval_count", 0),
                "decode_tps": d.get("eval_count", 0) / max(d.get("eval_duration", 1) / 1e9, 1e-9),
                "load_s": d.get("load_duration", 0) / 1e9,
                "prompt_tok": d.get("prompt_eval_count", 0)}


print("model:", MODEL)
print(f"baslangic VRAM: size/vram/ctx = {ps()}")
for n in (1, 2, 3, 4):
    sonuc = [None] * n
    t0 = time.time()
    th = [threading.Thread(target=bir, args=(PROMPTLAR[i % len(PROMPTLAR)] + f" (v{n}-{i})", sonuc, i))
          for i in range(n)]
    for t in th:
        t.start()
    for t in th:
        t.join()
    duvar = time.time() - t0
    sureler = [s["sure"] for s in sonuc]
    toplam_tok = sum(s["tok"] for s in sonuc)
    print(f"\n n={n} | duvar {duvar:5.1f}s | istek basina: "
          + ", ".join(f"{s:.1f}s" for s in sureler))
    print(f"      medyan {statistics.median(sureler):.1f}s | maks {max(sureler):.1f}s | "
          f"toplam {toplam_tok} token | toplam hiz {toplam_tok/duvar:.1f} tok/s | "
          f"istek basi {statistics.mean([s['decode_tps'] for s in sonuc]):.1f} tok/s")
    print(f"      VRAM: {ps()}")
