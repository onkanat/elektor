import json
import sys

from transformers import AutoTokenizer

MODEL = sys.argv[1] if len(sys.argv) > 1 else "E:/models/Ornith-1.5-9B"
DATA = sys.argv[2] if len(sys.argv) > 2 else "E:/egitim/veri/agentic_macair_train.jsonl"

tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
row = json.loads(open(DATA, encoding="utf-8").readline())
tools = row["tools"]
msgs = row["messages"][:3]

variants = {
    "openai_list": tools,
    "function_list": [t["function"] for t in tools],
    "dict_by_name": {t["function"]["name"]: t["function"] for t in tools},
    "none": None,
}

for name, t in variants.items():
    try:
        if t is None:
            out = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
        else:
            out = tok.apply_chat_template(msgs, tools=t, tokenize=False, add_generation_prompt=False)
        print(f"{name:14s} OK   {len(out)} karakter | ilk 120: {out[:120]!r}")
    except Exception as exc:  # noqa: BLE001
        print(f"{name:14s} HATA {type(exc).__name__}: {str(exc)[:90]}")

print("\n--- sablonun tools bolumu ---")
tmpl = tok.chat_template or ""
idx = tmpl.find("tools")
print(tmpl[max(0, idx - 200): idx + 500] if idx >= 0 else "(tools gecmiyor)")
