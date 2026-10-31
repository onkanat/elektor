#!/usr/bin/env python3
"""HF deposundan dosyalari duz HTTPS ile indirir (xet yok, bagimlilik yok).

Kullanim (ECE_PC):
    python hf_indir.py <repo_id> <hedef_dizin>

Neden: `hf download` bu makinede Xet arka ucunda takildi (0 bayt/sn, 0 CPU).
Bu betik Range ile devam eder, .part -> tam ad yeniden adlandirir, ilerlemeyi
yazar. Kimlik dogrulama gerektirmez (depo gated degil).
"""
import json
import os
import sys
import time
import urllib.request

API = "https://huggingface.co/api/models/{repo}?blobs=true"
URL = "https://huggingface.co/{repo}/resolve/main/{path}"


def list_files(repo: str) -> list[dict]:
    with urllib.request.urlopen(API.format(repo=repo), timeout=60) as fh:
        data = json.load(fh)
    out = []
    for s in data.get("siblings", []):
        size = s.get("size") or 0
        if size:
            out.append({"path": s["rfilename"], "size": size})
    out.sort(key=lambda x: x["size"], reverse=True)
    return out


def download(repo: str, dest: str) -> int:
    os.makedirs(dest, exist_ok=True)
    files = list_files(repo)
    total = sum(f["size"] for f in files)
    done_bytes = 0
    t0 = time.time()
    print(f"depo={repo} dosya={len(files)} toplam={total/1e9:.2f} GB hedef={dest}", flush=True)
    for f in files:
        target = os.path.join(dest, f["path"].replace("/", os.sep))
        os.makedirs(os.path.dirname(target) or dest, exist_ok=True)
        if os.path.exists(target) and os.path.getsize(target) == f["size"]:
            done_bytes += f["size"]
            print(f"VAR  {f['path']} ({f['size']/1e6:.1f} MB)", flush=True)
            continue
        part = target + ".part"
        have = os.path.getsize(part) if os.path.exists(part) else 0
        req = urllib.request.Request(URL.format(repo=repo, path=f["path"]))
        if have:
            req.add_header("Range", f"bytes={have}-")
        with urllib.request.urlopen(req, timeout=120) as resp:
            mode = "ab" if have and resp.status == 206 else "wb"
            if mode == "wb":
                have = 0
            last = time.time()
            got = have
            with open(part, mode) as out:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
                    got += len(chunk)
                    if time.time() - last > 5:
                        el = time.time() - t0
                        rate = (done_bytes + got) / max(el, 1e-9)
                        eta = (total - done_bytes - got) / max(rate, 1e-9)
                        print(f"  {f['path']}: {got/1e6:.0f}/{f['size']/1e6:.0f} MB | "
                              f"genel {rate/1e6:.1f} MB/s | kalan ~{eta/60:.0f} dk", flush=True)
                        last = time.time()
        if os.path.getsize(part) != f["size"]:
            print(f"HATA boyut uyusmuyor: {f['path']} {os.path.getsize(part)} != {f['size']}", flush=True)
            return 2
        os.replace(part, target)
        done_bytes += f["size"]
        print(f"OK   {f['path']} ({f['size']/1e6:.1f} MB)", flush=True)
    el = time.time() - t0
    print(f"BITTI toplam={done_bytes/1e9:.2f} GB sure={el/60:.1f} dk ort={done_bytes/el/1e6:.1f} MB/s", flush=True)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("kullanim: python hf_indir.py <repo_id> <hedef_dizin>", file=sys.stderr)
        sys.exit(64)
    sys.exit(download(sys.argv[1], sys.argv[2]))
