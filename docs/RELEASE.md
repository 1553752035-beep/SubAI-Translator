# 发布流程与踩坑记录

面向维护者：如何把一次改动安全地发出去（推送 → CI → Release），
以及本项目在真实环境里踩过的坑。**这些坑都真实发生过，不是假想。**

---

## 0. 目标平台

| 组件 | 平台 |
|---|---|
| 桌面端 + 语音合成 | **Windows 10/11**（SAPI、`bin\ffmpeg.exe`、CUDA DLL 目录加载、Tauri）|
| 后端 | Windows（源码方式 / 绿色版）；另有 Linux 容器镜像（`Dockerfile` / `docker-compose.yml`）|

---

## 1. CI 设计（`.github/workflows/ci.yml`）

| 任务 | 运行器 | 说明 | 阻塞 |
|---|---|---|---|
| `backend` | **windows-latest** | 目标平台。FFmpeg 用 `choco` 安装且 `continue-on-error`（装不上时相应用例自动跳过） | 是 |
| `frontend` | **windows-latest** | `npm ci` → `npx tsc -b` → `npm test` | 是 |
| `container` | ubuntu-latest | `docker build` → `docker run` → 轮询 `/api/health` → 失败打印容器日志 | **否** |

**为什么后端/前端必须跑 Windows**：SAPI 语音合成、`bin\ffmpeg.exe`、CUDA DLL 目录加载、
PyInstaller 单文件、Tauri 桌面端都是 Windows 专有。跑在 Linux 上的话，这些路径会被大量跳过，
**等于没有验证真实目标平台**。

**为什么容器任务非阻塞**：容器路径在首次验证前从未真实运行过，首跑失败是**有信息量的结果**，
不应该在拿到日志之前就拦住提交。验证通过后可以随时把它改成阻塞。

---

## 2. 发布前检查清单

```powershell
cd <安装目录>\源码

# 1) 测试全绿（后端 314 项 / 前端 34 项）
$env:RUN_API_TESTS=1; .venv\Scripts\python.exe -m pytest tests -q
cd frontend; npm test; npx tsc -b; cd ..

# 2) 安全复核：确认没有密钥与开发机绝对路径（见第 6 节）
# 3) 编码复核：确认含中文的 .ps1 都带 BOM（见第 5 节）

# 4) 构建产物
.venv\Scripts\python.exe -m PyInstaller --noconfirm subai_backend.spec
cd frontend; npm run tauri:build -- --no-bundle; cd ..

# 5) 组装绿色包并自检
powershell -ExecutionPolicy Bypass -File tools\build_green_package.ps1 -OutDir D:\SubAI-Green
D:\SubAI-Green\subai-backend.exe --check

# 6) 推送（会自动触发 CI）
git add -A; git commit -m "..."; git push origin main
```

推送后确认三个 CI 任务全绿，再创建/更新 Release。

---

## 3. 只有 CI 才会暴露的两类问题（都踩过）

### ① 锁文件必须提交

`frontend/.gitignore` 曾忽略 `package-lock.json`（脚手架模板的默认行为）。
后果：CI 的 `actions/setup-node` 报
`Some specified paths were not resolved, unable to cache dependencies`，
`npm ci` 也无从执行——前端任务在第 3 步就挂了。

**规则**：应用项目（非库）必须提交锁文件。库项目才忽略它。

### ② 测试不能假设运行环境的能力

CI 的 windows runner **只装英文 SAPI 音色**，而用例让它读中文「你好」：
SAPI 合成出"只有文件头、0 采样"的 wav（**实测 46 字节 / 0.000 秒**），
于是 `wav_duration > 0.1` 断言失败。本机装有 `Microsoft Huihui (zh-CN)`，所以一直通过。

**规则**：端到端用例要**显式挑选存在的资源**（音色/字体/模型），并让输入与其能力匹配；
不要假设"本机有，CI 也有"。

---

## 4. 网络受限环境：推送与分发

### 4.1 推送

实测本机 `github.com:443` **间歇不可达**（同期的 `api.github.com` / `ssh.github.com` /
`codeload.github.com` 正常）：一次 `git ls-remote` 1.9 秒成功，随后 21 秒超时，重试又通。

应对：
1. 首次推送用 **Git Credential Manager 浏览器授权**（本机 `credential.helper=manager`）；
   授权窗口标题为 **Connect to GitHub**，选「Sign in with your browser」→ 浏览器里 Authorize。
   ⚠️ 授权完成前不要关闭该窗口。
2. 推送用**重试循环**（本机实测第一次就成功）：
   ```powershell
   for ($i=1; $i -le 6; $i++) { git push origin main; if ($LASTEXITCODE -eq 0) { break }; Start-Sleep 8 }
   ```
3. 若浏览器授权反复失败，可改用 SSH（`ssh.github.com:443` 实测稳定可达）：
   生成密钥 → 把公钥加到 GitHub → `~/.ssh/config` 里 `Host github.com` 指向
   `ssh.github.com:443` → `git remote set-url origin git@github.com:<user>/<repo>.git`。

### 4.2 分发大文件

实测 GitHub **大文件传输基本不可用**：gh CLI（14.8 MB）下载 **90 秒 0 字节**；
0.65 GB 的完整绿色包上传被拒（`can't process that file`，应为传输损坏）。

应对：
- **精简包**（约 237 MB，含 FFmpeg，**不含 ASR 模型**）作为 Release 附件，用**浏览器**上传；
- 模型（约 464 MB）由使用者用 `tools/fetch_ct2_model.ps1` 获取——该脚本走 hf-mirror 镜像，
  curl `-C -` 断点续传、低速自动重连，正是为这种网络写的；
- 完整包（含模型）建议走国内网盘分发，而不是 GitHub。

---

## 5. PowerShell 5.1 的 UTF-8 三连坑（务必记住）

| # | 坑 | 表现 | 正确做法 |
|---|---|---|---|
| 1 | `Get-Content` **不带 `-Encoding`** 时按系统 ANSI(GBK) 解码 | 读 UTF-8 文件得到乱码（曾导致 Release 说明粘成乱码） | `[System.IO.File]::ReadAllText($p, [System.Text.Encoding]::UTF8)` |
| 2 | 含中文的 **`.ps1` 无 BOM** → PS 5.1 按 GBK 解析，**直接语法错误** | `build_gpu_pack.ps1` 曾经完全跑不起来 | 用 **UTF-8 带 BOM** 保存；改完用解析器校验 |
| 3 | **`.gitignore` / `.env.example` 加 BOM** | BOM 会成为第一行内容的一部分，规则/键名被破坏 | 这两个文件**保持无 BOM** |

写完 `.ps1` 一定校验一次：
```powershell
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$null, [ref]$errors)
if ($errors.Count) { $errors | ForEach-Object Message }
```

---

## 6. 安全复核（上传前必做）

```powershell
# 当前树与全部历史里搜密钥 / 开发机路径 / 机器名
git ls-files            # 取列表后用正则扫描内容
git rev-list --all      # 逐提交扫描历史
git status --ignored    # 核对忽略集是否符合预期
```

要点：
- 仓库体积要小（本项目打包后 362 KB）——**一旦把大文件提交进历史，之后就很难清干净**；
- 确认 `.gitignore` 覆盖 `.env` / `*.db` / `output/` / `dist/` / `build/` / `target/` /
  `node_modules/` / `models/` / `/bin/` / `data/uploads/`；
- 发布产物里不应残留开发机绝对路径（本项目曾在 Tauri 侧找出一处写死的兜底路径，已移除）。

---

## 7. 绿色版与 Release

- 组装：`tools/build_green_package.ps1 -OutDir <目录>`（一条命令，含校验与说明文件）；
- 目录内所有路径都由 exe 位置推导，可整体拷贝到其他机器（已在全新目录实测）；
- Release 附件用**浏览器**上传（shell 走不通，见 4.2）；
- Release 说明里要写清：**不含模型**、如何获取模型、需要自备翻译服务、
  硬字幕识别不需要模型。

---

## 8. 常见故障对照表

| 现象 | 原因 | 处理 |
|---|---|---|
| CI 前端挂在 `setup-node` | 锁文件未提交 | 提交 `package-lock.json` |
| CI 后端某个 SAPI 用例失败 | runner 只有英文音色，用例却读中文 | 用例挑选存在的音色并匹配文本语言 |
| `git push` 报 `Failed to connect to github.com port 443` | 本机 github.com 间歇不可达 | 重试循环；或改走 SSH（`ssh.github.com:443`）|
| 推送时弹出 **Connect to GitHub** | 首次需要凭据 | 选「Sign in with your browser」并完成授权 |
| Release 附件上传报 `can't process that file` | 大文件传输损坏 | 改用精简包 / 网络盘 |
| `.ps1` 报 `Unexpected token` / 字符串未终止 | 含中文但无 BOM | 另存为 UTF-8 带 BOM |
| 粘贴中文变乱码 | `Get-Content` 默认 GBK | 用 `[System.IO.File]::ReadAllText(..., UTF8)` |
