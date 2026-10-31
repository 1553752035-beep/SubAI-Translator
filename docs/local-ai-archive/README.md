# D:/AI 本地模型环境完整归档

> 本目录是 `D:\AI` 的**配置文件归档**。模型本身（6.23 GB）不在仓库里，
> 但每一个文件的作用、来源、恢复方式都在这里。
>
> 归档日期：2026-10-25
> 归档时 `D:\AI` 总计 6.23 GB / 25 个文件，其中 17 个配置文件已完整复制进本目录。

---

## 一、这套环境是干什么的

不是玩具。它是**在本机 8 GB 显存上跑 35B 模型做本地代码开发**的完整调优成果，
包含大量实测数据和踩坑记录，价值主要在 `KoboldCpp/DEPLOY-Qwen3.6.md`（26 KB）。

三个实例共用一块 RTX 4070 Laptop（8 GB），**不要同时运行**：

| 端口 | 用途 | 模型 | 显存 | 加载 | 脚本 |
|---|---|---|---|---|---|
| 5001 | SubAI 字幕翻译 | Qwen3.6-35B-A3B | ~7 GB | 1–3 分钟 | `KoboldCpp/start-qwen36-a3b.bat` |
| 5002 | DSH 适配（含视觉） | Qwen3.6-35B-A3B | ~7 GB | 1–3 分钟 | `KoboldCpp/start-dsh-profile.bat` |
| 5003 | 视频通话视觉 | Qwen3-VL-4B | 4.6 GB | 10–30 秒 | `KoboldCpp-vl/start-5003-video.bat` |

---

## 二、核心成果摘要（细节见 DEPLOY-Qwen3.6.md）

### 性能

| 指标 | 数值 | 怎么来的 |
|---|---|---|
| 解码速度 | **31.6 tok/s**（短上下文）/ **26.1 tok/s**（52K 上下文） | 98304 上下文下重测 |
| 预填充 | 389–416 tok/s | |
| 工具调用 | **5/5 成功**，零重复死循环 | temperature 钉死 0.6 |
| 显存占用 | 7329 MiB / 8188 MiB | 余 482–528 MiB |
| 内存占用 | 16.1 GB | 加 `--noshift` 后 |

### 四个关键参数（每一个都是踩坑换来的）

```
--moecpu 33          性能命门。33 层专家放内存、7 层放显存
                     全放内存(--moecpu 99) 只有 7.33 tok/s，这个是 33 tok/s
--jinja_tools        修复工具调用解析（之前模板渲染与解析器格式不对齐）
--jinjatemplate      加载改造模板，全局禁用思考
--noshift            关掉 SmartCache 的 7 个无效 KV 槽位，纯赚 4.6 GB 内存
```

### 三个必须知道的坑

**1. 「说话说一半」**：KoboldCpp 默认不读模型自带模板，而是猜一个通用 ChatML。
Qwen3.6 要求 assistant 回复前必须写 `<think>` 开头，模板缺失就草草输出然后立刻吐 EOS。
`--jinja` + 改造模板解决。

**2. 偶发「未返回任何内容」**：模型带 RNN/混合结构标记，KoboldCpp 自动启用 SmartCache
预备 7 个 KV 槽位，每份占 66–265 MB；但下一行就宣告 `context shift will be disabled`——
**这 7 个槽位根本用不上，却实实在在占着内存**。加 `--noshift` 后可用内存从 0.69 GB 涨到 5.29 GB。

**3. 上下文是「输入+输出共用一个池子」**，不是各给一份：

```
提示词上限 = contextsize − max_tokens
```

三次实测全部吻合。所以 `maxInputTokens + maxOutputTokens` 一旦超过 `contextsize`，
输入会被**静默截断**。截断本身安全，但若切坏了一轮 `tool_call`/`tool` 的配对，模型可能直接空响应。

### 一个反直觉的发现：只有 10 层需要 KV cache

读 GGUF 元数据得到：

```
qwen35moe.block_count             = 40
qwen35moe.full_attention_interval = 4    ← 每 4 层才 1 层全注意力，其余是线性注意力(SSM)
qwen35moe.attention.head_count_kv = 2    ← 只有 2 个 KV head
```

**40 ÷ 4 = 10 层**需要 KV。若按 40 层估算会误判成「显存完全不够」而错过整个扩容空间。

每 token KV 开销 = 10 层 × 2 head × (256+256) × 1.0625 B（q8_0）= **10.6 KiB**。
实测 KV buffer 差 340 MiB / 32768 token = 10.6 KiB/token，与公式完全一致。

### 一个确认无解的问题

```
ggml_cuda_host_malloc: failed to allocate 15827.31 MiB of pinned memory: out of memory
```

CPU 侧 15.5 GB MoE 权重本该锁进页锁定内存加速传输，但分配失败后回落到可分页内存。
这是 tok/s 上不去的主要原因。**已确认与可用内存无关**（空闲 21.48 GB 时同样失败），
受 Windows 页锁定内存上限所限，非配置可调。唯一出路是把专家层移回显存，
但显存只剩 500 MiB，**当前硬件下无解**。

---

## 三、模型清单（6.23 GB，需重新下载）

### KoboldCpp（端口 5001/5002 用）

| 文件 | 大小 | 用途 | 来源 |
|---|---|---|---|
| `Qwen3.6-35B-A3B-UD-Q4_K_M.gguf` | **20.61 GB** | 代码开发主力 | [unsloth/Qwen3.6-35B-A3B-GGUF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF) |
| `Hy-MT2-1.8B-Q4_K_M.gguf` | 1.06 GB | **SubAI 翻译默认** | 腾讯混元 Hy-MT2 |
| `Hy-MT2-1.8B-StreamRevise-Q4_K_M.gguf` | 1.00 GB | 流式字幕场景 | 同上 |
| `mmproj-F16.gguf` | 0.84 GB | 视觉编码器（配 35B） | 同 Qwen3.6 仓库 |
| `koboldcpp.exe` | 0.59 GB | **推理程序 1.115.2** | [GitHub LostRuins/koboldcpp](https://github.com/LostRuins/koboldcpp/releases) |

### KoboldCpp-vl（端口 5003 用）

| 文件 | 大小 | 用途 |
|---|---|---|
| `Qwen3VL-4B-Instruct-Q4_K_M.gguf` | 2.33 GB | 视频通话视觉 |
| `mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf` | 0.42 GB | 视觉编码器（GPU） |

**注意**：`KoboldCpp-vl` 目录里**没有** `koboldcpp.exe`，它复用 `KoboldCpp\koboldcpp.exe`。
所以恢复时只需在 `D:\AI\KoboldCpp\` 放一个 exe，两个目录都能用。

### 归档时记录的文件哈希（首尾各 8 MB 的 SHA256 前 16 位）

用于下载后校验，避免拿到同名不同版本的文件：

```
Hy-MT2-1.8B-Q4_K_M.gguf              08b40c06402fb0e6
Hy-MT2-1.8B-StreamRevise-Q4_K_M.gguf e86c3f1eb5ca007a
mmproj-F16.gguf                      1d2c0c7b41aff248
Qwen3VL-4B-Instruct-Q4_K_M.gguf      749060ecdd9ca90f
mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf bb6e89605cf1ffd7
```

---

## 四、下载方式

### 国内镜像的两个坑（实测）

1. 必须带 `User-Agent: Mozilla/5.0`，否则 403
2. 必须在 URL 后加 `?download=true`，否则拿到 HTML 页面

### 35B 模型（20.61 GB）

**推荐 ModelScope**，实测 10.5 MB/s，比 HF 镜像快约 10 倍：

```bash
# ModelScope（推荐）
curl -L -C - --retry 5 \
  "https://modelscope.cn/models/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/master/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf" \
  -o Qwen3.6-35B-A3B-UD-Q4_K_M.gguf

# HF 镜像（备用）
curl -L -H "User-Agent: Mozilla/5.0" \
  "https://hf-mirror.com/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf?download=true" \
  -o Qwen3.6-35B-A3B-UD-Q4_K_M.gguf
```

### 视觉模型（3 GB，一条命令）

直接用归档里的 `KoboldCpp-vl/download-models.bat`，它已经写好断点续传和重试。

### Hy-MT2 翻译模型

腾讯混元的翻译专用模型，HuggingFace 搜 `Hunyuan-MT` 系列。
注意 SubAI 用的是 **1.8B** 小尺寸版，不是 7B。

---

## 五、恢复步骤

```bash
# 1. 建目录
mkdir D:\AI\KoboldCpp\models
mkdir D:\AI\KoboldCpp-vl\models

# 2. 从本仓库复制配置（17 个文件）
xcopy /E /I docs\local-ai-archive\KoboldCpp      D:\AI\KoboldCpp
xcopy /E /I docs\local-ai-archive\KoboldCpp-vl   D:\AI\KoboldCpp-vl

# 3. 下载 koboldcpp.exe 1.115.2 放到 D:\AI\KoboldCpp\
#    https://github.com/LostRuins/koboldcpp/releases

# 4. 下载模型（见第四节）

# 5. 启动
D:\AI\KoboldCpp-vl\0-menu.bat      ← 统一菜单，能看三个实例区别
```

### 恢复后的验证

```bash
# 起 5001 后跑这个（归档里已有）
python D:\AI\KoboldCpp\verify_qwen.py
```

它会检查四项：模型 ID、tok/s、工具调用 5 次、Anthropic 端点。
预期看到 `33 tok/s` 左右和 `tool calls = 5/5`。

---

## 六、归档文件清单

```
KoboldCpp/
  DEPLOY-Qwen3.6.md          26.8 KB  ← 最重要，完整调优报告
  chat_template.jinja         7.8 KB  官方原始模板
  qwen36-nothink.jinja        7.6 KB  改造后：固定空 think 块
  qwen36-dsh.jinja            8.1 KB  改造后：+ DSH 规则（diff 仅 1 行）
  start-qwen36-a3b.bat        2.0 KB  5001 SubAI
  start-dsh-profile.bat       3.8 KB  5002 DSH（快速版）
  start-dsh-safe.bat          2.7 KB  5002 DSH（稳定版，关 KV 复用）
  启动KoboldCpp.bat            114 B  桌面快捷方式入口
  make-nothink-template.py    1.2 KB  从官方模板生成 nothink 版
  verify_qwen.py              2.7 KB  部署验证脚本
  resume_dl.py                3.7 KB  分块并行下载器（32 线程）
  GPU.txt                      48 B  显存摘要

KoboldCpp-vl/
  README.md                   4.3 KB  ← 三个实例对照表 + 5003 实测数据
  0-menu.bat                  1.8 KB  统一启动菜单
  start-5003-video.bat        1.9 KB  5003 视频通话
  task-5003.bat                451 B  后台任务版（输出到 out.log）
  download-models.bat         1.4 KB  一键下载视觉模型
```

---

## 七、如果要接着做本地开发

**Claude Code 直连**（KoboldCpp 1.115.2 原生支持 Anthropic 协议，不需要 router）：

```bat
set ANTHROPIC_BASE_URL=http://127.0.0.1:5001
set ANTHROPIC_API_KEY=koboldcpp
claude
```

**CodeBuddy**：配置在 `C:\Users\Administrator\.codebuddy\models.json`（不在本归档内，
因为它在用户目录）。关键字段：

```
maxInputTokens  = 65536
maxOutputTokens = 32768
两者之和必须 ≤ contextsize(98304)
temperature     = 0.6   ← 低于 0.6 会输出死循环
```

模型 ID 必须带 `UD-` 前缀：`koboldcpp/Qwen3.6-35B-A3B-UD-Q4_K_M`。

---

## 八、这份归档的价值在哪

不是「怎么启动」——那看 bat 文件就够了。

真正值钱的是 `DEPLOY-Qwen3.6.md` 里那些**用时间换来的数字**：

- `--moecpu 99` 只有 7.33 tok/s，`--moecpu 33` 是 33 tok/s —— 差 4.5 倍，只改一个参数
- `--noshift` 纯赚 4.6 GB 内存，且**不损失任何功能**（上下文移位本来就被 MRope 禁用）
- 131072 上下文只余 100 MiB 显存，**实测确认 98304 才是安全上限**
- 输出上限设到 32768 以上没意义：33 tok/s × 49152 ≈ 25 分钟，超过 reqtimeout 必被掐断
- `--threads 16` 在 8 核上**启动成功但首个请求永久无响应**，日志停在启动阶段
- 某「针对 Claude Code 优化」的模型经字节级比对是**虚假宣传**，chat template 的 sha256 与通用版完全相同

这些结论如果丢了，重来一遍要几十个小时。