# pipeline/token_layer.py — Elektor token katmanı (Atropos vendor)
#
# Kaynak: NousResearch/atropos @ main (296a0bc5, arşivli 04.07.2026) · MIT ·
#     alınan dosya: atroposlib/utils/tokenize_for_trainer.py
#     yardımcı şema dosyası: atroposlib/type_definitions.py (yalnız Message TypedDict'i)
#     Attribütion (MIT): Nous Research — Copyright (c) 2026 Nous Research
#
# Yerel değişiklikler (vendor kodun altındaki bu dosyada tutulur; Atropos arşivli, upstream yok):
#   1. Mask sözleşmesi Dönüştürüldü: Atropos -100 mask → Elektor {0,1} (0=maskeli, 1=öğrenilir).
#      -100 dışı değerler (vendor son-segment token id'leri) → 1 olarak haritalanır.
#   2. numpy kaldırıldı (düz liste; vendor np.ones bloğu liste ile yeniden yazıldı).
#   3. `from atroposlib.type_definitions import Message` → bu dosyada tanımlı yerel Message TypedDict.
#   4. Vendor `__main__` debug bloğu (rich/Llama tokenizer örneği) düşürüldü.
#   5. Yerel ekleyenler: load_tokenizer / encode_sft / encode_dpo / encode_multiturn /
#      iter_token_rows / encode_sft_record yardımcıları (kendi kapsamımda, vendor dışı).
#   6. transformers 5.x: `apply_chat_template` BatchEncoding döndürür → `_apply_tokens`
#      normalizasyonu (tokenize=True + input_ids[0]); 4 çağrı noktası da üzerinden geçer.
#
# Sözleşme (şartname 10.11.2026):
#   Her satır: {"sample_id","source_file","source_sha256","kind","tokenizer","tokens","loss_mask",
#                "n_tokens","n_prompt_tokens","n_completion_tokens","truncated"}
#   1) len(tokens) == len(loss_mask) · 2) mask ∈ {0,1}; prompt 0, completion 1; PAD YOK
#   3) multi-turn: her assistant turu 1, system/user/tool 0
#   4) DPO çifti = iki satır (dpo_chosen / dpo_rejected), aynı sample_id kökü
#   5) kesme sondan (--max-len, varsayılan 8192 ∈ [2048,8192]); completion tamamen kesildiyse satır yazılmaz
#   6) tokenizer HF/transformers ile LOKAL yüklenir; strata/ollama uçlarına tokenizer isteği ATILMAZ

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, TypedDict

Content = Any

# --- atroposlib/type_definitions.py'den tekil alınan şema (ihraç sözleşmesi) ---
class Message(TypedDict):
    role: Literal["system", "user", "assistant", "tool"]
    content: Content
    reward: Optional[float]


# --- [VENDOR BEGIN] atroposlib/utils/tokenize_for_trainer.py @ 296a0bc5 ---
# Roles that should be masked in the loss calculation (not used for training)
UNMASKED_ROLES = ["assistant", "agent"]


# Yerel değişiklik notu (6): transformers 5.x `apply_chat_template` BatchEncoding döndürür
# (vendor 4.x token-liste bekler). Tek noktadan normalize edilir: tokenize=True + input_ids[0].
def _apply_tokens(tokenizer, chat, **kw):
    out = tokenizer.apply_chat_template(chat, tokenize=True, **kw)
    if hasattr(out, "encodings") or (hasattr(out, "get") and "input_ids" in out):
        ids = out["input_ids"]
        return list(ids[0]) if isinstance(ids, (list, tuple)) and ids and isinstance(ids[0], (list, tuple)) else list(ids)
    return out


def tokenize_for_trainer(
    tokenizer,
    chat: list,
    include_messages: bool = False,
    train_on_all_assistant_turns: bool = False,
    finish_reason: str = "",
) -> dict:
    """
    Tokenize a list of chat messages for the trainer.

    Args:
        tokenizer: The tokenizer to use (transformers PreTrainedTokenizer).
        chat (list): A list of chat messages.
        include_messages (bool): Whether to include the messages in the output.
        train_on_all_assistant_turns (bool): If True, mask out system/user/tool roles.
                                            If False, use the original prefix masking.
    Returns:
        dict: A dictionary containing the tokenized chat messages.
    """

    tokens = _apply_tokens(tokenizer, chat)

    if not train_on_all_assistant_turns:
        prefix_len = len(
            _apply_tokens(tokenizer, chat[:-1], add_generation_prompt=True)
        )
        masks = [-100] * prefix_len + tokens[prefix_len:]
    else:
        # NOTE (vendor): This implementation will break if the default system prompt is
        # used and depends on world state (e.g. current date).

        masks = [-100] * len(tokens)

        for i, msg in enumerate(chat):
            if msg["role"] in UNMASKED_ROLES:
                prefix_tokens = _apply_tokens(
                    tokenizer, chat[:i], add_generation_prompt=True
                )
                unmasked_tokens = _apply_tokens(tokenizer, chat[: i + 1])
                start_idx = len(prefix_tokens)
                end_idx = len(unmasked_tokens)
                masks[start_idx:end_idx] = list(unmasked_tokens[start_idx:])

    if finish_reason == "length":
        if tokens[-1] == tokenizer.eos_token_id:
            # truncate the last token
            tokens = tokens[:-1]
            masks = masks[:-1]

    result: Dict[str, Any] = {"tokens": tokens, "masks": masks}
    if include_messages:
        result["messages"] = chat
    return result
# --- [VENDOR END] ---

# Yerel değişiklik notu (1): vendor masks'i {0,1}'e normalize eden tek nokta.
def _normalize_mask(raw_mask: List[Any]) -> List[int]:
    return [0 if m == -100 else 1 for m in raw_mask]


def load_tokenizer(tokenizer_id: str):
    """HF tokenizer'ı LOKAL yükler (ağdan dosya indirme hariç servis/istek yok)."""
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(tokenizer_id)


def _base_row(
    project: str,
    index: int,
    source_file: str,
    source_sha: str,
    tokenizer_id: str,
    kind: str,
) -> Dict[str, Any]:
    return {
        "sample_id": f"{project}#{index}",
        "source_file": source_file,
        "source_sha256": source_sha,
        "kind": kind,
        "tokenizer": tokenizer_id,
    }


def _finish_row(row: Dict[str, Any], tokens: List[int], mask: List[int],
                prompt_len: int, truncated: bool) -> Dict[str, Any]:
    row.update(
        {
            "tokens": tokens,
            "loss_mask": mask,
            "n_tokens": len(tokens),
            "n_prompt_tokens": prompt_len,
            "n_completion_tokens": len(tokens) - prompt_len,
            "n_trainable_tokens": sum(mask),
            "truncated": truncated,
        }
    )
    return row


def _truncate(tokens: List[int], mask: List[int], max_len: int):
    """Kesme sondan; eğitilebilir token yoksa satır üretme (None,..) döner."""
    if not any(m == 1 for m in mask):
        return None, None, None
    if len(tokens) <= max_len:
        return tokens, mask, False
    tokens = tokens[:max_len]
    mask = mask[:max_len]
    if not any(m == 1 for m in mask):
        return None, None, None
    return tokens, mask, True


def encode_sft(tokenizer, record: Dict[str, Any], *, tokenizer_id: str,
               max_len: int) -> Dict[str, Any]:
    """{instruction,input,output} → tek satır (mask: prompt 0, output 1)."""
    if not (record.get("output") or "").strip():
        return {}
    chat = _sft_chat(record)
    res = tokenize_for_trainer(tokenizer, chat, train_on_all_assistant_turns=False)
    tokens = list(res["tokens"])
    mask = _normalize_mask(res["masks"])
    prompt_len = mask.index(1) if 1 in mask else len(tokens)
    tokens2, mask2, trunc = _truncate(tokens, mask, max_len)
    if trunc is None:
        return {}
    return _finish_row(_truncate_row_base(), tokens2, mask2, prompt_len, trunc)

def _truncate_row_base():
    return {}

def _sft_chat(record: Dict[str, Any]) -> List[Message]:
    instruction = (record.get("instruction") or "").strip()
    user_input = (record.get("input") or "").strip()
    prompt_text = instruction
    if user_input:
        prompt_text = f"{instruction}\n\n{user_input}" if instruction else user_input
    chat: List[Message] = [{"role": "user", "content": prompt_text,
                            "reward": None}]
    chat.append({"role": "assistant", "content": (record.get("output") or "").strip(),
                 "reward": None})
    return chat


def encode_dpo(tokenizer, record: Dict[str, Any], *, tokenizer_id: str,
               max_len: int, project: str, index: int, source_file: str,
               source_sha: str) -> List[Dict[str, Any]]:
    """{prompt,chosen,rejected} → İKİ satır, aynı sample_id kökü."""
    rows: List[Dict[str, Any]] = []
    for kind, answer_key in (("dpo_chosen", "chosen"), ("dpo_rejected", "rejected")):
        if not (record.get(answer_key) or "").strip():
            continue
        chat: List[Message] = [
            {"role": "user", "content": (record.get("prompt") or "").strip(), "reward": None},
            {"role": "assistant", "content": (record.get(answer_key) or "").strip(), "reward": None},
        ]
        res = tokenize_for_trainer(tokenizer, chat, train_on_all_assistant_turns=False)
        tokens = list(res["tokens"])
        mask = _normalize_mask(res["masks"])
        prompt_len = mask.index(1) if 1 in mask else len(tokens)
        tokens2, mask2, trunc = _truncate(tokens, mask, max_len)
        if trunc is None:
            continue
        row = _base_row(project, index, source_file, source_sha, tokenizer_id, kind)
        rows.append(_finish_row(row, tokens2, mask2, prompt_len, trunc))
    return rows


def encode_multiturn(tokenizer, record: Dict[str, Any], *, tokenizer_id: str,
                     max_len: int) -> Dict[str, Any]:
    """{messages:[...]} → her assistant turu 1, system/user/tool 0."""
    if not any((m.get("role") == "assistant" and str(m.get("content", "")).strip())
               for m in (record.get("messages") or [])):
        return {}
    chat: List[Message] = []
    for m in record.get("messages") or []:
        chat.append({"role": m.get("role", "user"),
                     "content": str(m.get("content", "")).strip(), "reward": None})
    res = tokenize_for_trainer(tokenizer, chat, train_on_all_assistant_turns=True)
    tokens = list(res["tokens"])
    mask = _normalize_mask(res["masks"])
    first_one = mask.index(1) if 1 in mask else len(tokens)
    tokens2, mask2, trunc = _truncate(tokens, mask, max_len)
    if trunc is None:
        return {}
    return _finish_row({}, tokens2, mask2, first_one, trunc)


def iter_token_rows(
    tokenizer,
    records: List[tuple],  # [(kind, record, source_file, source_sha, start_index)]
    *,
    project: str,
    tokenizer_id: str,
    max_len: int,
):
    """Kaynak kayıtlarını sözleşme satırlarına çevirir; satır üretimini istikrarlı yürütür."""
    for kind, record, source_file, source_sha, start_index in records:
        if kind == "sft":
            row = encode_sft(tokenizer, record, tokenizer_id=tokenizer_id, max_len=max_len)
            row.update(_base_row(project, start_index, source_file, source_sha,
                                 tokenizer_id, row.get("kind", "sft")))
            if row.get("n_tokens"):
                yield row
        elif kind == "dpo":
            yield from encode_dpo(tokenizer, record, tokenizer_id=tokenizer_id,
                                  max_len=max_len, project=project, index=start_index,
                                  source_file=source_file, source_sha=source_sha)
        elif kind == "multi_turn":
            row = encode_multiturn(tokenizer, record, tokenizer_id=tokenizer_id,
                                   max_len=max_len)
            row.update(_base_row(project, start_index, source_file, source_sha,
                                 tokenizer_id, row.get("kind", "multi_turn")))
            if row.get("n_tokens"):
                yield row
