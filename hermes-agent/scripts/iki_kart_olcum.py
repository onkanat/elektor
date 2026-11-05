import json, statistics, threading, time, urllib.request

A = "http://127.0.0.1:11437"  # CUDA_VISIBLE_DEVICES=1 -> kart 1
B = "http://127.0.0.1:11438"  # CUDA_VISIBLE_DEVICES=0 -> kart 0 (masaustu karti)
MODEL = "ornith-1.5:9b"
P = ["Kisa cevap: /tmp nasil temizlenir?", "Kisa cevap: cron nasil denetlenir?",
     "Kisa cevap: yedek yasi nasil olculur?", "Kisa cevap: journalctl ne yapar?"]


def istek(base, prompt):
    body = {"model": MODEL, "stream": False, "think": False,
            "options": {"temperature": 0, "num_predict": 120},
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(base + "/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as fh:
        d = json.load(fh)
    return time.time() - t0, d.get("eval_count", 0)


def olc(etiket, hedefler):
    sonuc = [None] * len(hedefler)

    def kos(i):
        sonuc[i] = istek(hedefler[i], P[i % len(P)] + f" #{i}")

    th = [threading.Thread(target=kos, args=(i,)) for i in range(len(hedefler))]
    t0 = time.time()
    for t in th:
        t.start()
    for t in th:
        t.join()
    duvar = time.time() - t0
    tok = sum(s[1] for s in sonuc if s)
    print(f"{etiket}: duvar {duvar:.1f}s | istekler "
          + ", ".join(f"{s[0]:.1f}" for s in sonuc if s)
          + f" | {tok} token | {tok/duvar:.1f} tok/s")


print("isinma:")
for ad, b in (("kart1(11437)", A), ("kart0(11438)", B)):
    t, _ = istek(b, "merhaba")
    print(f"  {ad}: {t:.1f}s")

olc("kart1 tek istek", [A])
olc("kart0 tek istek", [B])
olc("iki kart, 4 istek (2+2)", [A, A, B, B])
