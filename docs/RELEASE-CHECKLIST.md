# 发布前检查清单（1 页）

> 用途：发版前逐项打勾，避免再出现「打包成功但装上去不能用」。
> 打包本身用 `powershell -ExecutionPolicy Bypass -File scripts/build_release.ps1`（可选 `-Sign`）。

## A. 代码门禁

- [ ] `python -c "import src.api.server"` 通过（**铁律①**：语法错误会让 PyInstaller 静默产出残 exe）
- [ ] `RUN_API_TESTS=1 python -m pytest tests -q` 全绿
- [ ] `cd frontend && npx vitest run` 全绿、`npx tsc -b` 0 错误
- [ ] 版本号一致：`src/__init__.py`、`frontend/package.json`、`src-tauri/tauri.conf.json`、
      `src-tauri/Cargo.toml`、`frontend/package-lock.json` 五处相同
- [ ] **所有 `tools\*.ps1` 带 UTF-8 BOM**（**铁律②**：含中文的 ps1 缺 BOM 会被 PS5.1 按 ANSI 读，
      直接语法错误。每次用编辑器/脚本改过 ps1 后都要复查：`head -c 3 xxx.ps1 | od -An -tx1` 应输出 `ef bb bf`）

## B. 产物一致性（**最容易翻车的一项**）

- [ ] `scripts/build_release.ps1` 的步骤 5 显示「binaries 副本与 dist 一致」
- [ ] 安装目录里的 `subai-backend.exe` 与 `dist/subai-backend.exe` 大小一致
- [ ] **后端新旧快速判别**：装完启动后，不带令牌请求新接口 ——
      `GET /api/term-packs` 返回 **401 = 新后端（对）**；返回 **404 = 旧后端（混搭包）**

## C. 真机验收（装完必须做，不能只看「打包成功」）

- [ ] 静默安装或双击安装成功，装到 `%LOCALAPPDATA%\SubAI Translator`
- [ ] 启动后左下角显示「后端服务运行中 · localhost:8000」
- [ ] `netstat -ano | findstr :8000` 只有 **1 个** LISTENING（多实例会让任务被错误实例处理）
- [ ] 跑一条短视频 → 停在**字幕草稿/确认页**（不自动出片）
- [ ] 确认页改一句 → 保存 → 「生成视频」→ 成品出现在源视频同目录
- [ ] 关闭主程序后没有残留的 `subai-backend.exe`

## D. 分发安全

- [ ] 项目根 `.env` 不含机密：机密应在用户级 `%APPDATA%\SubAI\.env`（程序读取优先级更高、不会被分发带走）。
      `tools\build_green_package.ps1` 已有硬闸门，检测到含机密的 `.env` 会 `exit 3` 中止构建
- [ ] 检查 `data\` 里是否有测试任务（回收站 → 彻底移除）

## E. 发版（要自动更新才需要）

- [ ] 有签名版：`build_release.ps1 -Sign`（签名会提示 Password，**必须前台回车**，后台会挂起）
- [ ] 产物 `*-setup.exe` + `.sig` 同时上传
- [ ] 用 `tools\make_latest_json.ps1` 生成 `latest.json`（从安装包旁 `.sig` 读取签名；缺签名会直接报错退出，不会产出坏文件）
- [ ] 建 Release 后确认 `releases/latest/download/latest.json` 返回 200
- [ ] 用旧版本应用点一次「检查更新」验证链路

## F. 已知遗留（发布时可接受）

- [ ] 容器化 V-1~V-3（Docker / Compose / K8s）需真实环境，本机无法验证
- [ ] 安装包体积约 615 MB（含 ASR 模型）；精简版约 240 MB（不含模型）
