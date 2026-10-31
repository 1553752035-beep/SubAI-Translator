# 模型与依赖清单（按需重新下载）

> 这份文档的唯一用途：**当本地模型被删除后，照着它把开发环境还原回来。**
> 代码本身在 GitHub 仓库里，不需要这份文档；这里只记「哪些东西不跟着仓库走、从哪来、放哪里」。

生成日期：2026-10-25

---

## 一、为什么要单独记这份清单

项目目录 `D:\SubAI-Translator` 占 5.6 GB，但**真正的代码只有 6.4 MB**。
其余 99.8% 是模型文件和依赖，它们有明确的上游来源，删掉随时能重新拉。

GitHub 存不了这些：单文件硬上限 100 MB，仓库建议 1 GB 以内。
Git LFS 也不行 —— 免费额度只有 1 GB 存储 + 1 GB/月流量，
放一个模型就超额，而且**每次 clone 都在烧流量额度**。

所以策略是：**代码进仓库，模型记来源，需要时重新下载。**

---

## 二、ASR 模型（sherpa-onnx）

位置：`源码/models/sherpa/`

| 目录 | 大小 | 用途 | 是否必需 |
|---|---|---|---|
| `sensevoice-small/` | 228 MB | SenseVoice 识别（中文最快，4.1s/146s 音频） | 推荐 |
| `paraformer-zh/` | 217 MB | Paraformer 识别（中文稳定，3.9s） | 推荐 |
| `qwen3-asr/` | 941 MB | Qwen3-ASR（多语种最准，23.0s，慢 5.6 倍） | 可选 |
| `diarization/` | 43 MB | 说话人分离（pyannote 分段 + 3dspeaker 声纹） | 可选 |
| `silero_vad.onnx` | 2 MB | VAD 语音切分 | **必需** |
| `gtcrn_simple.onnx` | 0.5 MB | 降噪（默认关闭） | 可选 |

### 各文件明细

```
diarization/3dspeaker-eres2net.onnx          38 MB
diarization/pyannote-segmentation.onnx        6 MB
paraformer-zh/model.int8.onnx               217 MB
qwen3-asr/conv_frontend.onnx                 42 MB
qwen3-asr/decoder.int8.onnx                 721 MB
qwen3-asr/encoder.int8.onnx                 174 MB
qwen3-asr/tokenizer/merges.txt                2 MB
qwen3-asr/tokenizer/vocab.json                3 MB
sensevoice-small/model.int8.onnx            228 MB
```

### 下载方式

全部来自 HuggingFace 上的 [k2-fsa/sherpa-onnx](https://huggingface.co/csukuangfj) 系列仓库。
仓库名规律是 `sherpa-onnx-<模型名>`，例如：

```
sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17
sherpa-onnx-paraformer-zh-2023-09-14
sherpa-onnx-qwen3-asr-0.6B-int8-2025-06-25
sherpa-onnx-pyannote-segmentation-3-0
3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k
silero_vad.onnx（在 sherpa-onnx 主仓库的 assets 里）
```

**国内下载注意**：`huggingface.co` 直连经常不通，用镜像 `hf-mirror.com`。
但镜像有两个坑（本项目实测）：

1. 必须带 `User-Agent: Mozilla/5.0`，否则 403
2. 必须在 URL 后加 `?download=true`，否则拿到的是 HTML 页面而不是文件

示例：

```bash
curl -L -H "User-Agent: Mozilla/5.0" \
  "https://hf-mirror.com/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/model.int8.onnx?download=true" \
  -o models/sherpa/sensevoice-small/model.int8.onnx
```

---

## 三、Whisper 模型（CTranslate2）

位置：`tools/models-turbo/`（1.5 GB）

```
model.bin                1543 MB
tokenizer.json              3 MB
vocabulary.json             1 MB
config.json / preprocessor_config.json / README.md
```

**来源**：[openai/whisper-large-v3-turbo](https://huggingface.co/openai/whisper-large-v3-turbo)
的 CTranslate2 转换版，仓库是 `Systran/faster-whisper-large-v3-turbo`。

由 `.env` 的 `SUBAI_ASR_MODEL_DIR` 指定路径。

**注意**：这是默认 ASR 引擎（whisper）的模型。如果只用 sherpa 系列引擎
（sensevoice/paraformer/qwen3），这个 1.5 GB **可以不下载** ——
在设置里把 ASR 引擎切到 sherpa 系列即可。

---

## 四、本地翻译模型（KoboldCpp）

位置：`D:\AI\KoboldCpp\models\`（共 26.9 GB，其中 24.1 GB 是模型）

| 文件 | 大小 | 用途 | 是否必需 |
|---|---|---|---|
| `Qwen3.6-35B-A3B-UD-Q4_K_M.gguf` | **21.1 GB** | 大模型，质量最高 | **建议删**（见下） |
| `Hy-MT2-1.8B-Q4_K_M.gguf` | 1.08 GB | **当前实际使用的翻译模型** | 保留 |
| `Hy-MT2-1.8B-StreamRevise-Q4_K_M.gguf` | 1.02 GB | 流式修订版 | 保留 |
| `mmproj-F16.gguf` | 0.86 GB | 多模态投影（视觉） | 可选 |
| `koboldcpp.exe` | 0.61 GB | 推理程序本体 | **必需** |

### 关于那个 21 GB 的 Qwen3.6-35B

项目文档记录（`docs/KNOWN-LIMITS.md` 与 CHANGELOG 5 期）：
**本地翻译最终选的是 Hy-MT2-1.8B 基座**，理由是实测更优 ——
专用翻译模型在字幕这种短句场景上比通用大模型更稳，而且快得多。

所以这个 21 GB 大概率**当前没在用**。删掉它一次性腾出 21 GB，
比折腾云端备份划算得多。**但删之前需要确认** —— 我不会擅自动手。

**重新下载**：KoboldCpp 的模型都在 HuggingFace 上，搜文件名即可。
`Hy-MT2-1.8B` 是腾讯混元的翻译模型（`tencent/Hunyuan-MT-7B` 系列的小尺寸版）。

---

### 已删除：Qwen3.6-35B-A3B（本地代码开发用，2026-10-25 移除）

这个模型**不是 SubAI 项目的依赖**，是准备用来做本地代码开发的。
项目选型文档里从未出现它（本地翻译用的是 Hy-MT2-1.8B 基座）。
2026-10-25 删除以腾出空间，以下是完整还原信息。

**删除时记录的文件事实**（读 GGUF 头部得到，不是猜的）：

```
文件名      Qwen3.6-35B-A3B-UD-Q4_K_M.gguf
大小        22,134,528,992 字节 (20.61 GB)
原位置      D:\AI\KoboldCpp\models\
GGUF 版本   3
张量数      733
元数据项    54
架构        qwen35moe      ← MoE 结构
模型名      Qwen3.6-35B-A3B
规模标签    35B-A3B        ← 总参 35B，激活 3B
许可        apache-2.0
```

**上游来源**：[Qwen/Qwen3.6-35B-A3B](https://huggingface.co/Qwen/Qwen3.6-35B-A3B)
（Apache-2.0，可商用）。

**量化版本**：`UD-Q4_K_M` 里的 `UD` 是 Unsloth Dynamic 量化的标记，
即 `unsloth/Qwen3.6-35B-A3B-GGUF` 仓库的 UD-Q4_K_M 档。
下载时认准文件名里的 `UD-Q4_K_M`，普通的 `Q4_K_M` 是另一种量化，大小和表现都不同。

**重新下载**（国内用镜像，注意 UA 和 download=true 两个坑，见第二节）：

```bash
# 官方
curl -L -H "User-Agent: Mozilla/5.0"   "https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf?download=true"   -o Qwen3.6-35B-A3B-UD-Q4_K_M.gguf

# 国内镜像
curl -L -H "User-Agent: Mozilla/5.0"   "https://hf-mirror.com/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf?download=true"   -o Qwen3.6-35B-A3B-UD-Q4_K_M.gguf
```

**跑起来**（本机 RTX 4070 Laptop，8 GB 显存 —— 装不下 20.6 GB，必然走 CPU 卸载）：

```bash
cd D:\AI\KoboldCpp
koboldcpp.exe --model models\Qwen3.6-35B-A3B-UD-Q4_K_M.gguf   --port 5001 --contextsize 8192 --gpulayers 20 --usecublas
```

`--gpulayers` 需要实测调：20 层大概是 8 GB 显存的极限，
再高会 OOM，再低就纯 CPU（很慢）。MoE 结构的好处是激活参数只有 3B，
**CPU 推理比同规模稠密模型快得多**，实际可用性比 35B 这个数字看起来好。

**如果要接进 SubAI 做本地翻译**：改 `.env` 的 `SUBAI_LLM_LOCAL_URL` 指向这个端点即可，
但**不建议** —— 项目实测 Hy-MT2-1.8B 在字幕短句上更准（2/33 错译 vs 通用模型通常更差），
而且快得多。这个模型适合的是**代码补全/长文推理**，不是字幕翻译。

---

## 六、Node.js（前端构建）

位置：`tools/nodejs/`（123 MB）

版本可以从 `frontend/package.json` 的 `engines` 字段或 `package-lock.json` 推。
也可以直接用系统已装的 Node —— 项目不强依赖这个内置副本。

**重新获取**：从 [nodejs.org](https://nodejs.org/) 下载对应版本，或用 nvm。

---

## 七、前端依赖

位置：`frontend/node_modules/`（约 700 MB，已被 `.gitignore` 排除）

**完全不需要备份**，一条命令还原：

```bash
cd frontend
npm ci        # 严格按 package-lock.json 装，版本完全一致
```

`npm ci` 比 `npm install` 好：它不会改写 lock 文件，装出来的版本与提交时一模一样。

---

## 八、系统依赖

| 依赖 | 用途 | 说明 |
|---|---|---|
| FFmpeg | 音视频处理 | `bin/ffmpeg.exe`（约 80 MB），从 [ffmpeg.org](https://ffmpeg.org/download.html) 下 Windows build |
| Python 3.14.3 | 后端运行时 | 本项目实测在 3.14 上可用 |
| CUDA / cuDNN | GPU 加速（可选） | CTranslate2 用；CPU 也能跑，只是慢 |

**FFmpeg 注意**：项目只需要 `ffmpeg.exe`，**不需要 `ffprobe.exe`**。
代码里所有媒体信息都通过 `ffmpeg -i` 的 stderr 解析，没有调用 ffprobe。

---

## 九、完整还原步骤

假设代码已经从 GitHub clone 下来，从零还原到可运行：

```bash
# 1. 后端依赖
pip install -r requirements.txt

# 2. 前端依赖
cd frontend && npm ci && cd ..

# 3. ASR 模型（按需，最小集 = VAD + sensevoice）
#    见第二节的下载命令

# 4. FFmpeg
#    下载 ffmpeg.exe 放到 bin/

# 5. 配置
cp .env.example .env
#    编辑 .env，填 SUBAI_ASR_MODEL_DIR 等

# 6. 验证
python -m pytest tests/ -q
cd frontend && npx vitest run
```

### 最小可运行集（不含可选模型）

| 项 | 大小 |
|---|---|
| 代码 | 6.4 MB |
| 前端依赖 | 约 700 MB |
| FFmpeg | 80 MB |
| silero_vad.onnx | 2 MB |
| sensevoice-small | 228 MB |
| **合计** | **约 1 GB** |

也就是说：**从 5.6 GB 压到 1 GB 是可行的**，前提是接受「只跑 SenseVoice 引擎」。
要保留 Qwen3 就再加 941 MB。

---

## 十、删之前该确认的事

删除任何模型前，逐条确认：

1. **当前默认引擎是什么？** 看 `.env` 的 `SUBAI_ASR_ENGINE`。
   如果没设，默认是 `whisper` —— 那 `models-turbo` 那 1.5 GB 就**不能删**。
2. **本地翻译在用哪个模型？** 看 KoboldCpp 启动参数或项目设置。
   如果是 Hy-MT2-1.8B，那 21 GB 的 Qwen3.6-35B 可以删。
3. **降噪开着吗？** `SUBAI_ASR_DENOISE`。开着就留 `gtcrn_simple.onnx`（0.5 MB，很小）。
4. **说话人分离用得上吗？** 用不上可以删 `diarization/`（43 MB）。

---

## 十一、验证清单（还原后跑一遍）

```bash
# ASR 引擎是否都能加载
python -c "import sys; sys.path.insert(0,'.'); from src import asr_sherpa; print(asr_sherpa.models_available())"

# 实际识别一段（用项目里的测试音频或自己的）
python -c "import sys; sys.path.insert(0,'.'); from src import asr_sherpa; print(len(asr_sherpa.transcribe(r'路径', which='sensevoice')))"

# 翻译链路
python -m pytest tests/test_translate_free.py tests/test_llm_providers.py -q
```

预期输出（模型齐时）：

```
{"sensevoice": True, "paraformer": True, "qwen3": True,
 "firered": False, "vad": True, "denoise": True}
```

`firered: False` 是正常的 —— 这个模型（739 MB）项目代码支持但从未下载，
因为 Qwen3 已经覆盖了它的场景。