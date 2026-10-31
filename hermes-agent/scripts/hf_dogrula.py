#!/usr/bin/env python3
"""Indirilen HF deposunu dogrular: boyutlar + LFS sha256 (ornekleme veya tumu).

    python hf_dogrula.py <repo_id> <hedef_dizin> [--sha-hepsi|--sha N]
"""
import hashlib
import json
import os
import sys
import time
import urllib.request

API = "https://huggingface.co/api/models/{repo}?blobs=true"


def sha256_file(path: str, blok: int = 8 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(blok)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 64
    repo, dest = sys.argv[1], sys.argv[2]
    mode = sys.argv[3] if len(sys.argv) > 3 else "--sha-ornek"
    with urllib.request.urlopen(API.format(repo=repo), timeout=60) as fh:
        data = json.load(fh)
    eksik = 0
    boyut_hatasi = 0
    toplam = 0
    lfs = []
    for s in data.get("siblings", []):
        path = s["rfilename"]
        beklenen = s.get("size") or 0
        yerel = os.path.join(dest, path.replace("/", os.sep))
        if not os.path.exists(yerel):
            print(f"EKSIK  {path}")
            eksik += 1
            continue
        boyut = os.path.getsize(yerel)
        toplam += boyut
        durum = "OK   " if boyut == beklenen else "BOYUT"
        if boyut != beklenen:
            boyut_hatasi += 1
        print(f"{durum}  {path:52s} {boyut:>15,} / {beklenen:>15,}")
        oid = (s.get("lfs") or {}).get("oid")
        if oid and path.endswith(".safetensors"):
            lfs.append((path, oid, yerel))
    print(f"\ndosya toplam={len(data.get('siblings', []))} eksik={eksik} boyut hatasi={boyut_hatasi} yerel toplam={toplam/1e9:.3f} GB")

    secilen = lfs
    if mode == "--sha-ornek":
        secilen = lfs[-1:]
    elif mode.startswith("--sha="):
        n = int(mode.split("=")[1])
        secilen = lfs[:n]
    elif mode == "--sha-yok":
        secilen = []
    hata = 0
    for path, oid, yerel in secilen:
        t0 = time.time()
        print(f"sha256 hesaplaniyor: {path} ...", end="", flush=True)
        got = sha256_file(yerel)
        el = time.time() - t0
        ok = got == oid
        hata += 0 if ok else 1
        print(f" {'ESLESIYOR' if ok else 'FARKLI'} ({el:.1f} s, {os.path.getsize(yerel)/el/1e6:.0f} MB/s)")
        if not ok:
            print(f"   yerel={got}\n   lfs  ={oid}")
    if eksik or boyut_hatasi or hata:
        print("SONUC: BASARISIZ")
        return 1
    if not secilen:
        print("SONUC: BOYUTLAR TAMAM — sha256 DOGRULANMADI (LFS oid yok; X-Linked-ETag ile ayrica kontrol et)")
        return 0
    print(f"SONUC: TAMAM (boyutlar tamam, {len(secilen)} shard sha256 dogrulandi)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
