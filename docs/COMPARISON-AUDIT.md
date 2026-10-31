# SubAI-Translator vs SmartSub 实测对比核查表

生成日期：2026-10-25
对照方式：**下载 SmartSub 真实源码逐项核实**，不是读 README 推测。

- SmartSub 来源：`codeload.github.com/buxuku/SmartSub/zip/refs/heads/main`（26.2 MB）
- 解压位置：`C:/tmp/smartsub/SmartSub-main/`，1908 个文件
- 我方：`D:/SubAI-Translator/源码/`

---

## 一、规模底账（客观数字）

| 项 | SmartSub | SubAI | 比值 |
|---|---|---|---|
| 核心逻辑行数 | **92,400** | 16,988 | 5.4× |
| 核心逻辑文件 | 392 | 62 | 6.3× |
| 测试文件 | 101 | 65 | 0.64× |
| 技术栈 | TypeScript / Nextron | Python / FastAPI | — |

**这一项必须说清楚**：对方核心代码是我们的 5.4 倍。
任何「能力面不弱于对方」的说法，都要在这个数字面前接受检验。

---

## 二、逐项核实结果

### ① 字幕格式导入导出

| 项 | SmartSub | SubAI | 结论 |
|---|---|---|---|
| 导出格式 | srt/vtt/ass/lrc/txt | srt/vtt/ass/lrc/txt | **持平** |
| 导入格式 | srt/vtt/ass/lrc（含 `.ssa`→ass） | srt/vtt/ass/lrc（含 `.ssa`→ass） | **持平** |
| 格式识别 | 扩展名 + 内容双判 | 扩展名 + 内容双判 | **持平** |
| 实现规模 | 602 行 | 约 400 行 | 我方略小 |

**判定：真的持平**，不是嘴上持平。两份常量表逐项对得上。

### ② ASS 样式 + 字体内嵌

| 项 | SmartSub | SubAI | 结论 |
|---|---|---|---|
| 样式构建 | `assStyleBuilder.ts` | `subtitle_style.py` | **持平** |
| 字体内嵌（写 MKV） | `assEmbeddedFonts.ts`（写） | `fonts.py` `build_attach_args` | **持平** |
| **读取 ASS 内已有字体** | ✅ `readAssEmbeddedFonts` | ❌ 无 | **我方缺** |
| **字体解析（逐字回退）** | ✅ `fontTextRuns` 用 `hasGlyphForCodePoint` | ❌ 无 | **我方缺** |
| 字体推荐 | `recommendFontsForText` + `containsCJK` | ❌ 无 | **我方缺** |
| 文件规模 | `fontResolver.ts` **916 行** | `fonts.py` 约 180 行 | 5× |

**上一轮我说「字体解析不值得做」，这个判断是错的。**
SmartSub 实际实现了：读字体 face → `hasGlyphForCodePoint` 逐字判断 → 切成 run →
缺字逐字回退到覆盖该字的字体。916 行说明它踩过很多坑（CJK、TTC 集合、隐形字符）。
我当时以「libass 本身会回退」为由跳过，是**没做就说不需要**。

### ③ 说话人分离

| 项 | SmartSub | SubAI | 结论 |
|---|---|---|---|
| 引擎 | sherpa-onnx（同源） | sherpa-onnx（同源） | **持平** |
| 文件规模 | 1021 行 / 5 文件 | `diarize.py` 约 240 行 | 4× |
| 模型管理 | `modelCatalog` + `modelDownloader`（下载/校验/删除） | 无（需手动放模型） | **我方缺** |
| 对齐 | `alignSpeakersToCues` | `assign_speakers` | **持平**（思路一致） |

### ④ 校对台波形

| 项 | SmartSub | SubAI | 结论 |
|---|---|---|---|
| 后端 | `proofreadWaveform.ts` 173 行 | `waveform.py` 约 120 行 | **基本持平** |
| 前端 | `WaveformTimeline.tsx` | `WaveformView.tsx` | **基本持平** |
| 增量累积 | `WaveformAccumulator` 类 | ❌ 无 | **我方缺** |
| 取消 | `cancelProofreadWaveforms` | ❌ 无 | **我方缺** |

### ⑤ 崩溃隔离

| 项 | SmartSub | SubAI | 结论 |
|---|---|---|---|
| 子进程隔离 | `UtilityHost` 类 + `spawnUtilityHost` | `run_isolated` | **持平** |
| 退出码描述 | `describeHostExit` | `describe_exit` | **持平** |
| 崩溃识别 | `nativeGuard` + `previousRun`（上次运行残留检测） | `is_crash`（退出码+stderr） | **我方缺「上次崩了」恢复** |
| 文件规模 | 1257 行 / 7 文件 | `worker.py` 约 300 行 | 4× |

### ⑥ 缺句告警

| 项 | SmartSub | SubAI | 结论 |
|---|---|---|---|
| 检测 | `detectMissedSpeech` + 能量扫描 360 行 | `compute_coverage` 覆盖率 | **我方弱** |
| 判据 | `MISSED_SPEECH_MIN_MS = 800` 按语音间隔判 | 按字数/时长比判 | 对方更准 |

### ⑦ ASR 引擎

| 项 | SmartSub | SubAI | 结论 |
|---|---|---|---|
| 本地引擎 | **7**：builtin(whisper) / fasterWhisper / funasr / qwen / fireRed / **parakeet** / localCli | **5**：whisper / sensevoice / paraformer / qwen3 / firered | **我方少 parakeet、localCli** |
| 云端引擎 | **9**：aliyun / deepgram / elevenlabs / gladia / openai-compat / tencent / volcengine / xfyun / xiaomiMimo | **0** | **我方缺** |
| 逐任务选引擎 | ✅ `resolveEngineIdForTask` | 全局配置 | **我方缺** |
| 非 ASCII 路径处理 | `nativeSafePath.ts` | 无（已知限制） | **我方缺** |

**我方实测推理**（同一 146.3 秒音频）：

| 引擎 | 耗时 | 段数 | 首句 |
|---|---|---|---|
| sensevoice | **4.1s** | 30 | 啊。好，开始录制啊。那么。这一款。我要给你细讲下。首先他本来的枪械伤害4246， |
| paraformer | **3.9s** | 29 | 好 好开始录制啊那么 这一款 我要给你细讲一下 首先它本来的枪械伤害四十二四十六装上短管 |
| qwen3 | **23.0s** | 28 | 好。好，开始录制啊。那么。这一款。我要给你细讲一下。首先，它本来的枪械伤害四十 |
| firered | — | — | 模型缺失（代码支持，未下载） |

qwen3 实测比 sensevoice **慢 5.6 倍**（23.0s vs 4.1s），不是之前说的 6~8 倍，更正。

### ⑧ 翻译服务

| 项 | SmartSub | SubAI | 结论 |
|---|---|---|---|
| 服务数量 | **17**（volc/baidu/deeplx/ollama/openai/azure/azureOpenai/aliyun/google/bingFree/googleFree/youdaoFree/doubao/niutrans/tencent/xunfei/qwenMt） | **25**（20 OpenAI兼容 + deepl + google + 3 本地） | **我方数量多** |
| 免费免key渠道 | ✅ bingFree / googleFree / youdaoFree / deeplx **4 个** | ❌ 0 个 | **我方缺** |
| 供应商健康记录 | ✅ `providerHealth.ts` | ❌ 无 | **我方缺** |
| 回退链 | ✅ `fallback.ts` + `providerFallback.ts` | 仅 DeepL/Google 失败回落 LLM | **我方弱** |
| 真实连通验证 | 有测试 `testConnection` | **20 个只填了 base_url，未验证** | **我方虚** |

**这是最需要警惕的一项**：我们的「25 个 provider」里，
20 个只是「预填了 base_url + 模型名」，**没有一家做过真实请求验证**。
用户填了 key 才发现地址过期/模型名不对，这种「数量优势」是纸面的。

---

## 三、诚实的总结

**真的持平的项**（代码对得上）：字幕格式、ASS 样式、字体内嵌（写入）、说话人分离核心算法、
崩溃隔离基础能力、校对台波形基本功能、ASR 的 4 个本地引擎。

**我方明确落后的项**：

1. **字体解析**（逐字字形回退）—— 916 行 vs 0 行
2. **读取 ASS 内已有字体** —— 有 vs 无
3. **云端 ASR 引擎** —— 9 个 vs 0 个
4. **免费免 key 翻译渠道** —— 4 个 vs 0 个
5. **供应商健康记录与回退链** —— 有 vs 无
6. **模型自动下载管理** —— 有 vs 无
7. **逐任务选 ASR 引擎** —— 有 vs 无
8. **非 ASCII 路径安全处理** —— 有 vs 无
9. **缺句检测精度** —— 按语音间隔 vs 按字数比
10. **provider 真实可用性验证** —— 有 testConnection vs 20 个未验证

**结论**：上一轮「基本不弱于其能力面」的说法**站不住**。
准确说法是：**核心流程能力基本对齐，但广度、工程完备度、验证覆盖明显落后**。
对方 92,400 行不是靠水出来的。

---

## 四、建议的补齐优先级

按「用户能直接感知」排序，不是按实现难度：

| 优先级 | 项 | 理由 | 预估 |
|---|---|---|---|
| P0 | provider 真实连通验证 | 现在 20 个是纸面数量，用户填了才发现不能用 | 0.5 天 |
| P0 | 免费免 key 翻译渠道（bing/google/youdao） | 用户没有 API key 也能用，门槛最低 | 1 天 |
| P1 | 字体解析逐字回退 | 中文有生僻字/emoji 时会掉方框，能看见 | 1.5 天 |
| P1 | 读取 ASS 内已有字体 | 别人给的 ASS 里的字体能直接用 | 0.5 天 |
| P2 | 逐任务选 ASR 引擎 | 不同素材用不同引擎，现在只能全局改 | 1 天 |
| P2 | 非 ASCII 路径安全 | 打包后路径含中文可能加载失败 | 0.5 天 |
| P3 | 云端 ASR 引擎 | 需各家账号，长期项 | 3 天+ |
