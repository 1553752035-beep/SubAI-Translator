@echo off
chcp 936 >nul
cd /d "%~dp0"
"D:\AI\KoboldCpp\koboldcpp.exe" ^
  --model "D:\AI\KoboldCpp-vl\models\Qwen3VL-4B-Instruct-Q4_K_M.gguf" ^
  --mmproj "D:\AI\KoboldCpp-vl\models\mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf" ^
  --port 5003 --usecublas --gpulayers 99 ^
  --contextsize 16384 --quantkv q8_0 ^
  --visionmaxres 640 --visionmaxtokens 256 ^
  --jinja --jinja_tools --reasoningeffort none --noshift ^
  --reqtimeout 1800 >> "%~dp0out.log" 2>&1
