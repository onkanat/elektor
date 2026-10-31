$ErrorActionPreference = "Continue"
$log = "E:\egitim\kurulum.log"
New-Item -ItemType Directory -Force -Path E:\egitim | Out-Null
function Log($m) { $m | Tee-Object -FilePath $log -Append }

Log "=== ECE_PC egitim ortami kurulumu $(Get-Date -Format s) ==="

# 1) uv (yonetici gerektirmez, kendi Python'unu kurar)
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) {
  $cand = "$env:USERPROFILE\.local\bin\uv.exe"
  if (Test-Path $cand) { $uv = $cand }
}
if (-not $uv) {
  Log "uv kuruluyor..."
  Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression 2>&1 | Tee-Object -FilePath $log -Append
  $uv = "$env:USERPROFILE\.local\bin\uv.exe"
}
Log "uv = $uv"
& $uv --version 2>&1 | Tee-Object -FilePath $log -Append

# 2) Python 3.12
Log "python 3.12 kuruluyor..."
& $uv python install 3.12 2>&1 | Tee-Object -FilePath $log -Append

# 3) venv
Log "venv: E:\egitim\venv"
& $uv venv E:\egitim\venv --python 3.12 2>&1 | Tee-Object -FilePath $log -Append
$py = "E:\egitim\venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Log "HATA: venv olusmadi"; exit 1 }

# 4) torch (CUDA) — once cu126, olmazsa cu124
foreach ($cu in @("cu126", "cu124")) {
  Log "torch deneniyor: $cu"
  & $uv pip install --python $py torch --index-url "https://download.pytorch.org/whl/$cu" 2>&1 | Tee-Object -FilePath $log -Append
  & $py -c "import torch;print('torch ok',torch.__version__)" 2>&1 | Tee-Object -FilePath $log -Append
  if ($LASTEXITCODE -eq 0) { Log "torch kuruldu ($cu)"; break }
}

# 5) egitim yigini
Log "peft/trl/transformers/bitsandbytes kuruluyor..."
& $uv pip install --python $py transformers peft trl datasets accelerate bitsandbytes safetensors sentencepiece protobuf pillow 2>&1 | Tee-Object -FilePath $log -Append

# 6) dogrulama
Log "=== DOGRULAMA ==="
& $py -c "import torch, transformers, peft, trl, bitsandbytes as bnb; print('torch', torch.__version__, '| cuda', torch.cuda.is_available(), '| gpu', torch.cuda.device_count()); [print('  gpu', i, torch.cuda.get_device_name(i), round(torch.cuda.get_device_properties(i).total_memory/1e9,1), 'GB') for i in range(torch.cuda.device_count())]; print('transformers', transformers.__version__, '| peft', peft.__version__, '| trl', trl.__version__, '| bnb', bnb.__version__)" 2>&1 | Tee-Object -FilePath $log -Append
Log "=== BITTI $(Get-Date -Format s) ==="
