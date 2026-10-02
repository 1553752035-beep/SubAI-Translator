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

---

## 9. 危险操作纪律（因一次真实事故而写）

**事故（2026-10-01）**：一条 `cmd /c "rd /s /q \"$path\""` —— PowerShell 的转义符是反引号而非反斜杠，
参数被拆坏成**根路径**，于是从 D 盘根开始递归删除。`rd` **不进回收站**，大量用户文件被永久删除；
事后靠编辑器本地历史（`User\History`）与 USHA 日志才逐步确认损失范围并恢复部署文件。

**硬性纪律（写代码/写脚本时同样适用）**：

1. **删除前必须打印解析后的绝对路径并逐条核对**（`Resolve-Path` / `Get-Item`），确认无误再动手；
2. 一律使用 **`Remove-Item -LiteralPath`**；**永不**用 `cmd /c` 拼字符串执行 `rd` / `del` / `rmdir`；
3. **绝不对根路径或驱动器执行递归删除**；递归前先确认目标至少包含两层已知目录；
4. **禁止通配符删除**，必须逐个列出具体路径；
5. 破坏性操作前先做**可验证的备份**（如本次的"复制 → SHA256 校验 → 才删除"流程）；
6. 需要给用户的机器做清理时，**先列清单、再让用户确认**，不擅自扩大范围。

> 恢复优先级参考：编辑器本地历史（VS Code / CodeBuddy 的 `User\History`）> 卷影副本 > 回收站 > 文件恢复工具。
> SSD + TRIM 开启时，文件恢复工具基本无效——**事前谨慎是唯一的保险**。

---

## 10. 安装包与自动更新（五期准备）

### 10.1 构建安装包（NSIS）

```powershell
cd 源码/frontend

# 精简版（不含 ASR 模型，约 290 MB）—— 与既有 lite 发布策略一致
npm run tauri:build -- --bundles nsis --config src-tauri/tauri.lite.conf.json

# 完整版（含 faster-whisper-small，约 760 MB）
npm run tauri:build -- --bundles nsis
```

产物：`src-tauri/target/release/bundle/nsis/SubAI Translator_4.1.0_x64-setup.exe`

**首次打包会从 GitHub 下载 NSIS 工具链**（`nsis-3.11.zip`）。网络不通时的兜底
（用镜像手动放到缓存目录，之后打包不再联网）：

```powershell
$dir = Join-Path $env:LOCALAPPDATA "tauri\NSIS"; New-Item -ItemType Directory -Force $dir | Out-Null
curl.exe -L -o "$dir\nsis-3.11.zip" `
  "https://gh-proxy.com/https://github.com/tauri-apps/binary-releases/releases/download/nsis-3.11/nsis-3.11.zip"
```

### 10.2 自动更新（Tauri Updater）

| 项 | 值 |
|---|---|
| 私钥 | `C:\Users\Administrator\.tauri\subai-updater.key`（**无密码，务必离线备份**）|
| 公钥 | 已写入 `src-tauri/tauri.conf.json` → `plugins.updater.pubkey` |
| 更新源 | `https://github.com/1553752035-beep/SubAI-Translator/releases/latest/download/latest.json` |
| 安装模式 | `passive`（静默安装，只在最后提示）|

> ⚠️ **私钥丢失 = 已安装的旧版本再也收不到更新**（只能换新公钥、重新装机）；
> **私钥泄露 = 他人可伪造更新包**。请离线备份，且永远不要提交到仓库（`.gitignore` 已加 `*.key`）。

**发布一个可自动更新的版本：**

```powershell
cd 源码/frontend
$env:TAURI_SIGNING_PRIVATE_KEY = Get-Content "C:\Users\Administrator\.tauri\subai-updater.key" -Raw
npm run tauri:build -- --bundles nsis --config src-tauri/tauri.release.conf.json
```

会额外产出 `.nsis.zip` 与其 `.sig` 签名文件。把它们与安装包一起上传到 Release，
并按下面格式写一个 `latest.json` 一起上传（`signature` 填 `.sig` 文件的内容）：

```json
{
  "version": "4.1.0",
  "notes": "四期交付与深化",
  "pub_date": "2026-10-02T00:00:00Z",
  "platforms": {
    "windows-x86_64": {
      "signature": "<.sig 文件内容>",
      "url": "https://github.com/1553752035-beep/SubAI-Translator/releases/download/v4.1.0/SubAI Translator_4.1.0_x64-setup.nsis.zip"
    }
  }
}
```

> 未设置 `TAURI_SIGNING_PRIVATE_KEY` 时**不要**用 `tauri.release.conf.json`（缺密钥会直接构建失败）。

### 10.3 安装与卸载的实测行为

本机实测（静默安装到临时目录 → 启动 → 卸载）：

| 项 | 结果 |
|---|---|
| 安装内容 | `subai-translator.exe`（界面）+ `subai-backend.exe`（后端 sidecar，Tauri 会自动去掉平台后缀）+ `bin\ffmpeg.exe` |
| 精简版 | **不含 `models\`**（ASR 模型按既有 lite 策略单独提供）|
| 启动 | 应用启动后自动拉起后端 sidecar，`/api/health` 立即返回 200 ✓ |
| 卸载 | 程序文件删除，但**保留 `data\` 目录**（tasks/terminology/translation_cache/openapi 等数据库）—— 卸载不会丢用户数据 |
| 注册表 | 卸载后无残留项 ✓ |

> 也就是说：重装后原有的任务记录、术语库与缓存仍在。若要彻底清空，需手动删除安装目录下的 `data\`。

### 10.4 NSIS 工具链离线兜底（实测踩坑记录）

Tauri 的 NSIS 打包会校验缓存目录 `%LOCALAPPDATA%\tauri\NSIS` 中的 **13 个必需文件**，
任一缺失就**删掉整个目录并重新从 GitHub 下载**（本机网络下必然超时）。手工补齐时必须严格照它的布局：

- 解压 `nsis-3.11.zip` 后把内层 `nsis-3.11\` 的内容**铺到 `NSIS\` 根**（等价于它的 `fs::rename`）；
- `nsis_tauri_utils.dll` 必须放在 `NSIS\Plugins\x86-unicode\additional\`（**不是根目录**）；
- zip 的 SHA1 需为 `EF7FF767E5CBD9EDD22ADD3A32C9B8F4500BB10D`，DLL 的 SHA1 需为 `75197FEE3C6A814FE035788D1C34EAD39349B860`，否则会触发重新下载。

```powershell
$dir = Join-Path $env:LOCALAPPDATA "tauri\NSIS"; New-Item -ItemType Directory -Force $dir | Out-Null
$zip = Join-Path $env:TEMP "nsis-3.11.zip"
curl.exe -sL -o $zip "https://gh-proxy.com/https://github.com/tauri-apps/binary-releases/releases/download/nsis-3.11/nsis-3.11.zip"
$tmp = Join-Path $env:TEMP "nsis-extract"; Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::ExtractToDirectory($zip, $tmp)
Get-ChildItem (Join-Path $tmp "nsis-3.11") | ForEach-Object { Move-Item $_.FullName $dir -Force }
$dllDir = Join-Path $dir "Plugins\x86-unicode\additional"; New-Item -ItemType Directory -Force $dllDir | Out-Null
curl.exe -sL -o (Join-Path $dllDir "nsis_tauri_utils.dll") "https://gh-proxy.com/https://github.com/tauri-apps/nsis-tauri-utils/releases/download/nsis_tauri_utils-v0.5.3/nsis_tauri_utils.dll"
```

> 日常（不带更新产物）就用 10.1 的命令。CI 里可把私钥放进 GitHub Secret 再按上面的方式导出。
