$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

# 路径由脚本位置推导：<install root>/源码/setup/install_all.ps1
$installRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$venvPy = Join-Path $installRoot '.venv\Scripts\python.exe'
$py = if (Test-Path $venvPy) { $venvPy } else { 'python' }
$logdir = Join-Path $installRoot 'logs'
New-Item -ItemType Directory -Force -Path $logdir | Out-Null
$main = Join-Path $logdir 'install_all.log'
if (Test-Path $main) { Remove-Item $main -Force }

function Log($m) {
  $line = (Get-Date).ToString('HH:mm:ss') + '  ' + $m
  $line | Out-File -FilePath $main -Append -Encoding utf8
}

function Run($name, $pkgs, $extra) {
  Log ''
  Log ('=== BATCH ' + $name + ' ===')
  $pa = @('-m','pip','install','--no-input','--timeout','40','--retries','3','--progress-bar','off')
  if ($extra) { $pa = $pa + $extra }
  $pa = $pa + $pkgs
  $out = & $py @pa 2>&1
  Log ('    exitcode=' + $LASTEXITCODE)
  $hit = $out | Select-String -Pattern 'Successfully installed|ERROR|error:|No matching distribution|Could not find'
  if ($hit) { $hit | ForEach-Object { Log ('    ' + $_.Line) } } else { Log '    (no notable lines)' }
  return $LASTEXITCODE
}

# ---- wait until no other pip is running (avoid cache lock contention) -----
$n = 0
while ($n -lt 120) {
  $p = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*pip install*' }
  if (@($p).Count -eq 0) { break }
  Start-Sleep -Seconds 5
  $n++
}
Log ('previous pip drained after ' + ($n*5) + 's')

# ---- network probe --------------------------------------------------------
# IMPORTANT: huggingface.co is normally DNS-blackholed in CN and
# Invoke-WebRequest -TimeoutSec does NOT bound DNS resolution, so curl is used.
# All model downloads must therefore go through the hf-mirror endpoint.
Log ''
Log '=== NETWORK PROBE (curl, honours connect timeout incl. DNS) ==='
foreach ($u in @('https://huggingface.co', 'https://hf-mirror.com', 'https://modelscope.cn')) {
  $r = & curl.exe -s -o NUL -w "%{http_code} in %{time_total}s" --connect-timeout 5 --max-time 10 -I $u 2>&1
  Log ('    ' + $u + '  ->  ' + ($r -join ' '))
}
$env:HF_ENDPOINT = 'https://hf-mirror.com'
[Environment]::SetEnvironmentVariable('HF_ENDPOINT', 'https://hf-mirror.com', 'User')
Log ('    HF_ENDPOINT set (this run + user env) = ' + $env:HF_ENDPOINT)

# ---- small text / subtitle libraries -------------------------------------
Run 'subtitle-text' @('srt','pysubs2','pypinyin') $null

# ---- ASR: faster-whisper (CTranslate2 backend, no torch needed) ----------
Run 'asr-faster-whisper' @('faster-whisper') $null

# ---- OCR: PP-OCR models through ONNX Runtime (no PaddlePaddle needed) ----
Run 'ocr-rapidocr' @('rapidocr-onnxruntime','onnxruntime') $null

# ---- torch（已不需要）--------------------------------------------------------
# The CUDA build is a ~2.8 GB download. Probed 2026-09-13:
#   https://download.pytorch.org/whl/cu129  ->  ~384 KB/s  (about 2 hours)
#   mirror.sjtu.edu.cn/pytorch-wheels/cu129 ->  hangs, unusable
# The phase-1 pipeline does NOT need torch at all (faster-whisper runs on
# CTranslate2, RapidOCR runs on ONNX Runtime, translation goes to the local
# koboldcpp HTTP endpoint), so only the small CPU build is installed here to
# keep `import torch` working. GPU torch is an optional upgrade, see report.
# v3.1.2 起 GPU 能力由 CTranslate2 + nvidia-* 运行库提供，torch 不再是任何功能的依赖，
# 因此这里不再安装（如需 torch 作显存探测兜底，可自行 pip install torch）。
# Run 'torch-cpu' @('torch') $null

Log ''
Log '=== FINAL PACKAGE LIST ==='
$out = & $py -m pip list 2>&1
$out | ForEach-Object { Log ('    ' + $_) }
Log ''
Log '=== VERIFY IMPORTS ==='
$code = @'
mods = ["numpy","cv2","av","moviepy","srt","pysubs2","jieba","pypinyin","soundfile","scipy",
        "fastapi","uvicorn","httpx","openai","pydantic","sqlalchemy","faster_whisper",
        "ctranslate2","rapidocr_onnxruntime","onnxruntime","torch"]
for m in mods:
    try:
        mod = __import__(m)
        v = getattr(mod, "__version__", "?")
        print("  OK    " + m + "  " + str(v))
    except Exception as e:
        print("  FAIL  " + m + "  -> " + type(e).__name__ + ": " + str(e)[:120])
try:
    import torch
    print("  torch cuda_available = " + str(torch.cuda.is_available()))
except Exception:
    print("  torch not importable")
try:
    import ctranslate2
    print("  ctranslate2 cuda types = " + str(ctranslate2.get_supported_compute_types("cuda")))
except Exception as e:
    print("  ctranslate2 cuda probe failed: " + str(e)[:120])
try:
    import onnxruntime
    print("  onnxruntime providers = " + str(onnxruntime.get_available_providers()))
except Exception as e:
    print("  onnxruntime probe failed: " + str(e)[:120])
'@
$code | Out-File -FilePath (Join-Path $logdir '_verify.py') -Encoding ascii
$vout = & $py (Join-Path $logdir '_verify.py') 2>&1
$vout | ForEach-Object { Log $_ }

Log ''
Log 'ALL DONE'
