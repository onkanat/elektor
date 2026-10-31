import time

import torch

print("torch", torch.__version__, "cuda", torch.cuda.is_available())
dev = "cuda"

# 1) stok AdamW
m = torch.nn.Sequential(*[torch.nn.Linear(1024, 1024, bias=False) for _ in range(4)]).to(dev)
opt = torch.optim.AdamW(m.parameters(), lr=1e-4)
x = torch.randn(8, 1024, device=dev)
t0 = time.time()
for _ in range(20):
    loss = m(x).pow(2).mean()
    loss.backward()
    opt.step()
    opt.zero_grad(set_to_none=True)
torch.cuda.synchronize()
d1 = (time.time() - t0) / 20
print(f"AdamW (stok)        : {d1*1000:.1f} ms/adim")

# 2) bitsandbytes 8-bit sayfalı
try:
    import bitsandbytes as bnb
    m2 = torch.nn.Sequential(*[torch.nn.Linear(1024, 1024, bias=False) for _ in range(4)]).to(dev)
    opt2 = bnb.optim.PagedAdamW8bit(m2.parameters(), lr=1e-4)
    t0 = time.time()
    for _ in range(20):
        loss = m2(x).pow(2).mean()
        loss.backward()
        opt2.step()
        opt2.zero_grad(set_to_none=True)
    torch.cuda.synchronize()
    d2 = (time.time() - t0) / 20
    print(f"bnb PagedAdamW8bit   : {d2*1000:.1f} ms/adim  ({d2/d1:.1f}x)")
except Exception as exc:  # noqa: BLE001
    print("bnb optimizer HATA:", type(exc).__name__, str(exc)[:160])

# 3) 4-bit lineer katman (QLoRA yolu)
try:
    import bitsandbytes as bnb
    lin = bnb.nn.Linear4bit(4096, 4096, bias=False, quant_type="nf4", compute_dtype=torch.bfloat16).to(dev)
    xx = torch.randn(1, 64, 4096, device=dev, dtype=torch.bfloat16)
    for _ in range(3):
        lin(xx)
    torch.cuda.synchronize()
    t0 = time.time()
    for _ in range(10):
        y = lin(xx)
        y.sum().backward()
    torch.cuda.synchronize()
    d3 = (time.time() - t0) / 10
    print(f"bnb Linear4bit 4096->4096 (1x64) : {d3*1000:.1f} ms/ileri+geri")
except Exception as exc:  # noqa: BLE001
    print("bnb Linear4bit HATA:", type(exc).__name__, str(exc)[:160])
