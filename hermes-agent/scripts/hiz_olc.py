import json, sys, time, urllib.request

BASE = "http://192.168.1.26:11434"
TOOLS = [
 {"type":"function","function":{"name":"disk_usage","description":"dizin boyutu","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},
 {"type":"function","function":{"name":"cron_health","description":"cron durumu","parameters":{"type":"object","properties":{"since_hours":{"type":"integer"}},"required":[]}}},
 {"type":"function","function":{"name":"notify","description":"ajana haber","parameters":{"type":"object","properties":{"machine":{"type":"string"},"message":{"type":"string"}},"required":["machine"]}}},
]
SYS = ("Sen evdeki kucuk ajansin. Istegi TEK arac cagrisiyla karsila; aciklama yazma.")
GOREVLER = [
    "/tmp ne kadar yer kaplıyor, bak",
    "son 24 saatte hata veren cron işi var mı",
    "aikonsol'e '/tmp temizlendi' diye haber ver",
]


def cagir(model, prompt, tools=True):
    body = {"model": model, "stream": False, "think": False,
            "options": {"temperature": 0, "num_predict": 300},
            "messages": [{"role": "system", "content": SYS}, {"role": "user", "content": prompt}]}
    if tools:
        body["tools"] = TOOLS
    req = urllib.request.Request(BASE + "/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as fh:
        d = json.load(fh)
    dt = time.time() - t0
    ec = d.get("eval_count", 0)
    ed = d.get("eval_duration", 1) / 1e9
    pc = d.get("prompt_eval_count", 0)
    pd = d.get("prompt_eval_duration", 1) / 1e9
    ld = d.get("load_duration", 0) / 1e9
    calls = (d.get("message") or {}).get("tool_calls") or []
    ad = calls[0]["function"]["name"] if calls else None
    return dt, ec, ec / max(ed, 1e-9), pc, pc / max(pd, 1e-9), ld, ad


for model in sys.argv[1:]:
    print(f"=== {model} ===")
    # isinma
    dt, *_ = cagir(model, "merhaba", tools=False)
    print(f"  isinma: {dt:.1f} s")
    sureler, adlar = [], []
    for g in GOREVLER:
        dt, ec, tps, pc, pps, ld, ad = cagir(model, g)
        sureler.append(dt)
        adlar.append(ad)
        print(f"  {dt:5.1f}s | decode {tps:5.1f} tok/s | prefill {pps:6.1f} tok/s | "
              f"yukleme {ld:4.1f}s | cagri: {ad}")
    print(f"  ORTALAMA: {sum(sureler)/len(sureler):.2f} s/gorev | cagrilar: {adlar}")
