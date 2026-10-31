import sys

print("python", sys.version.split()[0])
try:
    import torch
    print("torch", torch.__version__, "| cuda", torch.cuda.is_available(), "| gpu", torch.cuda.device_count())
    for i in range(torch.cuda.device_count()):
        p = torch.cuda.get_device_properties(i)
        print(f"  gpu {i}: {p.name} {p.total_memory/1e9:.1f} GB")
except Exception as exc:  # noqa: BLE001
    print("torch HATA:", exc)

for name in ("transformers", "peft", "trl", "datasets", "accelerate", "bitsandbytes", "safetensors"):
    try:
        mod = __import__(name)
        print(f"{name:14s} {getattr(mod, '__version__', '?')}")
    except Exception as exc:  # noqa: BLE001
        print(f"{name:14s} YOK ({type(exc).__name__})")
