# SubAI Translator

AI 视频字幕识别与翻译工具：自动提取视频里的语音或硬字幕，用大语言模型翻译成目标语言，一键生成双语字幕文件。

## 它能做什么

- **语音识别（ASR）**：把视频中的说话声转成字幕文字，适合没有字幕的视频
- **硬字幕识别（OCR）**：识别画面里已经内嵌的字幕文字，适合需要翻译现有字幕的视频
- **机器翻译**：把字幕翻译成目标语言，支持术语库保证专有名词翻译一致
- **多格式输出**：SRT / VTT / ASS / JSON
- **图形界面**：上传视频、查看实时进度、在线编辑字幕、管理术语库与历史记录

## 环境要求

| 依赖 | 说明 |
|------|------|
| Python 3.12+ | 运行后端 |
| FFmpeg | 项目已自带（`bin/` 目录），无需单独安装 |
| Node.js 18+ | 仅运行桌面/网页界面时需要 |
| NVIDIA GPU（可选） | 加速语音识别，需额外安装 `torch` |

## 快速上手

### 第 1 步：启动后端

```powershell
cd D:\SubAI-Translator
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

```
D:\SubAI-Translator
├── src/             后端代码（FastAPI）
├── frontend/        界面代码（React + Tauri）
├── bin/             FFmpeg 可执行文件
├── models/          语音识别模型
├── output/          字幕输出目录
├── data/            数据库与上传文件
├── tests/           测试用例
└── requirements.txt Python 依赖清单
```

## 常见问题

- **提示找不到模型**：将 faster-whisper 模型放到 `models/faster-whisper-small/` 目录
- **提示 GPU 不可用**：未安装 `torch` 或显存不足 4GB 时会自动回退到 CPU，属正常现象
- **云端翻译返回 401**：检查 `SUBAI_LLM_CLOUD_API_KEY` 是否已正确配置
- **端口被占用**：修改 `SUBAI_SERVER_PORT` 环境变量后重启后端

## 许可证

本项目采用 **MIT** 许可证，详见 [LICENSE](LICENSE)。

> 说明：对外分发**完整运行包**时，其中的第三方组件（FFmpeg、ASR 模型、Python 运行时等）各自适用其原始许可证，请一并附上相应声明。
> 本仓库通过 `.gitignore` 排除了 `bin/`（FFmpeg 二进制）与 `models/`（ASR 模型），因此仓库本身不重分发这些组件。
