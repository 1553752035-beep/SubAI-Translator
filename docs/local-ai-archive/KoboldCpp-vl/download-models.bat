@echo off
chcp 936 >nul
title 下载 Qwen3-VL-4B 模型

REM ============================================================================
REM  下载视频通话用的视觉模型（约 3GB）
REM  走 hf-mirror（GitHub 在本机不可达）
REM  支持断点续传：中断后重新运行本脚本即可
REM ============================================================================

set DEST=%~dp0models
if not exist "%DEST%" mkdir "%DEST%"
set BASEURL=https://hf-mirror.com/Qwen/Qwen3-VL-4B-Instruct-GGUF/resolve/main

echo ==========================================================
echo   下载目标: %DEST%
echo   总计约 3GB，请保持网络
echo ==========================================================
echo.

echo [1/2] 模型 Qwen3VL-4B-Instruct-Q4_K_M.gguf (2.5GB)
curl -L -C - --retry 5 --retry-delay 3 -o "%DEST%\Qwen3VL-4B-Instruct-Q4_K_M.gguf" "%BASEURL%/Qwen3VL-4B-Instruct-Q4_K_M.gguf"
if errorlevel 1 ( echo [ERROR] 模型下载失败 & pause & exit /b 1 )

echo.
echo [2/2] 视觉编码器 mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf (0.45GB)
curl -L -C - --retry 5 --retry-delay 3 -o "%DEST%\mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf" "%BASEURL%/mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf"
if errorlevel 1 ( echo [ERROR] mmproj 下载失败 & pause & exit /b 1 )

echo.
echo ==========================================================
echo   下载完成，可以运行 启动-5003-视频通话.bat
echo ==========================================================
dir "%DEST%"
pause
