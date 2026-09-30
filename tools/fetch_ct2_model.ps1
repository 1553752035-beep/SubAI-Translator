# Download a CTranslate2 Whisper model from the hf-mirror endpoint.
#
# WHY curl AND NOT huggingface_hub:
#   This machine's link stalls on long sustained transfers (observed three
#   times: SJTU pytorch mirror, Aliyun torch wheel, hf-mirror model.bin).
#   huggingface_hub cannot resume, so a stall means starting over.
#   curl with "-C -" resumes, and --speed-limit/--speed-time aborts a dead
#   transfer and lets --retry reconnect from where it stopped. This turns an
#   otherwise impossible download into a merely slow one.
param(
  [string]$Repo   = 'Systran/faster-whisper-small',
  [string]$OutDir = ''
)

# Derive paths from this script's location so it works in any install directory:
#   <repo>/tools/fetch_ct2_model.ps1  ->  install root = parent of <repo>
if (-not $OutDir) {
  $installRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
  $OutDir = Join-Path $installRoot 'models\faster-whisper-small'
}
$logDir = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) 'logs'
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$log = Join-Path $logDir 'fetch_model.log'

function Log($m) {
  ((Get-Date).ToString('HH:mm:ss') + '  ' + $m) | Out-File $log -Append -Encoding utf8
}

$files = @('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt', 'preprocessor_config.json')

Log ('repo=' + $Repo + '   out=' + $OutDir)
foreach ($f in $files) {
  $url = 'https://hf-mirror.com/' + $Repo + '/resolve/main/' + $f
  $dst = Join-Path $OutDir $f
  Log ('fetch ' + $f)
  $r = & curl.exe -L -C - -s -S --retry 40 --retry-delay 2 --retry-all-errors `
        --speed-limit 4096 --speed-time 15 --connect-timeout 10 --max-time 3600 `
        -o $dst $url 2>&1
  $rc = $LASTEXITCODE
  $sz = 0
  if (Test-Path $dst) { $sz = (Get-Item $dst).Length }
  Log ('   rc=' + $rc + '   size=' + $sz)
}
Log 'DONE'
