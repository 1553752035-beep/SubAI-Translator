# SubAI-Translator 项目交接简报

> 生成：2026-10-15 ｜ 来源：DSH 会话 `session-cb8bcb01`（2026-09-29 ~ 10-03，194 轮用户对话）+ 项目文件实测
> 用途：在新会话里接手这个项目，无需回读 50 MB 原始记录

## 1. 项目是什么

**中文视频字幕 / 翻译桌面应用**：Tauri（Rust + Web 前端）+ Python 后端 + faster-whisper 语音识别。

流程：上传视频 → ASR 识别 → 翻译（本地 koboldcpp Qwen3.6-35B 或云端 DeepSeek）→ **字幕草稿确认页**（逐句可改 / 播放对照 / 合并 / 拆分 / Ctrl+Z 撤销）→ 烧录出片。

- 路径：`D:\SubAI-Translator\`
- **git 仓库根 = `源码\`**（`tools\`、`原型\` 等在仓库之外，不会被提交）
- 唯一权威方案：`D:\SubAI-Translator\项目总方案.md`（109 KB，刻意不入库）

## 2. 当前状态（10-03 之后 12 天没动过，实测确认）

| 项 | 状态 |
|---|---|
| **v5.0.0 安装包** | ✅ 已打包 + 已签名 → 桌面 `SubAI-5.0.0\`：`SubAI Translator_5.0.0_x64-setup.exe`（677 MB）+ `.sig`（428 B） |
| **启动验证** | ❌ **从未做过** —— 打包铁律第 ③ 步要求：装完必须真能启动并看到 `后端服务运行中 · localhost:8000`（= health 200） |
| `.venv` / `dist` / `target` | ❌ 10-03 瘦身时清空（20+ GB → 2.72 GB）。**要改代码必须先重建 Python 环境** |
| 项目文件 | 最后修改 `10-03 12:00`，此后无任何改动 |
| `_lessons-2026-10-03.md` | 已不存在（当初记录了打包/签名与瘦身教训，内容已并入记忆） |

## 3. 下一步（建议顺序）

1. **启动验证 v5.0.0**（最优先，成本最低）：装桌面那个安装包 → 打开 → 确认左下角出现 `后端服务运行中 · localhost:8000` → 跑一个短视频（只加字幕最快）→ 看能否出字幕草稿。
2. **重建开发环境**：`cd D:\SubAI-Translator\源码 && pip install -r requirements.txt`。注意 10-03 特意删掉了约 2 GB 的 PyTorch + CUDA DLL —— **只装真正需要的依赖**，别让它胖回去。
3. **剩下的优化项**：用户 10-03 原话是「剩的一些优化问题明天再说」，未具体化。原会话 10:50 还提过「还差两步才算可发布」，末尾没展开 —— 需要时回原会话检索。
4. **重新打包**：见下节签名坑。

## 4. 必须知道的坑（每条都有血证）

1. **Tauri 签名会卡死**：更新私钥无密码，而 Tauri 在非交互环境会停在 `Password:` 等你输入 → 后台跑会永久挂起并残留 node 进程（还会锁住 node.exe）。**只能在前台终端跑，提示 Password 时直接回车**。管道喂回车、`npm run ... -p ''`、直接 CLI `-p ''` 三条非交互路子全部实测无效。
2. **`TAURI_SIGNING_PRIVATE_KEY` 要放密钥内容**，放路径会报 `Invalid symbol 58`；路径要用 `TAURI_SIGNING_PRIVATE_KEY_PATH`。
3. **打包铁律四条**：打包前先 `python -c "import src.api.server"`；PyInstaller 在语法错误时会静默产出残 exe（退出码仍是 0）；打包后必须真启动看到 health=200；必须确保只有一个 subai-backend 实例。
4. 删除语义 / 路由冲突 / 云端 URL 污染 / 叠字导致测试假失败 / jsdom 缺 scrollIntoView —— 这 6 条已在运行时记忆中，每轮自动注入。

## 5. 环境与配置

- **Node / npm / mnemon CLI**：`D:\SubAI-Translator\tools\nodejs\`（10-03 从 D:\PythonProject5 迁入，在 git 仓库之外）
- **API key 与后端配置**：`D:\SubAI-Translator\.env`（云端指向 `https://api.deepseek.com/v1/chat/completions`，曾误指向 koboldcpp 导致云端翻译全失败）
- **本地模型**：koboldcpp（用户侧手动开）
- 数据：`data\tasks.db`、`terminology.db`（术语库）、`translation_cache.db`、`users.db`

## 6. 关于「把旧对话搬过来」

原会话解压后 **50.3 MB / 14351 条事件 / 1571 步 / 1327 次工具调用**，约上千万 token，远超 1M 上下文窗口——**物理上装不进任何新会话**。

完整原文仍保留在：
`~/.dsh/sessions/--C-Users-Administrator-Documents-deepseek-harness-default-workspace--/session-cb8bcb01-99e3-4ab3-8080-3ee34f219d49/session.v4.jsonl.zstd`
（多帧 zstd 拼接；Node 的 `createZstdDecompress` 只解第一帧，需按帧魔数 `28 B5 2F FD` 切分逐帧解压）

另：该项目下还挂着 68 个子代理会话，是当时跑子任务的记录。
