@echo off
chcp 936 >nul
title KoboldCpp 启动菜单

:menu
cls
echo ============================================================================
echo                        KoboldCpp 启动项总览
echo ============================================================================
echo.
echo   [1]  5001  SubAI-Translator 字幕翻译
echo        模型 Qwen3.6-35B-A3B   显存 约7GB   加载 1-3 分钟
echo        脚本 D:\AI\KoboldCpp\start-qwen36-a3b.bat
echo.
echo   [2]  5002  DSH 原适配（含视觉）
echo        模型 Qwen3.6-35B-A3B   显存 约7GB   加载 1-3 分钟
echo        脚本 D:\AI\KoboldCpp\start-dsh-profile.bat
echo.
echo   [3]  5003  视频通话视觉  [新增]
echo        模型 Qwen3-VL-4B       显存 约4.6GB  加载 10-30 秒
echo        脚本 D:\AI\KoboldCpp-vl\start-5003-video.bat
echo.
echo ----------------------------------------------------------------------------
echo   注意：三者共用一块 8GB 显卡，不要同时运行。
echo         5001/5002 各占约 7GB，5003 约 4.6GB。
echo ----------------------------------------------------------------------------
echo.
echo   [4]  下载视频通话模型（约 3GB，仅首次）
echo   [5]  查看当前显存占用
echo   [6]  查看端口占用
echo   [0]  退出
echo.
set /p CH=请输入编号并回车: 

if "%CH%"=="1" ( start "" "D:\AI\KoboldCpp\start-qwen36-a3b.bat" & goto menu )
if "%CH%"=="2" ( start "" "D:\AI\KoboldCpp\start-dsh-profile.bat" & goto menu )
if "%CH%"=="3" ( start "" "D:\AI\KoboldCpp-vl\start-5003-video.bat" & goto menu )
if "%CH%"=="4" ( start "" "D:\AI\KoboldCpp-vl\download-models.bat" & goto menu )
if "%CH%"=="5" ( cls & nvidia-smi --query-gpu=memory.used,memory.total --format=csv & pause & goto menu )
if "%CH%"=="6" ( cls & netstat -ano ^| findstr ":500" & pause & goto menu )
if "%CH%"=="0" exit /b
goto menu
