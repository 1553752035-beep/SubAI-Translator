# KoboldCpp 启动项对照表

三个实例共用一块 8GB 显卡（RTX 4070 Laptop），**不要同时运行**。

## 谁是谁

| 端口 | 用途 | 模型 | 显存 | 加载耗时 | 脚本 |
|---|---|---|---|---|---|
| **5001** | **SubAI-Translator** 字幕翻译 | Qwen3.6-35B-A3B | 约 7GB | 1–3 分钟 | `D:\AI\KoboldCpp\start-qwen36-a3b.bat` |
| **5002** | DSH 原适配（含视觉） | Qwen3.6-35B-A3B | 约 7GB | 1–3 分钟 | `D:\AI\KoboldCpp\start-dsh-profile.bat` |
| **5003** | **视频通话视觉**（新增） | Qwen3-VL-4B | **4.6GB** | **10–30 秒** | `D:\AI\KoboldCpp-vl\start-5003-video.bat` |

> 5001 和 5002 读同一个 21GB 的 `Qwen3.6-35B-A3B-UD-Q4_K_M.gguf`，只是参数不同。
> 5003 用独立 3GB 小模型，目录也独立。

## 怎么起

**统一菜单（推荐）**
```
D:\AI\KoboldCpp-vl\0-menu.bat
```
菜单里能直接看到三个实例的区别，还能查显存和端口占用。

**单独起**
```
D:\AI\KoboldCpp-vl\start-5003-video.bat     ← 视频通话
D:\AI\KoboldCpp\start-qwen36-a3b.bat        ← SubAI
D:\AI\KoboldCpp\start-dsh-profile.bat       ← DSH 原适配
```

## 5003 是什么、为什么要它

给 DSH 手机视频通话用的**专用视觉模型**。

| | 5002（原适配） | 5003（视频通话） |
|---|---|---|
| 模型 | 35B MoE（文本为主挂视觉） | **4B 专用 VL** |
| 视觉编码器 | CPU（`--mmprojcpu`） | **GPU** |
| 视觉编码耗时 | — | **90 ms** |
| 单张 640×360 帧 | 不可用（28.5s/截图） | **342–715ms（平均 445ms）** |
| 上下文 | 98304 | 16384 |
| 适用 | 单张截图理解 | 连续抽帧 |

## 实测结果（2026-10-27）

**精度**
- 640×360 纯色图 → 4/4 全对（绿黄 / 蓝红 / 黑白 / 橙紫）
- 判别性问题「中间有没有白色竖线」→ 答「有」✅ 证明真在看图
- 2560×1600 游戏界面 → 正确认出 M4A1 改装界面，中文文字全对
- 2560×1530 VS Code → 正确认出 Python 环境、main.py、llama.cpp
- 1264×369 动漫图 → 正确描述 + 发现小红书水印

**延迟**
| 场景 | 耗时 |
|---|---|
| 首次请求（CLIP 预热） | 6420 ms |
| 同一图重复（smartcache 命中） | 116–119 ms |
| **不同图 640×360（真实场景）** | **342–715 ms，平均 445 ms** |
| 2560×1600 截图 | 2291 ms |
| 1264×369 截图 | 876 ms |

**日志证据**
```
clip_ctx: CLIP using CUDA0 backend        ← 视觉编码器在 GPU
image_tokens: nx=22 ny=13 = 286 tokens
clip_image_batch_encode: 704×416
image slice encoded in 90 ms
image decoded in 23 ms
```

## 目录结构

```
D:\AI\KoboldCpp\               ← 原有，本方案未修改任何文件
   ├─ koboldcpp.exe              （被 5003 复用，只读执行）
   ├─ models\
   │   ├─ Qwen3.6-35B-A3B-UD-Q4_K_M.gguf   21GB（5001/5002 用）
   │   └─ mmproj-F16.gguf                  899MB
   ├─ start-qwen36-a3b.bat      → 5001 SubAI
   └─ start-dsh-profile.bat     → 5002 DSH

D:\AI\KoboldCpp-vl\            ← 全新，本方案创建
   ├─ 0-menu.bat                统一菜单
   ├─ start-5003-video.bat      端口 5003
   ├─ download-models.bat       首次下载 3GB
   ├─ README.md                 本文件
   └─ models\
       ├─ Qwen3VL-4B-Instruct-Q4_K_M.gguf       2.50GB
       └─ mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf  0.45GB
```

## 接进 DSH

**设置 → 模型选项 → 添加模型提供商 → 自定义模型 API**

| 字段 | 值 |
|---|---|
| API 地址 | `http://127.0.0.1:5003/v1` |
| 模型 ID | `koboldcpp` |
| 上下文窗口 | 16384 |
| 最大输出 | 2048 |
| **输入类型** | **勾选「图片」**（不勾发不出图） |

## 常见问题

**Q: 中文乱码**
不会。bat 文件是 GBK 编码，脚本第一行 `chcp 936` 已适配。文件名用 ASCII 是为了避免命令行传参乱码。

**Q: 启动报「模型不存在」**
先跑 `download-models.bat`，约 3GB，支持断点续传。

**Q: 显存不够 / 很卡**
三个实例别同时开。菜单里选 [5] 查显存。

**Q: 还想更快**
改 `start-5003-video.bat`：`--visionmaxtokens 256` 降到 128，或 `--contextsize` 降到 8192。

**Q: 端口被占**
改 `--port 5004`，同步改 DSH 表单地址。

**Q: 为什么不用 Ollama**
按要求复用现有 KoboldCpp，避免再装一套推理框架。
