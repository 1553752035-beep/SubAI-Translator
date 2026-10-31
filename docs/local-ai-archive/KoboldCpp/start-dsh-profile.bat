@echo off
chcp 65001 >nul
title KoboldCpp - DSH profile (port 5002, vision enabled)

REM ============================================================================
REM  DSH 专用 KoboldCpp 启动配置（含视觉，与端口 5001 的原项目完全隔离）
REM
REM  你原有的 start-qwen36-a3b.bat / 启动KoboldCpp.bat / qwen36-nothink.jinja
REM  一个字节都没有改动。新增的只有：
REM    · 本文件（DSH 专用启动）
REM    · qwen36-dsh.jinja（原模板副本 + DSH 规则，diff 仅 1 行）
REM    · models\mmproj-F16.gguf（视觉编码器，899MB，来自 hf-mirror）
REM
REM  参数经 8 组配置实测确定（RTX 4070 Laptop 8GB + 31GB RAM）：
REM    · 生成 29-30 T/s / 预填充 426-461 T/s，参数几乎无差异 → 瓶颈在硬件
REM      （33 层专家被迫留在 CPU）。
REM    · ★ 唯一显著收益：--smartcache（前缀 KV 复用，重复前缀首字 10.5s → 1.66s）
REM    · 视觉实测通过：能准确读出截图里的中文界面与英文皮肤 ID（28.5s/张图）
REM    · 试过但无收益、未采用：--moecpu 32、--quantkv q4_0/q5_1、--usemtp。
REM
REM  ★ 为什么用 --gendefaultsoverwrite：
REM    DSH 的「自定义模型 API」表单只暴露 上下文窗口/最大输出/输入模态，
REM    【没有 temperature 字段】。若 DSH 内部用低温度，就会踩到你文档里记录的
REM    "temperature 过低 → 输出死循环"。这里把 temperature 钉死 0.6 并允许覆盖，
REM    使 DSH 传什么都无效，从根上消除该风险。
REM    注意：这也会覆盖其它采样字段——而 DSH 本就不传它们，因此无副作用。
REM ============================================================================

set MODEL=D:\AI\KoboldCpp\models\Qwen3.6-35B-A3B-UD-Q4_K_M.gguf
set EXE=D:\AI\KoboldCpp\koboldcpp.exe
set TPL=D:\AI\KoboldCpp\qwen36-dsh.jinja
set MMPROJ=D:\AI\KoboldCpp\models\mmproj-F16.gguf

if not exist "%EXE%"   ( echo [ERROR] koboldcpp.exe not found & pause & exit /b 1 )
if not exist "%MODEL%" ( echo [ERROR] model not found & pause & exit /b 1 )
if not exist "%TPL%"   ( echo [WARN] DSH 模板缺失，回退到原 nothink 模板 & set TPL=D:\AI\KoboldCpp\qwen36-nothink.jinja )

set VISION=--mmproj "%MMPROJ%" --mmprojcpu
if not exist "%MMPROJ%" (
    echo [WARN] mmproj 缺失，本次以纯文本模式启动
    set VISION=
)

echo ==========================================================
echo   KoboldCpp + Qwen3.6-35B-A3B   (DSH profile)
echo ----------------------------------------------------------
echo   Port       : 5002        (原项目用 5001，互不干扰)
echo   Context    : 98304       (KV q8_0；输入上限 = 98304 - max_tokens)
echo   SmartCache : 2           (KV 快照存内存，不占显存)
echo   MoE        : 33 层专家在 CPU / 7 层在 GPU
echo   Vision     : mmproj-F16 (编码器在 CPU，不占显存)
echo   Template   : qwen36-dsh.jinja (原模板 + DSH 规则)
echo   Sampling   : temperature 0.6 强制覆盖 + top_p .8 / top_k 20 / rep_pen 1.05
echo   Thinking   : none
echo   API        : http://127.0.0.1:5002/v1  (OpenAI 兼容)
echo ==========================================================
echo   首次加载 1-3 分钟（20.6GB 从磁盘）。使用中请勿关闭本窗口。
echo.

"%EXE%" --model "%MODEL%" ^
  --port 5002 ^
  --usecublas ^
  --gpulayers 99 ^
  --moecpu 33 ^
  --contextsize 98304 ^
  --quantkv q8_0 ^
  --smartcache 2 ^
  --jinja ^
  --jinja_tools ^
  --jinjatemplate "%TPL%" ^
  --reasoningeffort none ^
  --gendefaults "{\"temperature\":0.6,\"top_p\":0.8,\"top_k\":20,\"min_p\":0,\"rep_pen\":1.05,\"rep_pen_range\":256,\"tfs\":0.95}" ^
  --gendefaultsoverwrite ^
  --visionmaxres 2048 ^
  --noshift ^
  --reqtimeout 1800 ^
  %VISION%

echo.
echo [KoboldCpp exited]
pause
