@echo off
chcp 65001 >nul
title KoboldCpp - DSH profile SAFE (port 5002, no KV reuse)

REM ============================================================================
REM  DSH 专用「稳定优先」配置 —— 与 start-dsh-profile.bat 二选一，不要同时开
REM
REM  什么时候用它：
REM    当你在同一个会话里【反复贴图、且图片尺寸不一致】时，快速版
REM    (start-dsh-profile.bat) 可能报 "Provider finish_reason: error"，
REM    成因是 KoboldCpp 的 KV 前缀复用遇到媒体 token 数变化
REM    （服务端日志会写 "Media tokens mismatch at 46! (38 vs 46 tokens)"）。
REM    本配置用 --nofastforward 关闭 KV 复用，任何尺寸/数量的图都不会再触发。
REM
REM  代价（实测）：
REM    每一步都要重新处理整个上下文。纯文本短会话几乎无感（~1.5s/步），
REM    但上下文到 2 万 token 后每步约 45 秒，5 万 token 后约 110 秒。
REM    换句话说：稳定换速度，长会话会明显变慢。
REM
REM  你原有的三个文件依旧一字未改。
REM ============================================================================

set MODEL=D:\AI\KoboldCpp\models\Qwen3.6-35B-A3B-UD-Q4_K_M.gguf
set EXE=D:\AI\KoboldCpp\koboldcpp.exe
set TPL=D:\AI\KoboldCpp\qwen36-dsh.jinja
set MMPROJ=D:\AI\KoboldCpp\models\mmproj-F16.gguf

if not exist "%EXE%"   ( echo [ERROR] koboldcpp.exe not found & pause & exit /b 1 )
if not exist "%MODEL%" ( echo [ERROR] model not found & pause & exit /b 1 )
if not exist "%TPL%"   ( set TPL=D:\AI\KoboldCpp\qwen36-nothink.jinja )
set VISION=--mmproj "%MMPROJ%" --mmprojcpu
if not exist "%MMPROJ%" ( set VISION= )

echo ==========================================================
echo   KoboldCpp + Qwen3.6-35B-A3B   (DSH SAFE profile)
echo ----------------------------------------------------------
echo   Port       : 5002
echo   KV reuse   : DISABLED (--nofastforward)  ← 稳定优先
echo   Context    : 98304 / q8_0
echo   Vision     : mmproj-F16 (CPU)
echo   Sampling   : temperature 0.6 强制 / rep_pen 1.05
echo   API        : http://127.0.0.1:5002/v1
echo ==========================================================
echo.

"%EXE%" --model "%MODEL%" ^
  --port 5002 ^
  --usecublas ^
  --gpulayers 99 ^
  --moecpu 33 ^
  --contextsize 98304 ^
  --quantkv q8_0 ^
  --noshift ^
  --nofastforward ^
  --jinja ^
  --jinja_tools ^
  --jinjatemplate "%TPL%" ^
  --reasoningeffort none ^
  --gendefaults "{\"temperature\":0.6,\"top_p\":0.8,\"top_k\":20,\"min_p\":0,\"rep_pen\":1.05,\"rep_pen_range\":256,\"tfs\":0.95}" ^
  --gendefaultsoverwrite ^
  --visionmaxres 2048 ^
  --reqtimeout 1800 ^
  %VISION%

echo.
echo [KoboldCpp exited]
pause
