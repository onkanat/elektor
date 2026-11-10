#!/usr/bin/env python
# judge_kiyas.py — A-032 S5: DONMUŞ 20 örnek, taban (gemini) → strata karşılaştırma
# Protokol: MacAir A-032-referans-20261110.md (sha 9761d23e) — SET_SHA256 ec506766…
# Sıra: (i) taban (gemini-2.5-flash) → kanit/A-032-taban.jsonl [commitlenir]
#       (ii) switch (config A-032 ile değişti; judge yolu bağımsız — notta)
#       (iii) aynı 20 strata ile → kanit/A-032-strata.jsonl
#       (iv) tablo: sample_sha | taban | strata | Δ + ortalama Δ + |Δ|≤1 oranı (DONMUŞ eşik:
#            Δ ≥ −1,0 ve oran ≥ %80 → strata kalır; aksi gemini'ye geri)
# Kullanım: python scripts/judge_kiyas.py taban|strata|tablo  [pairs=20]
import hashlib
import json
import sys
from datetime import datetime, timezone
sys.path.insert(0, ".")

FROZEN_SET_SHA = "ec50676668ab57c4e4ea10810daba2aa6c5c60bd68af95aaf8ab75be445e4ab6"
SFT_FILE = "exports/kindi-docs/sft_dataset.jsonl"
OUT_DIR = "/home/hakan/Aikonsol/urunler/elektor/kanit"


def frozen_samples(n=20):
    raw = open(SFT_FILE, "rb").read()
    lines = [l for l in raw.split(b"\n") if l.strip()][:n]
    ids = [hashlib.sha256(l).hexdigest()[:16] for l in lines]
    got = hashlib.sha256("\n".join(ids).encode()).hexdigest()
    assert got == FROZEN_SET_SHA, f"SET_SHA uyuşmadı: {got}"
    return list(zip(ids, (json.loads(l) for l in lines)))


def judge_record(engine, sid, record, model_tag):
    g = engine.evaluate_pair(
        (record.get("instruction") or "") + ("\n\n" + (record.get("input") or "") if (record.get("input") or "") else ""),
        record.get("output") or "",
        record.get("rejected") or None,
        mode="strict",
    )
    return {
        "sample_sha": sid,
        "score": float(g.overall_score),
        "model": model_tag,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "technical_accuracy": float(g.technical_accuracy),
        "logical_consistency": float(g.logical_consistency),
        "turkish_fluency": float(g.turkish_fluency),
        "status": g.status,
    }


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "tablo"
    pairs_n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    samples = frozen_samples(pairs_n)
    cfg = json.load(open("config.json"))
    from pipeline.judge_engine import JudgeEngine

    engine = JudgeEngine(config_or_path="config.json")

    if cmd == "taban":
        with open(f"{OUT_DIR}/A-032-taban.jsonl", "w") as f:
            for sid, rec in samples:
                row = judge_record(engine, sid, rec, "gemini-2.5-flash")
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(f"  taban {sid}: {row['score']}")
        print("taban yazıldı → A-032-taban.jsonl (COMMIT GEREKLİ)")
        return

    if cmd == "strata":
        from pipeline.llm_client import call_llm

        class StrataAdapter:
            config = cfg

            def generate_content(self, prompt, system_instruction, model=None, **_):
                raw = call_llm(self.config, system_instruction,
                               prompt + "\n\nSADECE JSON döndür.",
                               model_override=self.config.get("model_analyzer"))
                try:
                    data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
                    return {"success": True, "json_data": data}
                except Exception:
                    return {"success": False}

        engine.gemini_client = StrataAdapter()
        with open(f"{OUT_DIR}/A-032-strata.jsonl", "w") as f:
            for sid, rec in samples:
                row = judge_record(engine, sid, rec, "qwen3.8-flash-next-q2_0 (judge)")
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(f"  strata {sid}: {row['score']}")
        print("strata yazıldı → A-032-strata.jsonl")
        return

    if cmd == "tablo":
        import statistics as st
        tb = {json.loads(l)["sample_sha"]: json.loads(l)["score"] for l in open(f"{OUT_DIR}/A-032-taban.jsonl")}
        ts = {json.loads(l)["sample_sha"]: json.loads(l)["score"] for l in open(f"{OUT_DIR}/A-032-strata.jsonl")}
        deltas = []
        print(f"{'sample_sha':17} | {'taban':>5} | {'strata':>6} | {'Δ':>6}")
        for sid, rec in samples:
            b, s = tb.get(sid), ts.get(sid)
            if b is None or s is None:
                print(f"{sid:17} | {b} | {s} | EKSİK")
                continue
            d = s - b
            deltas.append(d)
            print(f"{sid:17} | {b:5.1f} | {s:6.1f} | {d:+6.1f}")
        mean_d = st.mean(deltas)
        within1 = 100.0 * sum(1 for d in deltas if abs(d) <= 1) / len(deltas)
        print(f"\nortalama Δ: {mean_d:+.2f} · |Δ|≤1 oranı: {within1:.0f}%")
        ok = (mean_d >= -1.0) and (within1 >= 80)
        print("HÜKÜM (donmuş eşik):", "strata judge KALIR" if ok else "judge_model gemini-2.5-flash'a GERİ")


if __name__ == "__main__":
    main()
