#!/usr/bin/env python3
"""Belirtilen dosyaya ait noktaları yerel Qdrant koleksiyonundan siler.
Kullanım: .venv/bin/python bin/elektor-vektor-temizle.py "DOSYA.pdf" [id,id,...]
Qdrant yerel depo tek erişimli olduğu için embed koşusu durdurulmuş olmalı."""
import sys, json, datetime
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

ROOT = "/home/onkanat/Git/elektor"
COL = "macair_teknik_articles"
LOG = f"{ROOT}/logs/vektor-temizle.log"

def yaz(m):
    s = datetime.datetime.now().isoformat(timespec="seconds") + " " + m
    print(s)
    with open(LOG, "a") as f:
        f.write(s + "\n")

dosya = sys.argv[1]
ids = []
if len(sys.argv) > 2 and sys.argv[2].strip():
    ids = [int(x) for x in sys.argv[2].split(",") if x.strip()]

c = QdrantClient(path=f"{ROOT}/qdrant_macair-teknik")
once = c.get_collection(COL).points_count
yaz(f"başlangıç nokta={once} hedef_dosya={dosya} hedef_id={ids}")

pts, _ = c.scroll(COL, limit=1, with_payload=True)
yaz(f"payload anahtarları: {sorted(pts[0].payload.keys()) if pts else yok}")

adaylar = []
for key in ("filename", "source_file", "file", "dosya"):
    adaylar.append((f"{key}={dosya}", qm.Filter(must=[qm.FieldCondition(key=key, match=qm.MatchValue(value=dosya))])))
for key in ("article_id", "id", "articleId"):
    if ids:
        adaylar.append((f"{key} in {ids}", qm.Filter(must=[qm.FieldCondition(key=key, match=qm.MatchAny(any=ids))])))

silinen = 0
for ad, f in adaylar:
    try:
        n = c.count(COL, count_filter=f, exact=True).count
    except Exception as e:
        yaz(f"{ad} -> sorgu hatası: {e}")
        continue
    yaz(f"{ad} -> {n} nokta")
    if n:
        c.delete(COL, points_selector=qm.FilterSelector(filter=f))
        silinen += n

yaz(f"silinen toplam={silinen} · sonra nokta={c.get_collection(COL).points_count}")
