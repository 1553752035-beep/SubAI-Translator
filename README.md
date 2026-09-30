# SubAI Translator

AI 视频字幕识别与翻译工具：自动提取视频里的语音或硬字幕，用大语言模型翻译成目标语言，一键生成双语字幕文件。

## 它能做什么

- **语音识别（ASR）**：把视频中的说话声转成字幕文字，适合没有字幕的视频
- **硬字幕识别（OCR）**：识别画面里已经内嵌的字幕文字，适合需要翻译现有字幕的视频
- **机器翻译**：把字幕翻译成目标语言；术语库保证专有名词翻译一致，可选**强制锁定**（译名 100% 一致）或**软提示**（语句更自然）两种模式
- **多格式输出**：SRT / VTT / ASS / JSON
- **视频压制与配音**：把字幕烧进画面、封装成可开关的 MKV 字幕轨，或生成与时间轴对齐的配音音轨
- **图形界面**：上传视频、查看实时进度、在线编辑字幕、管理术语库与历史记录
- **任务取消**：处理中的任务可随时取消，流水线会在检查点主动中止，且不会留下半成品文件

## 环境要求

| 依赖 | 说明 |
|------|------|
| **Windows 10/11** | **目标平台**：桌面端与语音合成都依赖 Windows 专有组件（SAPI、`bin\ffmpeg.exe`、CUDA DLL 目录、Tauri）。后端另有 Linux 容器镜像（见 `Dockerfile`） |
| Python 3.12+ | 运行后端 |
| FFmpeg | 项目已自带（`bin/` 目录），无需单独安装 |
| Node.js 18+ | 仅运行桌面/网页界面时需要 |
| NVIDIA GPU（可选） | 加速语音识别。**不需要安装 `torch`**：需同时满足「CTranslate2 支持 CUDA + 能找到 CUDA 运行库 + 空闲显存 ≥4GB」，详见「GPU 加速（可选）」 |

## 快速上手

### 第 1 步：启动后端

```powershell
cd <安装目录>                      # 本机示例：D:\SubAI-Translator
pip install -r requirements.txt   # 首次运行
python src/start.py
```

启动成功后：

- API 地址：<http://localhost:8000>
- 接口文档：<http://localhost:8000/docs>

### 第 2 步：启动界面（可选）

```powershell
cd frontend
npm install            # 首次运行
npm run tauri:dev      # 桌面应用
```

只想用网页版时，改运行 `npm run dev`，浏览器打开 <http://localhost:5173>。

### 第 3 步：翻译一个视频

1. 打开应用，上传视频文件
2. 选择识别模式（语音 / 硬字幕）和目标语言
3. 点击开始，等待进度条完成
4. 在字幕编辑器里微调译文
5. 导出字幕文件（SRT / VTT / ASS / JSON）

## 部署到另一台机器

程序不依赖写死的绝对路径：所有目录都由**安装位置**推导（源码运行时为仓库根，绿色版为 exe 同级目录）。

### 先自检，再使用

```powershell
# 源码方式
python tools/selfcheck.py            # 快速自检（秒级）
python tools/selfcheck.py --full     # 额外做真实推理抽样（较慢）

# 绿色版（无需 Python）
subai-backend.exe --check
subai-backend.exe --check --full
```

自检逐项检查：运行环境与依赖、FFmpeg（含 libx264）、ASR 模型、目录可写性、翻译后端连通性、GPU/CPU 判定、端口占用。
**每个失败项都会给出可执行的修复建议**，退出码 `0`/`1` 便于脚本判断，`--json` 可机器读取。

### 组装绿色版（可分发给他人）

```powershell
cd 源码
python -m PyInstaller --noconfirm subai_backend.spec
cd frontend; npm run tauri:build -- --no-bundle; cd ..
powershell -ExecutionPolicy Bypass -File tools\build_green_package.ps1 -OutDir D:\SubAI-Green
```

产物结构（约 0.75 GB）：`SubAI-Translator.exe` + `subai-backend.exe` + `bin/`（FFmpeg）+ `models/`（ASR 模型）+ `data/` + `使用说明.txt` + `LICENSE`。
目录内所有路径都由 exe 位置推导，可**整体拷贝到其他机器**。

已在全新目录实测：自检通过（模型项在新路径下 PASS）、真实任务与压制/配音正常落盘于新目录、桌面端能拉起同目录的后端，且两个 exe 中**不含任何开发机绝对路径**。

### 需要自备的资源

| 资源 | 放置位置 | 说明 |
|---|---|---|
| ASR 模型 | `<安装目录>/models/faster-whisper-small/` | 体积较大，不随仓库分发，需另行获取 |
| FFmpeg | `<安装目录>/bin/ffmpeg.exe`，或加入 PATH | 用于抽音轨与视频压制；缺 libx264 仅影响压制 |
| 翻译服务 | 自行启动（如 koboldcpp），默认 `http://127.0.0.1:5001/v1/chat/completions` | 也可在设置页切换云端模式 |
| CUDA 运行库（可选） | `<安装目录>/cuda_dlls/` | 仅在需要 GPU 加速语音识别时，见「GPU 加速（可选）」 |

## 配置说明

通过环境变量或项目根目录的 `.env` 文件配置，环境变量优先级更高。常用配置项：

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `SUBAI_LLM_MODE` | 翻译模式：`local` / `cloud` / `hybrid` | `local` |
| `SUBAI_LLM_LOCAL_URL` | 本地翻译服务地址 | `http://127.0.0.1:5001/v1/chat/completions` |
| `SUBAI_LLM_CLOUD_URL` | 云端 API 地址（OpenAI 兼容） | 空 |
| `SUBAI_LLM_CLOUD_API_KEY` | 云端 API 密钥 | 空 |
| `SUBAI_LLM_CLOUD_MODEL` | 云端模型名 | `gpt-4o` |
| `SUBAI_ASR_DEVICE` | 识别设备：`auto` / `cuda` / `cpu` | `auto` |
| `SUBAI_SERVER_PORT` | 后端监听端口 | `8000` |
| `SUBAI_LOG_LEVEL` | 日志级别 | `info` |

三种翻译模式的区别：

- **local**：本地翻译模型，完全离线，需自行启动本地翻译服务（如 koboldcpp）
- **cloud**：调用云端 API，需要联网并配置 API 密钥
- **hybrid**：语音识别用本地 GPU，翻译走云端

## 目录结构

**绿色版**（`tools/build_green_package.ps1` 组装）：

```
<安装目录>/
├── SubAI-Translator.exe    桌面端
├── subai-backend.exe       后端
├── bin/                    FFmpeg 可执行文件
├── models/                 语音识别模型
├── data/                   数据库与上传文件
└── output/                 字幕与音视频输出
```

**源码仓库**（即绿色版里的 `<安装目录>/源码`；源码方式运行时 `<安装目录>` 为仓库的上一级）：

```
├── src/                    后端代码（FastAPI）
├── frontend/               界面代码（React + Tauri）
├── tests/                  测试用例
├── tools/                  自检、组装绿色版与运维脚本
├── .github/workflows/      CI（Windows）
└── requirements.txt        Python 依赖清单
```

## 常见问题

- **提示找不到模型**：将 faster-whisper 模型放到 `models/faster-whisper-small/` 目录
- **提示 GPU 不可用**：需同时满足「CTranslate2 支持 CUDA + 能找到 CUDA DLL + 空闲显存 ≥4GB」，否则自动回退 CPU（属正常现象；判定依据见 `GET /api/system/asr-device`）
- **云端翻译返回 401**：检查 `SUBAI_LLM_CLOUD_API_KEY` 是否已正确配置
- **端口被占用**：修改 `SUBAI_SERVER_PORT` 环境变量后重启后端
- **取消任务后似乎还在跑**：取消是协作式的（Python 线程无法安全强杀），最坏情况要等当前这一步跑完——例如 ASR 推理本身不可中断；但不会再写入任何输出文件

## 测试

**后端（pytest）**

```powershell
cd 源码
$env:RUN_API_TESTS=1; python -m pytest tests -q
```

**前端（vitest + Testing Library）**

```powershell
cd 源码/frontend
npm test          # 单次运行
npm run test:watch
```

当前规模：后端 **272** 项、前端 **19** 项（随迭代增长）。端到端用例会真实调用 ASR / OCR / FFmpeg，缺少模型或 FFmpeg 时自动跳过。

持续集成：`.github/workflows/ci.yml`（后端 pytest + 前端 vitest）。

## GPU 加速（可选）

语音识别默认自动选择设备：`auto` 会**同时满足**「CTranslate2 支持 CUDA + 能找到 CUDA DLL + 空闲显存 ≥4GB」时使用 GPU，否则安全回落到 CPU（不会因缺库而直接失败）。

- **开发环境**：安装 `nvidia-cublas-cu12`、`nvidia-cudnn-cu12` 即可，程序会自动把它们的 `bin` 目录加入 DLL 搜索路径。
- **绿色版主包不包含 CUDA 运行库（约 2.0 GB）**。如需 GPU 加速，可自行把运行库按下面结构放到安装目录，程序会自动识别：

```
cuda_dlls/
├── cublas/bin/cublas64_12.dll 等
├── cudnn/bin/cudnn64_9.dll 等
└── cuda_nvrtc/bin/nvrtc*.dll
```

- 当前生效设备与判定依据可通过 `GET /api/system/asr-device` 查看，或看日志里的 `[ASR]` 行。

- 自检：`.venv\\Scripts\\python.exe tools\\check_gpu.py --load`（报告判定依据并真实加载一次模型）。
- 生成可选 GPU 包（**不联网**，从本机已安装的 nvidia-* 运行库生成），然后把生成的 `cuda_dlls` 放到 exe 同级目录：
  - `-Mode Copy`（默认，约 2.0 GB）：复制 DLL，适合随绿色版分发或转移；
  - `-Mode Link`（**零磁盘占用**）：创建目录联接，适合开发机即时启用 GPU。

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_gpu_pack.ps1              # 复制（可分发）
powershell -ExecutionPolicy Bypass -File tools\build_gpu_pack.ps1 -Mode Link    # 目录联接（零占用）
```

- 实测（打包版，8.96 s 音频）：有 GPU 包时识别推理 **0.5 s**，无则 CPU **1.5 s**（约 3.0 倍）。

## 许可证

本项目采用 **MIT** 许可证，详见 [LICENSE](LICENSE)。

> 说明：对外分发**完整运行包**时，其中的第三方组件（FFmpeg、ASR 模型、Python 运行时等）各自适用其原始许可证，请一并附上相应声明。
> 本仓库通过 `.gitignore` 排除了 `bin/`（FFmpeg 二进制）与 `models/`（ASR 模型），因此仓库本身不重分发这些组件。
