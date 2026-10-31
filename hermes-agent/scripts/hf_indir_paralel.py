#!/usr/bin/env python3
"""HF deposunu PARALEL aralik istekleriyle indirir (xet yok, bagimlilik yok).

Olcum (ECE_PC, TTNet ~630 Mbps): tek baglanti 17-21 MB/s, 4 baglanti 55 MB/s,
8 baglanti 64 MB/s. Yani kisit tek-baglanti basina; paralel parcali indirme
duvari kaldirir.

    python hf_indir_paralel.py <repo_id> <hedef_dizin> [--baglanti 8] [--parca-mb 16]

Devam edebilir: <dosya>.part + <dosya>.chunks.json (tamamlanan parca listesi).
"""
import json
import os
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API = "https://huggingface.co/api/models/{repo}?blobs=true"
URL = "https://huggingface.co/{repo}/resolve/main/{path}"
LOCK = threading.Lock()


def list_files(repo: str) -> list[dict]:
    with urllib.request.urlopen(API.format(repo=repo), timeout=60) as fh:
        data = json.load(fh)
    return sorted(({"path": s["rfilename"], "size": s.get("size") or 0}
                   for s in data.get("siblings", []) if (s.get("size") or 0)),
                  key=lambda x: -x["size"])


class Sayac:
    def __init__(self, toplam: int, baslangic: int = 0):
        self.toplam = toplam
        self.indirilen = baslangic
        self.t0 = time.time()

    def ekle(self, n: int) -> None:
        with LOCK:
            self.indirilen += n


def parca_indir(url: str, part: str, bas: int, boy: int, sayac: Sayac) -> bool:
    req = urllib.request.Request(url, headers={"Range": f"bytes={bas}-{bas + boy - 1}"})
    for deneme in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp, open(part, "r+b") as out:
                out.seek(bas)
                kalan = boy
                while kalan > 0:
                    b = resp.read(min(1 << 20, kalan))
                    if not b:
                        break
                    out.write(b)
                    kalan -= len(b)
                    sayac.ekle(len(b))
            if kalan == 0:
                return True
        except Exception:  # noqa: BLE001
            if deneme < 2:
                time.sleep(2)
    return False


def dosya_indir(repo: str, f: dict, dest: str, baglanti: int, parca_boy: int) -> bool:
    target = os.path.join(dest, f["path"])
    os.makedirs(os.path.dirname(target) or dest, exist_ok=True)
    if os.path.exists(target) and os.path.getsize(target) == f["size"]:
        print(f"VAR  {f['path']}", flush=True)
        return True
    part = target + ".part"
    state_path = target + ".chunks.json"
    url = URL.format(repo=repo, path=f["path"])
    n_parca = (f["size"] + parca_boy - 1) // parca_boy
    tamam: set[int] = set()
    if os.path.exists(state_path) and os.path.exists(part):
        try:
            tamam = set(json.load(open(state_path)))
        except Exception:  # noqa: BLE001
            tamam = set()
    if not os.path.exists(part) or os.path.getsize(part) != f["size"]:
        tamam = set()
        with open(part, "wb") as fh:
            fh.truncate(f["size"])
    baslangic = sum(min(parca_boy, f["size"] - i * parca_boy) for i in tamam)
    sayac = Sayac(f["size"], baslangic)
    kalan = [i for i in range(n_parca) if i not in tamam]
    print(f"BASLA {f['path']} {f['size']/1e6:.0f} MB | parca={n_parca} kalan={len(kalan)} "
          f"baglanti={baglanti} devam={baslangic/1e6:.0f} MB", flush=True)
    dur = threading.Event()

    def rapor() -> None:
        son = 0
        while not dur.wait(10):
            hiz = (sayac.indirilen - son) / 10 / 1e6
            son = sayac.indirilen
            kalan_mb = (f["size"] - sayac.indirilen) / 1e6
            print(f"  {f['path']}: {sayac.indirilen/1e6:.0f}/{f['size']/1e6:.0f} MB | "
                  f"{hiz:.1f} MB/s | kalan ~{kalan_mb/max(hiz,1e-9)/60:.0f} dk", flush=True)

    threading.Thread(target=rapor, daemon=True).start()

    def isle(i: int) -> bool:
        bas = i * parca_boy
        boy = min(parca_boy, f["size"] - bas)
        ok = parca_indir(url, part, bas, boy, sayac)
        if ok:
            with LOCK:
                tamam.add(i)
                json.dump(sorted(tamam), open(state_path, "w"))
        return ok

    with ThreadPoolExecutor(max_workers=baglanti) as ex:
        sonuclar = list(ex.map(isle, kalan))
    dur.set()
    if not all(sonuclar):
        print(f"HATA {f['path']}: {sonuclar.count(False)} parca inemedi (tekrar kosulabilir)", flush=True)
        return False
    if os.path.getsize(part) != f["size"]:
        print(f"HATA {f['path']}: boyut {os.path.getsize(part)} != {f['size']}", flush=True)
        return False
    # Windows: indirme bitince dosya bir sure baska islem (AV/tarayici) tarafindan
    # tutulabiliyor -> WinError 32. Yeniden adlandirmayi tekrar dene.
    son_hata: Exception | None = None
    for _ in range(12):
        try:
            os.replace(part, target)
            son_hata = None
            break
        except PermissionError as exc:
            son_hata = exc
            time.sleep(3)
    if son_hata is not None:
        print(f"HATA {f['path']}: yeniden adlandirilamadi ({son_hata}); .part yerinde duruyor", flush=True)
        return False
    for s in (state_path,):
        try:
            os.remove(s)
        except OSError:
            pass
    print(f"OK   {f['path']} ({f['size']/1e6:.0f} MB)", flush=True)
    return True


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 64
    repo, dest = sys.argv[1], sys.argv[2]
    baglanti = 8
    parca_mb = 16
    for i, a in enumerate(sys.argv):
        if a == "--baglanti" and i + 1 < len(sys.argv):
            baglanti = int(sys.argv[i + 1])
        if a == "--parca-mb" and i + 1 < len(sys.argv):
            parca_mb = int(sys.argv[i + 1])
    parca_boy = parca_mb << 20
    os.makedirs(dest, exist_ok=True)
    files = list_files(repo)
    toplam = sum(f["size"] for f in files)
    print(f"depo={repo} dosya={len(files)} toplam={toplam/1e9:.2f} GB hedef={dest} "
          f"baglanti={baglanti} parca={parca_mb}MB", flush=True)
    t0 = time.time()
    for f in files:
        if not dosya_indir(repo, f, dest, baglanti, parca_boy):
            return 2
    el = time.time() - t0
    print(f"BITTI toplam={toplam/1e9:.2f} GB sure={el/60:.1f} dk ort={toplam/el/1e6:.1f} MB/s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
