@echo off
chcp 936 >nul
title [5003] 视频通话视觉 - Qwen3-VL-4B

REM ============================================================================
REM  用途：DSH 手机视频通话的本地视觉模型
REM  端口：5003   （5001=SubAI-Translator，5002=DSH 原适配，三者互不干扰）
REM  模型：Qwen3-VL-4B-Instruct Q4_K_M + mmproj Q8_0
REM
REM  实测：640x360 单帧 342-715ms（平均 445ms），视觉编码仅 90ms
REM  显存：约 4.6GB（模型 2.5G + mmproj 0.43G + KV 1.6G）
REM
REM  重要：本脚本不修改 D:\AI\KoboldCpp 下任何现有文件。
REM ============================================================================

set EXE=D:\AI\KoboldCpp\koboldcpp.exe
set MODEL=D:\AI\KoboldCpp-vl\models\Qwen3VL-4B-Instruct-Q4_K_M.gguf
set MMPROJ=D:\AI\KoboldCpp-vl\models\mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf

if not exist "%EXE%"    ( echo [ERROR] koboldcpp.exe 不存在 & pause & exit /b 1 )
if not exist "%MODEL%"  ( echo [ERROR] 模型不存在，请先运行 下载模型.bat & pause & exit /b 1 )
if not exist "%MMPROJ%" ( echo [ERROR] mmproj 不存在，请先运行 下载模型.bat & pause & exit /b 1 )

echo ==========================================================
echo   [5003] 视频通话视觉实例
echo ----------------------------------------------------------
echo   Model   : Qwen3-VL-4B-Instruct Q4_K_M
echo   Vision  : GPU (不使用 --mmprojcpu)
echo   Context : 16384  (KV q8_0)
echo   API     : http://127.0.0.1:5003/v1
echo   DSH     : 设置 - 模型选项 - 自定义模型 API
echo             地址填上面 API，模型 ID 填 koboldcpp，勾选「图片」
echo ==========================================================
echo.

"%EXE%" --model "%MODEL%" ^
  --mmproj "%MMPROJ%" ^
  --port 5003 ^
  --usecublas ^
  --gpulayers 99 ^
  --contextsize 16384 ^
  --quantkv q8_0 ^
  --visionmaxres 640 ^
  --visionmaxtokens 256 ^
  --jinja ^
  --jinja_tools ^
  --reasoningeffort none ^
  --noshift ^
  --reqtimeout 1800

echo.
echo [KoboldCpp 已退出]
pause
