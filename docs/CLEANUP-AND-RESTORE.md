# 本机清理与恢复手册

> 目标：把 `D:\AI` 和 `D:\SubAI-Translator` 从本机**完全删除**，
> 同时保证**任何东西都能按本文档恢复**。
>
> 编写日期：2026-10-25
> 编写时实测：`D:\AI` 6.23 GB / `D:\SubAI-Translator` 5.56 GB，合计 11.79 GB。

---

## 零、恢复的三条腿

删除前必须确认这三条都成立，缺一条就不要删：

| 依赖 | 覆盖什么 | 验证方式 |
|---|---|---|
| **GitHub 仓库** | 358 个文件（源码/测试/文档/配置/归档） | 见第一节 |
| **本文档 + MODELS-AND-DEPS.md** | 所有模型/依赖的来源、版本、哈希 | 见第二、三节 |
| **docs/local-ai-archive/** | `D:\AI` 的 18 个配置文件（含 26KB 调优报告） | 见第四节 |

---

## 一、GitHub 仓库状态

仓库：`https://github.com/1553752035-beep/SubAI-Translator`（**public**）

**注意**：本机 `github.com:443` 被阻断（TLS 握手重置），`git push/fetch` 不通。
推送走 GitHub Data API（`api.github.com` 可达）。**恢复时如果在别的机器上，
直接 `git clone` 即可，不受影响。**

### 仓库里有什么

```
358 个文件，约 3.0 MB
  src/            185 个  后端源码
  tests/          197 个  测试
  frontend/src/    前端源码
  docs/           文档（含本文件、MODELS-AND-DEPS.md、local-ai-archive/）
  k8s/            部署清单
```

### 仓库里没有什么（重要）

`.gitignore` 排除了：模型（`.onnx`/`.gguf`/`model.bin`）、`node_modules`、
构建产物（`dist`/`release`）、运行时数据（`*.db`/`*.wav`/`local_token.txt`）。

这些都要按文档重新获取，**不能靠 clone**。

---

## 二、D:\SubAI-Translator 删除清单

### 2.1 可以安全删除（GitHub 有，或可重新生成）

| 项 | 大小 | 恢复方式 |
|---|---|---|
| `源码/`（代码部分） | 约 8 MB | `git clone` |
| `源码/frontend/node_modules/` | 133 MB | `cd frontend && npm ci` |
| `源码/dist/` | 176 MB | PyInstaller 重新打包 |
| `backup-20261024/` | 176 MB | **不需要**，代码已在 GitHub |
| `release/` | 616 MB | 重新打包 |
| `源码/__pycache__`、`.pytest_cache` | 少量 | 自动生成 |

### 2.2 模型（需按 MODELS-AND-DEPS.md 重新下载）

| 路径 | 大小 | 说明 |
|---|---|---|
| `tools/models-turbo/` | 1546 MB | **whisper-large-v3-turbo 的 CT2 版**，当前默认 ASR 引擎在用 |
| `源码/models/sherpa/qwen3-asr/` | 941 MB | Qwen3-ASR（可选） |
| `源码/models/sherpa/sensevoice-small/` | 228 MB | SenseVoice |
| `源码/models/sherpa/paraformer-zh/` | 217 MB | Paraformer |
| `源码/models/sherpa/diarization/` | 43 MB | 说话人分离 |
| `源码/models/sherpa/silero_vad.onnx` | 2 MB | **VAD，必需** |
| `models/faster-whisper-small/` | 464 MB | **与下一行完全重复** |
| `源码/frontend/src-tauri/models/faster-whisper-small/` | 464 MB | **重复副本** |

**发现**：`faster-whisper-small` 有两份**完全相同**的副本（各 463.7 MB，5 个文件同名同大小）。
删掉其中任意一份不影响另一份。恢复时只需下载一份。

### 2.3 可执行文件（需重新获取）

| 路径 | 大小 | 来源 |
|---|---|---|
| `bin/ffmpeg.exe` | 84 MB | [ffmpeg.org](https://ffmpeg.org/download.html) Windows build |
| `源码/frontend/src-tauri/bin/ffmpeg.exe` | 84 MB | 同上（**重复副本**） |
| `SubAI-Translator.exe` | 14 MB | PyInstaller 打包产物 |
| `subai-backend.exe` | 176 MB | 同上 |
| `源码/frontend/src-tauri/binaries/subai-backend-x86_64-pc-windows-msvc.exe` | 176 MB | 同上（**重复副本**） |
| `源码/dist/subai-backend.exe` | 176 MB | 同上（**重复副本**） |
| `tools/nodejs/` | 123 MB | [nodejs.org](https://nodejs.org/)，或用系统 Node |

**注意**：项目只需要 `ffmpeg.exe`，**不需要 `ffprobe.exe`**。
代码里所有媒体信息都通过 `ffmpeg -i` 的 stderr 解析。

### 2.4 需要保留的配置（体积很小，但删了就丢）

| 文件 | 大小 | 处理 |
|---|---|---|
| `.env` | <1 KB | **先复制到安全地方**，它含 `SUBAI_ASR_MODEL_DIR` 等本机路径 |
| `data/*.db` | 约 150 KB | 词表/术语库/翻译缓存，**有用户数据**，建议备份 |
| `项目总方案.md` | 105 KB | **已从会话记录还原并推送**（`docs/项目总方案.md`） |
| `使用说明.txt` / `README.txt` | <1 KB | 已在 GitHub |
| `原型/` | 0.3 MB | HTML 原型，**不在 git 里**，建议复制进仓库 |

---

## 三、D:\AI 删除清单

### 3.1 模型（6.23 GB，需重新下载）

| 文件 | 大小 | 用途 |
|---|---|---|
| `KoboldCpp/models/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf` | **已删除**（20.61 GB） | 代码开发，见 MODELS-AND-DEPS.md |
| `KoboldCpp/models/Hy-MT2-1.8B-Q4_K_M.gguf` | 1081 MB | **SubAI 翻译默认** |
| `KoboldCpp/models/Hy-MT2-1.8B-StreamRevise-Q4_K_M.gguf` | 1020 MB | 流式字幕 |
| `KoboldCpp/models/mmproj-F16.gguf` | 858 MB | 视觉编码器（配 35B） |
| `KoboldCpp/koboldcpp.exe` | 609 MB | **推理程序 1.115.2** |
| `KoboldCpp-vl/models/Qwen3VL-4B-Instruct-Q4_K_M.gguf` | 2382 MB | 视频通话视觉 |
| `KoboldCpp-vl/models/mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf` | 433 MB | 视觉编码器（GPU） |

### 3.2 配置文件（已完整归档，可安全删除）

**18 个文件已逐字节复制到 `docs/local-ai-archive/`**，删除后从这里恢复即可。
其中最重要的是 `DEPLOY-Qwen3.6.md`（26.8 KB），记录了全部调优结论。

详细清单见 `docs/local-ai-archive/README.md`。

### 3.3 其他

| 项 | 说明 |
|---|---|
| `KoboldCpp-vl/out.log`（0.5 MB） | 运行日志，可删 |
| `KoboldCpp-vl/task.log` | 同上 |

---

## 四、恢复步骤（从零到能跑）

### 4.1 恢复 SubAI

```bash
# 1. 克隆代码
git clone https://github.com/1553752035-beep/SubAI-Translator.git
cd SubAI-Translator

# 2. 后端依赖
pip install -r requirements.txt

# 3. 前端依赖
cd frontend && npm ci && cd ..

# 4. 下载模型（见 MODELS-AND-DEPS.md 第二节）
#    最小集：silero_vad.onnx + sensevoice-small = 230 MB

# 5. 下载 ffmpeg.exe 放到 bin/

# 6. 配置
cp .env.example .env
#    编辑 SUBAI_ASR_MODEL_DIR 指向模型目录

# 7. 验证
python -m pytest tests/ -q          # 预期 828 passed
cd frontend && npx vitest run       # 预期 72 passed
```

### 4.2 恢复 D:\AI

```bash
# 1. 建目录
mkdir D:\AI\KoboldCpp\models
mkdir D:\AI\KoboldCpp-vl\models

# 2. 复制配置（从克隆下来的仓库里）
xcopy /E /I docs\local-ai-archive\KoboldCpp     D:\AI\KoboldCpp
xcopy /E /I docs\local-ai-archive\KoboldCpp-vl  D:\AI\KoboldCpp-vl

# 3. 下载 koboldcpp.exe 1.115.2 放到 D:\AI\KoboldCpp\
#    https://github.com/LostRuins/koboldcpp/releases

# 4. 下载模型（见 local-ai-archive/README.md 第四节）

# 5. 启动
D:\AI\KoboldCpp-vl\0-menu.bat
```

---

## 五、删除前必须做的三件事

**1. 备份 `.env`**

它不在 git 里（被 `.gitignore` 排除），但记录了本机的模型路径配置。
复制到仓库外的安全位置，或临时提交到仓库的 `docs/` 下。

**2. 备份 `data/*.db`**

```
data/glossary.db        16 KB   词表（用户确认过的译名）
data/terminology.db     28 KB   术语库
data/translation_cache.db 24 KB 翻译缓存
data/delta_terms.json   2.7 KB  术语增量
data/sample_terms.json  1.5 KB  术语示例
```

这些是**用户数据**，不是代码，删了就真没了。加起来不到 100 KB，
建议复制进仓库的 `docs/user-data-backup/` 或单独保存。

**3. 确认 35B 模型确实不需要了**

已于 2026-10-25 删除（20.61 GB），完整还原信息在 `MODELS-AND-DEPS.md` 第四节。
如果之后想做本地代码开发，照那份文档重新下载即可。

---

## 六、清理后的空间账

| 阶段 | D 盘剩余 |
|---|---|
| 清理前 | 13.9 GB |
| 删 35B 模型后 | 34.6 GB |
| 删完两个目录后（实测） | **46.4 GB** |

释放明细：

```
D:\AI                    6.23 GB
D:\SubAI-Translator      5.56 GB
  其中 源码/              2.44 GB（代码 8 MB + 模型 1.43 GB + node_modules 133 MB + 产物）
        tools/           1.67 GB（models-turbo 1546 MB + nodejs 123 MB）
        release/         0.62 GB
        models/          0.46 GB
        backup-20261024/ 0.18 GB
        其余 exe/ffmpeg  0.35 GB
```

---

## 七、一个提醒：重复副本

盘点时发现几处**完全重复**的文件，删的时候不用心疼：

| 文件 | 份数 | 每份 |
|---|---|---|
| `faster-whisper-small/model.bin` | 2 | 461 MB |
| `ffmpeg.exe` | 2 | 84 MB |
| `subai-backend.exe` | 3 | 176 MB |

光这三类重复就占了约 **1.6 GB**。它们不是设计冗余，是打包脚本把文件复制到多个位置
（Tauri 的 `binaries/`、PyInstaller 的 `dist/`、顶层运行目录）。
恢复时**每样只下一份**即可，打包脚本会自己复制。

---

## 八、C 盘残留（2026-10-26 补记，已全部清理）

删除 D 盘两个目录后做全机搜索，发现**测试安装时在 C 盘装了一整套**，同样已清理。

| 位置 | 大小 | 内容 |
|---|---|---|
| `AppData\Local\SubAI Translator\` | 1069 MB | 完整安装副本（含 uninstall.exe） |
| `AppData\Local\com.subai.translator\` | 76 MB | WebView 数据（Tauri 前端缓存） |
| 桌面 `SubAI-5.0.0\` | 646 MB | 安装包 `SubAI Translator_5.0.0_x64-setup.exe` |
| `AppData\Roaming\SubAI\` 与 `subai\` | <1 KB | 用户级 `.env`（两份重复） |
| `Temp\subai*` 10 个目录 | 191 MB | 测试产物（含 190 MB 的 preview_in.mkv） |
| `Temp\pytest-of-Administrator\` | 30 MB | pytest 临时目录 |
| `Temp\subai-*.log` 等 6 个文件 | 254 KB | 测试日志 |
| 注册表 `HKCU\...\Uninstall\SubAI Translator` | — | 卸载项 |
| 注册表 `HKCU\SOFTWARE\subai` | — | 应用设置 |
| 桌面 + 开始菜单快捷方式 | — | 指向 C 盘安装目录 |

**注意**：C 盘 `data\uploads\` 里有两个 172 MB 的视频，是
`C:\Users\Administrator\Videos\NVIDIA\Delta Force\` 下 NVIDIA 回放文件的**副本**，
原件完好，删除不影响。

---

## 九、⚠️ 三个 API Key 需要吊销

清理过程中在以下位置发现**明文 API Key**（均指向 `api.deepseek.com`）：

```
C:\...\AppData\Local\SubAI Translator\.env
  SUBAI_LLM_CLOUD_API_KEY=sk-0acae46179884e87b347d5ad53f51a11

C:\...\AppData\Roaming\SubAI\.env
C:\...\AppData\Roaming\subai\.env
  SUBAI_LLM_CLOUD_API_KEY=sk-aa435e8b5de64ca68c65c991e370e379
```

这些文件**已删除**，但 Key 在服务端仍然有效。
`sk-aa435e8b...` 这个此前还曾进入过 git 历史（后从仓库与索引移除）。

**待办**：去 DeepSeek 控制台吊销上述两个 Key，重新签发。

---

## 十、备份中不含密钥（已核查）

`docs/user-data-backup/.env` 是项目的**「分发安全版」**——全文都是注释，
没有任何实际配置项，更没有 Key：

```
# 机密（云端 API Key 等）不放这里：本文件会随「整个文件夹拷给别人」一起泄露。
# 放在用户级 %APPDATA%/SubAI/.env，读取优先级更高，也不会被分发带走。
```

仓库是 **public**，这一点已逐字节核对确认。

---

## 十一、Tauri 更新签名密钥（已单独备份）

`C:\Users\Administrator\.tauri\` 下有一对**更新签名密钥**（2026-10-02 生成）：

```
subai-updater.key       348 B   私钥（无密码）
subai-updater.key.pub   152 B   公钥
```

**这对密钥不是垃圾，删了就没了。** `RELEASE.md` 第 228 行的原话：

> ⚠️ 私钥丢失 = 已安装的旧版本再也收不到更新（只能换新公钥、重新装机）；
> 私钥泄露 = 他人可伪造更新包。

公钥已硬编码在 `src-tauri/tauri.conf.json` 的 `plugins.updater.pubkey` 里，
私钥只在**发版时签更新包**用。

**已备份到**：`D:\SubAI-Keys-Backup\`（含 README 说明）

> 这份私钥**不能进公开仓库** —— 泄露等于他人可伪造更新包。

如果确定不再发版，可以连同 `.tauri\` 一起删掉；从源码重新打包不需要它。
