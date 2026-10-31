#!/usr/bin/env python3
"""HF indirme hizini tek/paralel baglantiyla olcer (ECE_PC, salt okuma)."""
import sys
import threading
import time
import urllib.request

REPO = "ornith-ai/Ornith-1.5-9B"
PATH = "model-00003-of-00004.safetensors"
URL = f"https://huggingface.co/{REPO}/resolve/main/{PATH}"
CHUNK = 40 << 20  # 40 MB per connection


def grab(start: int, size: int, results: list, idx: int) -> None:
    req = urllib.request.Request(URL, headers={"Range": f"bytes={start}-{start + size - 1}"})
    got = 0
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            while True:
                b = resp.read(1 << 20)
                if not b:
                    break
                got += len(b)
    except Exception as e:  # noqa: BLE001
        results[idx] = (got, time.time() - t0, str(e)[:60])
        return
    results[idx] = (got, time.time() - t0, None)


def run(n: int) -> tuple[float, float]:
    results: list = [None] * n
    threads = [threading.Thread(target=grab, args=(i * CHUNK, CHUNK, results, i)) for i in range(n)]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    el = time.time() - t0
    total = sum(r[0] for r in results if r)
    errs = [r[2] for r in results if r and r[2]]
    per = [round(r[0] / max(r[1], 1e-9) / 1e6, 1) for r in results if r]
    print(f"baglanti={n}: toplam {total/1e6:.0f} MB / {el:.1f} s = {total/el/1e6:.1f} MB/s | tek tek: {per}"
          + (f" | HATA: {errs}" if errs else ""), flush=True)
    return total / el, el


if __name__ == "__main__":
    print(f"URL={URL}", flush=True)
    run(1)
    run(4)
    run(1)
    run(8)
