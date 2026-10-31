@echo off
chcp 65001 >nul
title KoboldCpp - Qwen3.6-35B-A3B (MoE offload)

set MODEL=D:\AI\KoboldCpp\models\Qwen3.6-35B-A3B-UD-Q4_K_M.gguf
set EXE=D:\AI\KoboldCpp\koboldcpp.exe
set TPL=D:\AI\KoboldCpp\qwen36-nothink.jinja

if not exist "%EXE%" (
    echo [ERROR] koboldcpp.exe not found at %EXE%
    pause
    exit /b 1
)
if not exist "%MODEL%" (
    echo [ERROR] model not found at %MODEL%
    pause
    exit /b 1
)
if not exist "%TPL%" (
    echo [ERROR] chat template not found at %TPL%
    echo         re-run the template generator before launching.
    pause
    exit /b 1
)

echo ==========================================================
echo   KoboldCpp + Qwen3.6-35B-A3B (UD-Q4_K_M)
echo ----------------------------------------------------------
echo   Port      : 5001
echo   GPU       : CUDA (RTX 4070 Laptop, 8GB)
echo   MoE       : 33 layers' experts -> CPU, 7 layers -> GPU
echo               (measured ~31.7 short / 26.1 long-ctx tok/s)
echo   Threads   : auto (7 detected)
echo               --threads 8 = no measurable gain; 16 = hangs
echo   Attention : GPU
echo   Context   : 98304  (input 65536 + output 32768)
echo   KV cache  : q8_0 (quantized, saves VRAM)
echo   Template  : model's own jinja template (MODIFIED)
echo   Thinking  : DISABLED (empty think block injected)
echo   CtxShift  : OFF  (--noshift frees ~4.6GB of useless KV slots)
echo   API       : OpenAI + Anthropic compatible
echo ==========================================================
echo.
echo NOTE: first load takes 1-3 minutes (20.6 GB from disk).
echo       Do NOT close this window while the model is in use.
echo.

"%EXE%" --model "%MODEL%" ^
  --port 5001 ^
  --usecublas ^
  --gpulayers 99 ^
  --moecpu 33 ^
  --contextsize 98304 ^
  --quantkv q8_0 ^
  --jinja ^
  --jinja_tools ^
  --jinjatemplate "%TPL%" ^
  --noshift ^
  --reqtimeout 1200 ^
  --launch

echo.
echo [KoboldCpp exited]
pause
