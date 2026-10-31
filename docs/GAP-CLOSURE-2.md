# 对标 SmartSub 的能力补齐（第二轮）

日期：2026-10-25
基准：`C:/tmp/smartsub/SmartSub-main/`（SmartSub 真实源码，1908 文件 / 92,400 行核心逻辑）

第一轮补齐了 8 项能力面（格式、样式、分离、波形、崩溃隔离、ASR/翻译引擎）。
这一轮补的是**核实后发现的真实差距**——不是照着 README 抄功能名，
而是逐项对照对方代码后确认「我们确实没有」的东西。

---

## 一、provider 真实连通验证

### 问题

`llm_providers.py` 里 25 个 provider 只是「预填了 base_url + 模型名」。
预填不等于可用：地址可能已变更、模型名可能已下线、服务可能要求非 Bearer 认证。

更糟的是 `llm.probe()` 原来的判据是：

```python
reachable = r.status_code < 500
```

这意味着 **401 / 403 / 404 全算「端点可达」**。用户填了一个完全无效的 key，
页面显示正常，直到真正跑翻译才报错——那时已经浪费了时间。

### 修法

把「网络层通不通」和「这个 key 能不能用」拆成两个字段：

| 字段 | 含义 |
|---|---|
| `reachable` | 服务器有没有应答（5xx 仍算 False，因为它没法干活） |
| `authorized` | 这个 key 在这台服务上能不能用（401/402/403 判 False） |
| `verdict` | ok / auth_failed / not_found / rate_limited / discontinued / ... |

新增 `src/provider_health.py`：批量探测 + 结果落盘（`data/provider_health.json`，7 天 TTL）。
并发默认 4——探测是锦上添花的功能，为它触发对方限流（尤其免费额度）反而伤用户。

### 实测结果（2026-10-25，无 key 探活，26 个 provider）

| verdict | 数量 | provider |
|---|---|---|
| `no_key`（端点存在，200） | 2 | openrouter, deepinfra |
| `auth_failed`（端点存在，401） | 10 | deepseek, qwen, doubao, kimi, zhipu, siliconflow, hunyuan, spark, minimax, stepfun |
| `forbidden`（403） | 3 | qianfan, groq, together |
| **`discontinued`（410）** | **1** | **yi** |
| `network_error`（本机不可达） | 7 | openai, gemini, grok, mistral, ollama, lmstudio, koboldcpp |
| `not_probeable`（无 /models 端点） | 3 | deepl, google_translate, tencent_free |

**最重要的发现：`yi`（零一万物）已经停服。**

```
HTTP 410
{"error":{"code":"model_service_closed",
          "message":"Model service has been discontinued"}}
```

而我们仍在把它列在 provider 列表里推荐给用户。
已加 `status="discontinued"` 标记与 `status_note`，保留条目（用户可能已有历史配置，
突然消失会更困惑）但明确标注。

另外 7 个 `network_error` 是**本机网络不可达**（openai/gemini/grok/mistral 全部连接超时），
不是代码问题——国内直连这些域名本来就不通。

### 新接口

- `POST /api/llm/provider-probe` — 批量核验（可带 api_key 判断认证）
- `GET /api/llm/provider-health` — 读取已保存结果（纯读盘，不重新探测）

---

## 二、免费免 Key 翻译渠道

### 问题

此前所有翻译渠道都要用户自己去申请 API Key：注册 → 实名 → 充值 → 建 Key。
对一个只想给游戏视频加个字幕的人来说，这道门槛直接把工具挡在门外。

### 实测过程（重要：先说没成的）

| 渠道 | 实测结果 | 决定 |
|---|---|---|
| `translate.googleapis.com` | 连接超时 15s | **放弃** |
| `translate.google.com` | 连接超时 12s | **放弃** |
| `clients5.google.com` | 连接超时 12s | **放弃** |
| 有道 `dict.youdao.com/webtranslate` | key 接口返回 `HTTP 500 {"code":1,"msg":"request error"}`，且需 AES-128-CBC 解密 + md5 签名（SmartSub 用 610 行实现） | **放弃**（不做半成品） |
| 百度 `fanyi.baidu.com/sug` | 只返回词典释义，不是整句翻译 | **放弃** |
| **腾讯交互翻译** `transmart.qq.com/api/imt` | **544ms，单/多条均正确** | **采用** |

Google 三个域名本机全部不可达——这不是代码问题，是网络环境。
代码留着也是死代码，不如不写。有道需要逆向网页端私有协议（会随版本变化），
维护成本极高且本机暂时拿不到 key，不做半成品。

### 腾讯交互翻译实测数据

| 项 | 结果 |
|---|---|
| 单条中→英 | `你好世界` → `Hello World`，544ms |
| 多条对齐 | 3 条进 → 3 条出，顺序正确 |
| 中→日 | `你好` → `こんにちは` |
| 英→中 | `Hello world` → `您好，世界` |
| 空串 | 原样返回，不发请求 |
| 长文本 | 3003 字正常 |
| 条数上限 | 60 条正常（取保守值 40 条/批） |

### 设计要点

1. **条数必须对齐**：字幕行与时间轴一一对应，返回条数不等就整批失败。
   补空串凑数会让某句话凭空消失而时间轴照常推进，成片里极难发现。
2. **空行本地处理**：字幕里常有空行/纯空格，送进去会挤占配额也可能让服务端
   返回不同条数，本地直接原样返回。
3. **失败不假装成功**：任何异常都抛出，由上层回落，不返回空串充数。

新增 `src/translate_free.py`（166 行）+ 30 项测试，已接进 pipeline，
在设置页选中后**连 Key 输入框都不显示**——避免用户以为「还得填点什么」。

---

## 三、字体解析（逐字回退）

### 这是我上一轮判断错了的地方

上一轮我写「字体解析不值得做，libass 本身会按候选链找字体」。
实际上 SmartSub 的 `fontResolver.ts` 有 **916 行**，做的事是：

```
读字体 face → face.hasGlyphForCodePoint(code) 逐字判断
→ 切成 run → 缺字逐字回退到覆盖该字的字体
```

我当时的理由（libass 会回退）不是完全错，但**没做就说不需要**是错的。
916 行说明它踩过很多坑（CJK、TTC 集合、隐形字符）。

### 实现

新增 `src/glyphs.py`（238 行），**纯标准库解析 sfnt 表目录 + cmap**：

- 只需要「某码位有没有字形」一个信息，不需要字形轮廓/hinting/变体
- 引入 fontTools 等于给打包加隐式依赖（PyInstaller 对它的数据文件处理常有坑）
- 支持 cmap format 4 与 12（不同字体的选择不同）

实测覆盖（真实字体）：

| 字体 | cmap 格式 | 常用汉字覆盖 |
|---|---|---|
| msyh.ttc（微软雅黑） | 12 | 20902 / 20902 |
| simhei.ttf（黑体） | 4 | 20902 / 20902 |
| simsun.ttc（宋体） | 4 | 20902 / 20902 |
| arial.ttf | 4 | 0 |

### 踩过的坑（写下来免得重犯）

**TTC 子字体偏移**：TTC 里每个子字体的表目录中，「表偏移」字段是
**相对文件开头**的绝对偏移，**不是**相对子字体起始位置。
按子字体加 base 会取到错误的 cmap，症状是「微软雅黑缺『文』字」这种明显不合理的判定。

**丢字 bug**：第一版把缺字收进 `buf` 后忘了写出去，
生成 `Hello {\fnSimHei}{\fn} World`——**中间的「敌人」直接消失了**。
测试里加了「去标签后必须与原文逐字一致」的硬约束才抓住。

**转义序列被拆断**：`\N`（硬换行）的后一个字符如果被判定为缺字，
会生成 `\` + `{fn}` + `N`，标签结构坏掉，表现为「换行消失」。
现在反斜杠+后一字符整体跳过。

### 与 ASS 的衔接

`build_ass_document(..., glyph_fallback={...})` 把缺字用 `{\fn回退字体}` 包起来。
连续缺字合成一段而不是逐字包裹——逐字会让 ASS 体积膨胀数倍并拖慢 libass 解析。

**像素级验证**（真实烧录，2026-10-25）：

| 写法 | 墨迹像素 | 横向范围 |
|---|---|---|
| 无标签（基准） | 605 | 10~622 |
| `{\fnSimHei}敌人{\fn}` | 605 | 10~622 |
| `{\fnMicrosoft YaHei}敌人{\fn}` | 605 | 10~622 |

三者完全一致，说明字体切换没有破坏排版，且**带空格的字体名也能被 libass 正确识别**。

---

## 四、读取 ASS 内嵌字体

下载的字幕包（尤其日文/多语种番剧）经常把字体直接嵌在 `.ass` 里，
放在文件末尾的 `[Fonts]` 段。只用自己的字体，创作者精心选的字体就全丢了。

### 编码格式（最容易写错的地方）

ASS 的内嵌字体**不是** MIME base64，而是 **UUencode 变体**：

- 每 4 个字符压 3 个字节
- 每个字符占 **6 bit**，值 = 字节值 + **33**（不是 base64 的 65）
- 合法字符范围 `!`(0x21) 到 `` ` ``(0x60)

拿标准 base64 解码器处理**不会报错**，只会得到一堆垃圾字节，
然后字体加载静默失败——极难排查。

验证：`"AAAA"` 在此格式下解出 `0x82 0x08 0x20`（base64 会解成三个 0x00）。
用真实 simhei.ttf 前 3000 字节做往返，逐字节一致。

新增 `src/ass_fonts.py`（198 行）+ 21 项测试。

---

## 五、逐任务选 ASR 引擎

### 为什么需要

实测同一段 146.3 秒中文游戏解说：

| 引擎 | 耗时 | 段数 |
|---|---|---|
| paraformer | 3.9s | 29 |
| sensevoice | 4.1s | 30 |
| qwen3 | **23.0s** | 28 |

而粤语、中英混说、英语说唱则是 Qwen3 明显更准（上一轮实测数据）。
如果只能全局改配置，用户换一种素材就要回设置页改一次，
**批量处理混合素材时根本做不到**。

### 实现

`asr_engine` 字段从请求一路传到子进程：

```
TranscodeRequest.asr_engine
  → _submit_one_transcode（normalize_asr_engine 校验）
  → 队列参数
  → process_transcode_task
  → worker payload
  → run_pipeline(asr_engine=...)
  → asr_segments(engine=...)
```

**校验放在提交前**：引擎名写错立刻返回 400 并列出可选值，
而不是等任务跑起来在子进程深处失败（用户看到「任务失败」完全看不出是自己填错了）。

24 项测试锁住这条链路的每一环——尤其 worker 那一步容易漏，
因为 worker 的参数是一个个显式列出来的，新增字段不写进去就是**静默失效**。

---

## 六、非 ASCII 路径安全

### 根因

sherpa-onnx 的 C++ 层用**窄字符 API**（fopen / std::ifstream）打开模型文件，
而 Python 传进去的是 UTF-8 字节。Windows 系统代码页不是 UTF-8 时（中文版 936/GBK），
这些字节被当成本地代码页解码，路径变成一个不存在的名字。

**症状是静默降级，不是报错**，所以特别难查：

- silero VAD：构造函数静默失败，之后每次调用都打印 `vad is nullptr`，永远切出 0 个语音段
- 降噪 / 识别 / TTS / 说话人分离：构造时抛 `Please check your config!`
- readWave 抛 `Failed to read ...`，writeWave 返回 false

本项目 `models/sherpa` 位于 `D:\SubAI-Translator\源码\` 下，**路径含中文**。
开发时用相对路径能跑通，**打包后必然踩这个坑**。

### 处理策略（按文件性质分三类）

| 类型 | 做法 | 理由 |
|---|---|---|
| 随包小模型（VAD 2MB、降噪 0.5MB） | 复制到 ASCII 目录，内容寻址（sha1 前 16 位） | 复制成本可忽略 |
| 用户音频 | 不复制，Python 侧读写 wav 后再交给原生库 | 大文件 |
| GB 级用户模型 | 不搬，失败时给可操作提示 | 复制 900MB 太贵 |

### 实现要点

- 只在 **Windows + 非 ASCII** 时介入；ASCII 路径用户行为完全不变
- **暂存候选目录自身含非 ASCII 时被剔除**——暂存到中文目录等于没暂存
- **副本完整性校验用 sha1 而不只是大小**：模型被截断但大小相同虽然罕见，
  一旦发生就是「加载成功但推理结果全错」，比直接失败更难查
- **任何失败都退回原路径**：暂存是尽力而为，不该让识别失败

### 实测

```
原路径: D:\SubAI-Translator\源码\models\sherpa\silero_vad.onnx   (含中文)
暂存后: C:\Users\...\Temp\native-models\f7b6152f842c088f\silero_vad.onnx

推理验证（146.3 秒音频，接入前后对比）:
  sensevoice  30 段 / 331 汉字  ← 完全一致
  paraformer  29 段 / 379 汉字  ← 完全一致
```

新增 `src/native_safe.py`（239 行）+ 36 项测试。

---

## 七、前端界面（后端能力真正被用户用到）

后端做完不等于用户能用上。这一轮补了两个界面入口。

### 7.1 逐任务选识别引擎（向导页）

放在「成品形式」下面，四个选项：跟随设置 / SenseVoice / Paraformer / Qwen3。

几个刻意的决定：

- **默认「跟随设置」并显示当前引擎名**（如「跟随设置（sensevoice）」）。
  只写「跟随设置」用户不知道跟的是什么，等于让他盲选。
- **未安装的引擎置灰不可点**，`title` 说明「模型未安装」。
  列出来但不给点，比直接隐藏好 —— 用户能知道「有这个选项，装了就能用」。
- **引擎接口失败不阻断**：拿不到可用性就当作全部可用。
  这是向导页，用户此刻只想快点出片，不该因为一个辅助信息拿不到就卡住。
- **只有选了具体引擎才传 `asr_engine`**，默认不传，保持「跟随全局」语义。

4 项测试覆盖：默认态与引擎名显示、置灰不可点、选中后高亮且「跟随」取消、
接口失败仍可点。

### 7.2 服务商核验（设置页）

「测试连接」旁边加了「核验全部服务商」，一次性看到 26 个的真实状态。

- **按信息量排序**：可用 / 已停服 / Key 无效 排前面，
  「本机不可达」沉底。国内用户看到 7 个 `network_error` 是常态，
  堆在前面会把「yi 已停服」这种关键结论淹掉。
- **颜色区分**：可用绿、明确失败红、其余灰。
- **失败不静默**：核验接口挂了要显式报错，不能什么都不显示让用户以为「没有可用服务商」。

3 项测试覆盖：三种结论都显示、排序正确（用 `compareDocumentPosition` 判文档顺序，
不靠抓文本猜）、失败有提示。

### 顺带修的一个既有缺陷

`SettingsPage.test.tsx` 的 `vi.mock('../api')` 一直缺 5 个导出
（`cancelAsrModel` / `downloadAsrModel` / `getAsrModelStatus` /
`getSubtitleQuality` / `openExternal`）。vitest 的全量 mock **一次只报一个缺失**，
所以这 5 个从来没被一次性发现。现在补齐并给了默认返回值。

---

## 八、本轮测试增量

| 文件 | 项数 |
|---|---|
| `test_glyphs.py` | 29 |
| `test_ass_fonts.py` | 21 |
| `test_font_pipeline.py` | 14 |
| `test_glyph_fallback.py` | 21 |
| `test_glyph_render.py` | 2（真实烧录，耗时约 5 分钟） |
| `test_translate_free.py` | 30 |
| `test_asr_engine_per_task.py` | 24 |
| `test_native_safe.py` | 36 |
| `WizardPage.test.tsx` | 4 |
| `SettingsPage.test.tsx` | 11（含 3 项核验） |
| **合计** | **192** |

---

## 九、仍未补的差距（如实记录）

| 项 | SmartSub | 我们 | 说明 |
|---|---|---|---|
| 云端 ASR 引擎 | 9 个（aliyun/deepgram/elevenlabs/gladia/openai-compat/tencent/volcengine/xfyun/xiaomiMimo） | 0 | 需各家账号，长期项 |
| 模型自动下载管理 | `modelCatalog` + `modelDownloader` | 手动放模型 | 体验差距 |
| 供应商健康记录（历史趋势） | `providerHealth.ts` | 只存最近一次 | 我们够用 |
| 缺句检测精度 | 按语音间隔 800ms 判 | 按字数/时长比 | 对方更准 |
| Parakeet / localCli 引擎 | 有 | 无 | 优先级低 |

核心代码规模仍是 16,988 行 vs 对方 92,400 行（5.4 倍）。
这一轮补的是**用户能直接感知**的能力，广度差距依然存在。