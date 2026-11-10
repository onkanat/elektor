# tests/test_token_layer.py — FAZ-24: token katmanı birim testleri (şartname K1 sözleşmesi)
# Offline: gerçek HF tokenizer'a ağ erişimi YOK — deterministik sahte tokenizer kullanılır.
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.token_layer import (  # noqa: E402
    encode_dpo,
    encode_multiturn,
    encode_sft,
    load_tokenizer,
)


class FakeTokenizer:
    """apply_chat_template sözleşmesini sağlayan deterministik sahte tokenizer.

    token akışı = mesaj başına 1 rol-id + içerik başına ~1 int (4 karakterde 1,
    deterministik, toplamda sıralı); add_generation_prompt=True ise sona sabit 13 eklenir.
    """

    eos_token_id = 777

    def _msg_tokens(self, msg):
        role = msg.get("role", "user")
        base = 100 if role == "system" else 200 if role == "user" else 300
        if role == "assistant":
            base = 50
        content = str(msg.get("content", ""))
        h = sum((i + 1) * 13 for i in content.encode("utf-8")) % 100000
        n = max(1, (len(content) + 3) // 4)
        return [base + (h + i * 7) % 9900 for i in range(n)]

    def apply_chat_template(self, chat, tokenize=True, add_generation_prompt=False, **_):
        tokens = []
        for msg in chat:
            if tokenize:
                tokens.extend(self._msg_tokens(msg))
            else:
                tokens.append(msg)
        if add_generation_prompt:
            tokens.append(13)
        return tokens

    def decode(self, ids, **_):
        return "<t>"


def test_length_equality():
    tok = FakeTokenizer()
    sft = {"instruction": "özetle", "input": "gövde metni", "output": "özet çıktısı"}
    row = encode_sft(tok, sft, tokenizer_id="test/fake", max_len=8192)
    assert len(row["tokens"]) == len(row["loss_mask"])
    assert row["loss_mask"][row["n_prompt_tokens"]] == 1


def test_mask_bounds():
    tok = FakeTokenizer()
    sft = {"instruction": "inst", "input": "", "output": "cevap"}
    row = encode_sft(tok, sft, tokenizer_id="test/fake", max_len=8192)
    mask = row["loss_mask"]
    assert set(mask) <= {0, 1}
    idx = mask.index(1)
    # prompt sonuna kadar 0, completion tamamen 1
    assert all(m == 0 for m in mask[:idx])
    assert all(m == 1 for m in mask[idx:])


def test_dpo_two_rows():
    tok = FakeTokenizer()
    record = {"prompt": "soru", "chosen": "iyi cevap", "rejected": "kötü cevap"}
    rows = encode_dpo(tok, record, tokenizer_id="test/fake", max_len=8192,
                      project="p", index=7, source_file="dpo_dataset.jsonl", source_sha="x" * 16)
    # dpo rejected content'in karakter karması chosen'dan farklı = satır sayısı 2
    assert len(rows) == 2
    kinds = sorted(r["kind"] for r in rows)
    assert kinds == ["dpo_chosen", "dpo_rejected"]
    # aynı sample_id kökü
    assert rows[0]["sample_id"] == rows[1]["sample_id"]


def test_truncation_tail_cut():
    tok = FakeTokenizer()
    sft = {"instruction": "inst", "input": "", "output": "o" * 500}
    row = encode_sft(tok, sft, tokenizer_id="test/fake", max_len=100)
    assert row["truncated"] is True
    assert row["n_tokens"] == 100
    assert len(row["tokens"]) == len(row["loss_mask"])
    # completion hâlâ kısmen içeride (kesme sondan → prompt tam, completion kısmi)
    assert row["loss_mask"].count(1) >= 1


def test_empty_completion_skipped():
    tok = FakeTokenizer()
    # max_len'i prompt uzunluğunun ALTINA çek: completion tamamen kesilir → boş dict (satır yok)
    sft = {"instruction": "uzun istem " * 200, "input": "girdi " * 200, "output": "cevap"}
    row = encode_sft(tok, sft, tokenizer_id="test/fake", max_len=32)
    assert row == {}


def test_multiturn_roles_masked():
    tok = FakeTokenizer()
    messages = [
        {"role": "system", "content": "sistem"},
        {"role": "user", "content": "soru 1"},
        {"role": "assistant", "content": "yanıt 1"},
        {"role": "user", "content": "soru 2"},
        {"role": "assistant", "content": "yanıt 2"},
    ]
    row = encode_multiturn(tok, {"messages": messages}, tokenizer_id="test/fake", max_len=8192)
    mask = row["loss_mask"]
    # assistant segmentleri = 1; system/user segmentleri = 0
    assert any(m == 1 for m in mask)
    assert sum(mask) < len(mask)  # en az bir maskeli segment var
