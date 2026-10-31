#!/usr/bin/env python3
import hashlib
import sys

path = sys.argv[1]
beklenen = sys.argv[2] if len(sys.argv) > 2 else ""
h = hashlib.sha256()
n = 0
with open(path, "rb") as fh:
    for b in iter(lambda: fh.read(8 << 20), b""):
        h.update(b)
        n += len(b)
got = h.hexdigest()
print("dosya   :", path)
print("bayt    :", n)
print("yerel   :", got)
if beklenen:
    print("beklenen:", beklenen)
    print("SONUC   :", "ESLESIYOR" if got == beklenen else "FARKLI")
else:
    print("SONUC   : sha hesaplandi (karsilastirma yok)")
