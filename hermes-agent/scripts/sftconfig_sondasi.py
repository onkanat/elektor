import dataclasses
import inspect

from trl import SFTConfig

print("SFTConfig alanlari (ilk 40):")
fields = [f.name for f in dataclasses.fields(SFTConfig)]
print("  ", ", ".join(fields[:40]))
for name in ("max_length", "max_seq_length", "eval_strategy", "evaluation_strategy",
             "gradient_checkpointing_kwargs", "optim", "bf16", "report_to", "save_strategy"):
    print(f"  {name:28s} {'VAR' if name in fields else 'YOK'}")

base = dict(output_dir="E:/egitim/cikti/probe", per_device_train_batch_size=1,
            gradient_accumulation_steps=8, num_train_epochs=1.0, learning_rate=1e-4,
            lr_scheduler_type="cosine", warmup_ratio=0.03, logging_steps=5,
            save_strategy="no", bf16=True, optim="paged_adamw_8bit", report_to=[],
            gradient_checkpointing=True,
            gradient_checkpointing_kwargs={"use_reentrant": False})

print("\nminimal + tek tek ekleme:")
try:
    SFTConfig(**{k: v for k, v in base.items() if k != "gradient_checkpointing_kwargs"})
    print("  minimal (gc_kwargs haric): OK")
except Exception as exc:  # noqa: BLE001
    print("  minimal: HATA", type(exc).__name__, str(exc)[:160])

for extra in ({}, {"gradient_checkpointing_kwargs": {"use_reentrant": False}},
              {"max_length": 4096}, {"max_seq_length": 4096},
              {"eval_strategy": "no"}, {"evaluation_strategy": "no"}):
    kw = dict(base)
    kw.update(extra)
    try:
        cfg = SFTConfig(**kw)
        print(f"  +{list(extra) or 'taban'}: OK  (max_length={getattr(cfg, 'max_length', None)})")
    except Exception as exc:  # noqa: BLE001
        print(f"  +{list(extra) or 'taban'}: HATA {type(exc).__name__}: {str(exc)[:140]}")

print("\nsignature:", str(inspect.signature(SFTConfig.__init__))[:400])
