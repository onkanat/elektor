import json, statistics, threading, time, urllib.request

PORTS = ["http://127.0.0.1:11434", "http://127.0.0.1:11437"]
MODEL = "ornith-1.5:9b"
P = [
    "Kisa cevap ver: /tmp nasil temizlenir?",
    "Kisa cevap ver: cron nasil kontrol edilir?",
    "Kisa cevap ver: yedek tazeligi nasil olculur?",
    "Kisa cevap ver: journalctl ne ise yarar?",
]


def ps(base):
    try:
        with urllib.request.urlopen(base + "/api/ps", timeout=8) as fh:
            d = json.load(fh)
        for m in d.get("models", []):
            return round(m.get("size_vram", 0) / 1e9, 2), m.get("context_length")
    except Exception:  # noqa: BLE001
        pass
    return None, None


def bir(base, prompt, sonuc, i):
    body = {"model": MODEL, "stream": False, "think": False,
            "options": {"temperature": 0, "num_predict": 120},
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(base + "/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as fh:
        d = json.load(fh)
    sonuc[i] = (time.time() - t0, d.get("eval_count", 0), base.split(":")[-1])


print("isinma (iki ornek):")
for b in PORTS:
    t0 = time.time()
    bir(b, "merhaba", [None], 0)
    print(f"  {b}: {time.time()-t0:.1f}s | VRAM {ps(b)}")

for etiket, hedefler in (("2 ornek, 4 istek (2+2)", PORTS * 2),
                         ("tek ornek, 4 istek", [PORTS[0]] * 4)):
    sonuc = [None] * 4
    th = [threading.Thread(target=bir, args=(hedefler[i], P[i], sonuc, i)) for i in range(4)]
    t0 = time.time()
    for t in th:
        t.start()
    for t in th:
        t.join()
    duvar = time.time() - t0
    sureler = [s[0] for s in sonuc]
    tok = sum(s[1] for s in sonuc)
    print(f"\n{etiket}: duvar {duvar:.1f}s | istekler "
          + ", ".join(f"{s:.1f}" for s in sureler)
          + f" | medyan {statistics.median(sureler):.1f}s | toplam {tok} token | {tok/duvar:.1f} tok/s")
    print(f"   VRAM: 11434={ps(PORTS[0])} 11437={ps(PORTS[1])}")
