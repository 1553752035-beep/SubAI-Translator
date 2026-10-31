# 更新日志

本项目的主要版本变更。更详细（含实现取舍与踩坑记录）的完整历史见 [`项目总方案.md`](../项目总方案.md)。

## [未发布]

### 新增

- **provider 真实连通验证**。原来 `llm.probe()` 的判据是 `status_code < 500`，
  等于 **401/403/404 全算「端点可达」** —— 用户填了完全无效的 key，页面显示正常，
  直到真正跑翻译才报错。现在拆成两个字段：`reachable`（网络层）与 `authorized`（认证层），
  并新增 `verdict`（ok / auth_failed / not_found / rate_limited / discontinued）。
  新增 `src/provider_health.py`：批量探测 + 结果落盘（`data/provider_health.json`，7 天 TTL）。
  新接口 `POST /api/llm/provider-probe`、`GET /api/llm/provider-health`。

  **实测抓到 `yi`（零一万物）已停服**：`/v1/models` 返回 HTTP 410
  `{"code":"model_service_closed","message":"Model service has been discontinued"}`，
  而我们仍在列表里推荐它。已加 `status="discontinued"` 标记。
  26 个 provider 无 key 探活结果：2 个 200（openrouter/deepinfra）、10 个 401、
  3 个 403、1 个 410、7 个本机网络不可达、3 个无 /models 端点（翻译专用）。

- **免费免 Key 翻译渠道**。新增 `src/translate_free.py`：**腾讯交互翻译**，
  用户不填任何 Key 也能出片。实测 544ms、3 条进 3 条出、中英日互译正常、
  3003 字与 60 条均正常。设置页选中后连 Key 输入框都不显示。

  实测后**未采用**的渠道（写清楚免得后人重踩）：
  - `translate.googleapis.com` / `translate.google.com` / `clients5.google.com`
    → 本机三个域名全部 12~15 秒连接超时，是网络不可达不是代码问题；
  - 有道 `dict.youdao.com/webtranslate` → 需 AES-128-CBC 解密 + md5 签名
    （SmartSub 用 610 行实现），本机 key 接口返回 500，不做半成品；
  - 百度 `fanyi.baidu.com/sug` → 只返回词典释义不是整句翻译。

- **字体解析（逐字回退）**。新增 `src/glyphs.py`：纯标准库解析 sfnt 表目录 + cmap
  （format 4 / 12），判断「某码位有没有字形」，缺字切成 run 逐字回退。
  不引入 fontTools 的理由：只需要一个字的信息，引入它等于给打包加隐式依赖。
  实测 msyh.ttc / simhei.ttf / simsun.ttc 覆盖常用汉字 20902/20902，arial.ttf 为 0。

  接进 `build_ass_document(..., glyph_fallback={...})`，用 `{\fn回退字体}` 行内覆盖。
  连续缺字合成一段而不是逐字包裹（逐字会让 ASS 体积膨胀数倍并拖慢 libass 解析）。
  **像素级验证**：带标签与不带标签的墨迹像素完全一致（605 vs 605，横向 10~622），
  说明字体切换没破坏排版，且带空格的字体名（Microsoft YaHei）也能被 libass 识别。

- **读取 ASS 内嵌字体**。新增 `src/ass_fonts.py`：从 `.ass` 的 `[Fonts]` 段解出字体。
  编码是 **UUencode 变体**（每字符 -33 占 6 bit），**不是 MIME base64** ——
  用标准 base64 解码器处理不会报错，只会得到垃圾字节然后字体静默加载失败。
  验证：`"AAAA"` 解出 `0x82 0x08 0x20`（base64 会解成三个 0x00）；
  真实 simhei.ttf 前 3000 字节往返逐字节一致。

- **逐任务选 ASR 引擎**。`asr_engine` 从请求一路传到子进程
  （TranscodeRequest → 校验 → 队列 → worker payload → run_pipeline → asr_segments）。
  动机：实测同一段 146.3 秒游戏解说，paraformer 3.9s / sensevoice 4.1s /
  **qwen3 23.0s**，而粤语与英语说唱是 Qwen3 明显更准 —— 只能全局改的话，
  批量处理混合素材做不到。引擎名写错在**提交前**就返回 400 并列出可选值。

- **非 ASCII 路径安全**。新增 `src/native_safe.py`：把随包小模型复制到纯 ASCII 目录，
  原生库打开副本。根因是 sherpa-onnx 的 C++ 层用窄字符 API（fopen / std::ifstream），
  Windows 代码页不是 UTF-8 时中文路径被错误解码成不存在的名字。
  **症状是静默降级不是报错**：silero VAD 构造失败后每次调用都打印 `vad is nullptr`，
  永远切出 0 个语音段 —— 这是最难查的一类问题。
  本项目 `models/sherpa` 位于含中文的路径下，开发时用相对路径测不出来，**打包后必然踩到**。

  实现要点：只在 Windows + 非 ASCII 时介入（ASCII 用户行为完全不变）；
  暂存候选目录自身含非 ASCII 时被剔除（暂存到中文目录等于没暂存）；
  **副本完整性用 sha1 而不只是大小**（模型被截断但大小相同会「加载成功但结果全错」）；
  任何失败都退回原路径，不让识别失败。
  实测：接入后推理结果与之前完全一致（sensevoice 30 段/331 汉字，paraformer 29 段/379 汉字）。


- **字幕格式：导入 4 种 / 导出 5 种**。新增 `src/subtitle_formats.py`：srt / vtt / ass / lrc 导入，
  srt / vtt / ass / lrc / txt 导出。此前只能导入 SRT，用户拿 `.vtt` / `.ass` 进来会解析出 0 行
  并报「未提取到任何字幕」，实际原因是格式没识别。现在按**扩展名 + 内容特征**双重判断，
  `.ass` 改名成 `.txt` 也能认出来。ASS 解析按 `Format:` 行实际列序取 Start/End/Text（不同工具列序不同，
  硬编码下标会取错列）；LRC 只有起始时间，结束时间取「下一行起点 − 0.01」——这是格式定义，不是精度缺陷。
- **ASS 字幕全套样式**。新增 `src/subtitle_style.py`：颜色 / 描边 / 阴影 / 位置 / 背景框 / 字体候选链。
  原来烧硬字幕只能传 `force_style=FontName=...,FontSize=...`。
  - 颜色用 CSS 语义输入，内部转 ASS 的 `&HAABBGGRR`（**BGR 顺序 + alpha 反转**两个坑都封装掉）
  - 脚本空间固定 384×288（与 ffmpeg 的 SRT 隐式转换一致），既有字号/边距**观感零回归**
  - `BorderStyle=3`（背景框）时框色取 `OutlineColour` 且必须与 `BackColour` 同色，否则 shadow>0 露异色边
  - 字体用**候选链**而非解析 TTF cmap 做逐字回退：libass 本身按顺序找第一个可用字体，自己解析维护成本高
  - 实测烧录：金色像素 5403 个、位于画面 89%~95% 高度、水平居中偏差 6px
- **说话人分离**。新增 `src/diarize.py`：sherpa-onnx pyannote 分割 + 3dspeaker 嵌入 + FastClustering。
  分离与识别**解耦**（只产出时间片，再用「重叠时长最大」贴到已定版字幕行），
  保证开关分离不影响字幕切分；说话人编号按首次出现顺序重排，同一素材重跑结果一致。
  实测 146 秒素材 22.8s 处理完；阈值 0.5 会过度聚类（单人误判 3 人），默认改 0.9。
- **校对台波形图**。新增 `src/waveform.py` + `GET /api/video/waveform` + `WaveformView` 组件。
  后端只返回按像素桶归并的 **min/max**（1000 桶 = 2000 个数字），不传原始采样
  （10 分钟音频 2600 万采样点，传前端必然卡死）。用 min/max 而非均值，
  是为了保留枪声/爆破音这类短促声音。前端 canvas 三层绘制（波形 → 字幕覆盖区 → 播放头），点击跳转。
- **ASR 引擎扩充到 4 个**。新增 `qwen3`（Qwen3-ASR 0.6B）与 `firered`（FireRed-ASR，双版本签名均支持）。
  实测对比（同一批音频，16k 重采样）：粤语、中英混说、中文绕口令、英语说唱四项 **Qwen3 明显更准**
  （如说唱：`Why do I still write? Sometimes it's hard enough` vs SenseVoice 的
  `While was still right sometimes it hard`），日语打平。
  **代价是慢 6~8 倍**（4.0s vs 1.2s），模型 936MB —— 所以定位是**按素材选**：
  中文游戏喊话用 SenseVoice，多语言/混说/说唱/口音用 Qwen3。
  Qwen3 官方支持 40 语言 + 19 种中文方言 + 歌词/说唱识别。
  `_read_wav` 从「采样率不对就报错」改成**自动转 16k 单声道**（实测官方测试音频 5 个里 3 个是 44.1kHz）。
- **翻译服务扩充：非 OpenAI 协议**。新增 `src/translate_engines.py`：**DeepL** 与 **Google Cloud Translation**。
  原有 25 个 provider 全走 OpenAI 兼容协议，拿 `/chat/completions` 调 DeepL 必然 404。
  **为什么需要**：LLM 会漏句/改写/合并行，专用翻译不会，但不懂上下文 —— 两者互补。
  关键契约：**返回条数必须等于输入条数**，不等就整批报错（字幕与时间轴错位比译不准严重得多且极难察觉）。
  `Provider` 新增 `protocol` 字段（openai | deepl | google），让 UI 能区分「要不要填 base_url」。
- **ASS 字体内嵌（MKV attachment）**。新增 `src/fonts.py` + `GET /api/system/fonts`。
  这是「用户自己看不出问题」的典型：ASS 只记录**字体名**，渲染时靠播放器去系统里找，
  在自己机器上一切正常，发给别人或放到安卓电视上就掉成默认字体/方框。
  把 TTF/OTF 作为 attachment 塞进 MKV 后，libass / mpv / VLC 会自动加载。
  - `mimetype` 与 `filename` **必须显式写**：不写 mimetype，libass 认不出这是字体，
    文件变大了却一点效果没有（白嵌）；filename 要能被 libass 匹配到字体族名。
  - **只在 MKV 生效**（MP4 容器不支持 attachment）：输出 mp4 时静默忽略而不是报错 ——
    用户要 mp4 是他自己的选择，不该因此拿不到字幕。
  - **字体缺失不中断出片**：找不到就跳过并在响应里如实报告 `fonts_missing`。
    没有内嵌的字幕在本机照样能播，为「对方没装字体」让整个封装失败是不成比例的惩罚。
  - 字体名支持候选链（`"Microsoft YaHei, SimHei"`），与 libass 的回退顺序一致。
  - 实测：simhei.ttf 9.3 MB → MKV 从 3.40 MB 涨到 12.70 MB（差值 9.30 MB 与字体文件精确一致），
    输出中可见 `Stream #0:3: Attachment` + `mimetype: font/ttf`。
  - 设置界面「软字幕封装」新增「内嵌字体」下拉，只列出**能真正找到文件**的族名。
- **崩溃隔离**。新增 `src/worker.py`：pipeline 改在**独立子进程**执行。
  CTranslate2 / sherpa-onnx / onnxruntime 都是原生库，崩溃不走 Python 异常、try/except 拦不住 ——
  原来在线程池里跑，一个视频崩了会让整个 `subai-backend.exe` 消失，同时运行的其它任务全丢，
  桌面端显示「后端离线」。隔离后同一崩溃只是「这个任务失败」，服务继续活着，
  卡死在 C++ 里的任务也能被 terminate 停掉。进度靠 stdout 行协议转发，现有回调无需改动。
- **`docs/LESSONS.md` 扩充到 9 条**（新增 L-007 ~ L-009）。
- **sherpa-onnx 语音识别引擎**（可选，默认不启用）：新增 `sensevoice` / `paraformer` 两套中文引擎，
  中文识别更准、速度快 2~4 倍。切换方式 `SUBAI_ASR_ENGINE=sensevoice`（或 `paraformer`）后重启，
  默认 `whisper` 行为完全不变。
  - 时间轴来自 **Silero VAD 段边界**（段级模型无词级时间戳），比按文本比例摊派更准
  - **GTCRN 降噪**可选（`SUBAI_ASR_DENOISE=true`），默认关：实测会把「有敌人」改成「就敌人」
  - 两个模型都内置的理由：SenseVoice 的 `use_itn` 给阿拉伯数字（「4246」），
    Paraformer 词汇更准但数字念成中文（「四十二四十六」）——字幕场景优先 SenseVoice
  - 新增 `GET /api/system/asr-engine` 只读状态接口；设置页新增「语音识别引擎」卡片
- **`docs/LESSONS.md`**：调研方法论教训（用无信息量素材做对比、没读对方文档就动手、
  参数没对齐就下结论等 6 条真实失误）

### 修复

- **产物串号（严重）**：`extract_audio` 固定输出文件名会串任务。原来写死 `TMP_DIR/audio16k.wav`，
  多任务并发时互相覆盖；更糟的是抽音轨失败时 `os.path.exists(wav)` 检查的是**上一次残留的文件**，
  于是检查通过，把**上一个视频的语音**当成本次输入。
  症状极具欺骗性：**传一个不存在的视频路径，居然「成功」输出 3 行字幕**（内容来自上一次跑过的素材）。
  现在每次用独立临时文件名、失败时清理、并在入口校验文件存在。
- **崩溃识别漏判**：Windows + Python 3.14 上空指针写的退出码只是 **1**，跟普通 Python 异常完全一样，
  唯一可靠信号是 stderr 的 `Windows fatal exception: access violation`。
  只查退出码表会把原生崩溃误判成普通报错，从而丢掉「换引擎重试」这条最有用的提示。
  现在 `is_crash()` 同时看退出码与 stderr，并从 stderr 认出具体崩溃类型。
- **`force_style` 列错位**：Style 行第一列是 Name，不属于 force_style。整串右移一位会让
  字体名变成 "Default"、字号失效，且 ffmpeg 全程不报错。现在明确跳过首列。
- **颜色把单词当十六进制**：`bad` / `abc` 的字符恰好都是合法十六进制，会被解析成 `#bbaadd`。
  现在**无井号的 3 位形式一律不认**（`#f00` 认，`bad` 不认），非法值回落白色。
- **字幕切分把词切成两半**：「我们广泛应用」在字数上限处会在「广\|泛」之间硬切。
  现在超字数时回溯到词边界（优先切在停顿标点之后，无标点则退到最后一个完整词）。
- **停顿标点导致碎片行**：`break_punct` 默认含 `，,；;、`，原来所有标点一律立即切，
  「好，我们继续走」被切成「好，」/「我们继续走」两条（第一条仅 2 字，人眼来不及读）。
  现在句末标点（`。！？!?…`）立即切，停顿标点达软上限（`max(6, 60%×上限)`）才切。
- **新增最短显示时长护栏**：原来只有「最长 8 秒」没有下限，会切出 0.15 秒的「给我」。
  过短行会延长，但**不越过下一行起点**（宁可短，不重叠；只动 end 不动 start）。
  实测 146 秒素材：<1 秒碎片行从 **27% 降到 17%**，而**文本内容 400 字一字未改**。

### 变更
- `.gitignore`：补 `corpus/`、`data/known_terms.json`、`models/sherpa/`
- `requirements.txt`：新增 `sherpa-onnx>=1.13,<3`（可选，不装也能跑）
- `config.py`：新增 `min_display_sec`（默认 1.0，`SUBAI_MIN_DISPLAY_SEC` 可覆盖，0=关闭）
- 设置页「字幕质量」卡片：新增「最短显示」「断句方式」两行

### 测试

- 新增 `tests/test_subtitle_formats.py`（16 项）：往返精度、格式固有局限、导入容错、格式识别
- 新增 `tests/test_subtitle_style.py`（44 项）：颜色 BGR/alpha 反转、force_style 列对齐、
  背景框取色、对齐映射、ASS 时间百分秒、零回归
- 新增 `tests/test_diarize.py`（15 项）：重叠归属（非包含判定）、编号重排、真实推理、
  双音源强制人数验证
- 新增 `tests/test_waveform.py`（13 项）：桶数恒定、min/max 而非均值、静音占比、真实解码
- 新增 `tests/test_asr_engines.py`（9 项）：模型完整性、tokenizer 必须是目录、引擎目录映射
- 新增 `tests/test_translate_engines.py`（26 项）：语言代码映射、条数不一致必须报错、HTML 实体还原
- 新增 `tests/test_worker.py`（16 项）：假字幕回归、独立文件名、失败清理、崩溃识别、真实段错误隔离
- 前端新增 `WaveformView.test.tsx`（5 项）、`MediaTools` 样式提交（2 项）
- 后端全量：**582 passed / 74 skipped / 0 failed**；前端 **65 passed**（12 文件）；tsc 无错
- 后端 **470 passed / 73 skipped / 0 failed**（543 项）；前端 **58 passed**（11 文件）
- 新增 `tests/test_asr_sherpa.py` 19 项（含 2 项真实推理，无模型自动跳过）

### 已知限制
- sherpa 系引擎**无词级时间戳**：一条 VAD 段内含多句时会整段作为一条字幕；
  需要细粒度断句时仍用 `whisper`
- sherpa 模型共 446 MB，绿色版打包体积会明显增大（当前未内置进主包）

## [5.0.0] - 2026-10-03

### 新增
- **免登录**：界面不做登录，改本机令牌（`data/local_token.txt` + `X-Local-Token`）；后端登录体系保留，`SUBAI_AUTH_REQUIRE_LOGIN=true` 可恢复
- **两段式字幕流程**：先出字幕草稿 → 确认页核对 → 再出片（`defer_render` + `POST /api/task/{id}/render`）
- **确认页**：逐句编辑、键盘操作、Ctrl+Z 撤销栈、拆分/合并、时间码编辑、可疑行高亮、播放器叠字与 seek
- **词级时间戳**：落盘 `.words.json`，字幕接口带出 `words`
- **术语包**：`src/term_packs.py`（56 条 ASR 纠错 + 17 条翻译术语），识别后自动纠错
- **任务管理**：回收站（归档/取消）、批量删除、彻底移除（含产物，路径白名单）、鼠标框选
- **设置页精简**：删修改密码/运维/语言与报表卡片；新增「选服务商，只填 API Key 即可用云端」

### 修复
- 字幕「向下合并」`splice(j,2)` 会多删后一行 → 改 `splice(Math.min(i,j),2)`
- 回收站批量删除误走软删除（archive）→ 改 purge
- `DELETE /api/task/purge` 与 `/api/task/{task_id}` 路由冲突 → 统一 `POST + JSON body` 传 id
- `scrollIntoView` 无能力检测会导致确认页渲染空白

### 说明
- 发布形态为免费开源的本机工具；原「五期 = 商业发布（订阅制/多端 App/客服）」规划作废

## [5.0.1] - 2026-10-17

### 修复
- **两段式真正生效**：`defer_render` 此前只出现在函数签名里、无人读取，前端传 true 时任务仍会自动出片，确认后再压一遍。现改为只留草稿、确认后由 `/render` 出片
- **打包防混搭**：Tauri 的 `externalBin` 副本（`frontend/src-tauri/binaries/subai-backend-*.exe`）此前未随 PyInstaller 重建更新，导致 v5.0.0 安装包是「新前端 + 旧后端」；现已同步，并在 spec 补 `excludes` 把无用重包排除（176 MB vs 395 MB）

### 2026-10-24 审计清理（安全 / 交付链 / 依赖 / 体积）

**安全**
- 云端 API Key 不再落在安装目录：`.env` 改为三级加载（真实环境变量 > `%APPDATA%/SubAI/.env` > 安装根），
  「设置」页保存的 Key 也写入用户级位置，整个目录拷给别人不再带走额度
- `tools/build_green_package.ps1` 增加分发安全闸门：发现含机密的 `.env` 直接 `exit 3`，不再是打印提示
- 顺手修掉一个隐藏 bug：源码模式下 `_project_root()` 指向 `源码/`，此前**根本读不到上一级的 `.env`**

**交付链**
- 版本号统一到 `5.0.1`（`src/__init__.py` / tauri.conf / package.json / package-lock / Cargo.toml）
- `bundle.resources` 移除 `models/**`：`npm run tauri:build` 产出 **lite 包**，
  新增 `npm run tauri:build:full`（合并 `tauri.full.conf.json`）产出含模型包 —— 与 README 承诺的「lite」口径对齐
- 新增 `tools/make_latest_json.ps1`：从安装包 `.sig` 生成 `latest.json`，缺签名直接报错退出。
  此前仓库内 `latest.json` 停在 4.1.0，而 updater 指向 `releases/latest`，应用内「检查更新」拿不到 5.x

**工程**
- `requirements.txt` 全部加上界（`pillow>=12.3.0,<13`、`rapidocr-onnxruntime>=1.2.3,<1.3` 等）；
  README 明确「常规装 requirements.txt，精确复现才用 lock」
- 新增 `tools/run_tests.ps1`：本地一键跑后端 pytest + 前端 vitest（CI 在 GitHub Actions，而主用机常连不上 GitHub）
- **修掉一个影响真实使用的环境陷阱**：`src/config.py` 新增 `normalize_no_proxy()` 并在导入期执行。
  httpx 在 trust_env=True 时会把 `NO_PROXY` 的每一项**按 URL 解析**，带方括号的 `[::1]` 被解析成 port=':1]'
  并抛 `httpx.InvalidURL: Invalid port: ':1]'`。后果不只是测试：**自检「翻译后端连通性」失败、
  连本地 koboldcpp 与云端 API 全部不可达**，而错误信息完全指向不了真因。
  修复后：脏 NO_PROXY 下自检由 `InvalidURL` 变为正常 `ConnectError`，koboldcpp 起来即 PASS。
  测试侧由 `tests/conftest.py` 复用同一归一化；全量 **508 passed / 0 failed**，
  双端真实翻译验收（本地 koboldcpp 1.9s / 云端 DeepSeek 2.4s，均 0 失败行）见 `docs/KNOWN-LIMITS.md` 第五节

**真实素材实测（Delta Force 47 个片段，2026-10-24）**
- 用 4 个真实片段（1:40 × 3 + 5:31 × 1）跑完整链路，共 120 行语音。语音密度差异极大：
  18 秒/行（长片段，大片静默）到 2.2 秒/行（多人密集喊话）；19 秒那个片段**完全无语音**（纯音效，0 行）。
- **关键缺陷：ASR 结果不可复现。**同一视频两次跑出 46 行 vs 41 行，内容几乎无重叠。
  根因：`get_asr_device()` auto 模式要求空闲显存 ≥4GB，本地 LLM（koboldcpp 占 7.4G/8G）在跑时
  必然回落到 CPU int8，而 **CTranslate2 的 float16(GPU) 与 int8(CPU) 识别结果本来就不同**。
  连带影响：缓存 key 基于文本 → 切设备后缓存全失效；改进无法验收。
- 已修：`asr_segments` 打印 `[ASR] 设备=cpu 精度=int8`，回落 CPU 时明确提示原因（显存不足 / 本地 LLM 占用）
  并说明「切换设备会让同一视频出现不同字幕」。
- **CLI 词表链路断裂（已修）**：`run_pipeline` 的 `glossary` 只有 API 路径会传，命令行一直是 `None`
  → 用户在界面里加的词表用 CLI 跑完全不生效。新增 `load_glossary_from_db()` 兜底（同步读 SQLite）。
- 建词表「三角洲行动」8 条（蓝斜/离斜/给箭/血包/宿舍/航天基地/露娜/三角洲行动），全部走同音自动纠正：
  实测 `蓝鞋→蓝斜`、`离鞋→离斜`、`给剑→给箭`（×3）、`雪包→血包` 均命中 `auto`。

**术语澄清（2026-10-24）：项目里有三个不同的「两段/分段」，别混**
| 名称 | 作用 | 位置 |
|---|---|---|
| 两段式字幕确认（v5.0.0，v5.0.1 修好） | 先出字幕草稿 → 确认页核对 → 再渲染出片。管的是**什么时候出片** | `defer_render` + `POST /api/task/{id}/render` |
| 只识别不翻译（五期） | 识别后保留原文。管的是**要不要翻译** | `NO_TRANSLATE_TARGETS` / 界面第 2 个入口 |
| 只翻译（本次新增） | 读已有字幕只做翻译，跳过识别。管的是**要不要重新识别** | `run_pipeline(from_srt=)` / `--translate-only` |

**界面补齐三项能力（2026-10-24）**

调研后发现前端比我原先判断的完整得多（术语管理、配音、硬字幕压制、软字幕封装都在），
真正缺的是三个「后端有能力、界面没入口」的地方：

1. **词表支持变体写法**：`TerminologyManager` 管的是术语库（`/terminology`，管译法），
   词表（`/glossary`，管听错纠正）此前只能在向导里输入「每行一个词」，没法写 variants。
   现支持 `甲修 ← 甲球,甲秋` 与 `G:碰瓷M7 ← possm7`（与 `G:` 前缀自由组合），老写法不受影响。
   **顺带修掉一个静默 bug**：点「载入」只还原 `src`，用户把词表载入再存回去，variants 就被抹了；
   现在载入时还原成 `src ← a,b` 完整写法。
2. **`/api/compose` 暴露 `target_lang`**：`_run_compose_task` 早就支持「跳过识别只翻译已有字幕」，
   但这条路由一直硬编码 `target_lang="none"`，于是界面只能「直接套用」——想翻译必须回头重跑识别。
   前端新增「直接套用 / 先翻译再出片」开关 + 目标语言选择，等价于 CLI 的 `--translate-only`。
3. **字幕质量开关进设置页**：新增只读接口 `GET /api/system/subtitle-quality`，
   显示「丢弃疑似幻觉」与「单行最长显示」。**刻意做成只读**——这两项在 pipeline 导入时就进了
   模块常量，运行时改配不生效；写一个「保存了但没生效」的接口只会更误导，界面上明确提示改 `.env` 后重启。

测试：前端 58 passed（新增 `glossaryParse.test.ts` 7 项），后端相关子集 24 passed
（新增 `test_compose_route.py` 3 项：转发 / 默认 / 空白归一）。

**单行字幕显示时长上限（2026-10-24）**
- 现象：VAD 判定「一段时间都在说话」时，whisper 可能只认出两三个字。实测 04.08 长视频里
  「有敌」这一行被写成 **36 秒**（因为后面 36 秒音频模型只抠出这两个字），观众会以为一直在说同一句。
- 新增 `MAX_DISPLAY_SEC`（默认 8 秒，`SUBAI_MAX_SUBTITLE_SEC` 可覆盖）：超长行截短结束时间，
  **只截短不延长、不动 word 时间戳**，并打印「N 行超过 8 秒已截短」。实测该视频 7 行被截短。

**词表扩容到 22 条 + 近音判定收紧（2026-10-24）**
- 补入官方条目（百度百科可抓，B站 wiki 是 JS 动态渲染抓不到）：干员 红狼/蜂医/露娜/牧羊人/威龙/深蓝/无名，
  点位 组装室二楼，枪械锚点 M7/M14。作用是同音纠正 + 防止专名被翻译成普通词。
  **英文译名故意不填**——官方译法未经确认，乱填比不填更糟，交给翻译模型音译。
- **近音判定收紧为「首字必须相同」**：词表扩到 22 条后，原规则（共享任一汉字即标记）噪音爆炸 ——
  实测「深蓝往蓝鞋那边」一条就冒出「往蓝→深蓝」「蓝往→蓝斜」「蓝斜→离斜」三条误报，
  把真正要看的「蓝鞋→蓝斜」淹没。真实误识别几乎都是首字对、尾字错（甲球/甲修、小鸡/小金、雪包/血包）。
- 测试同步调整为两条：首字相同的近音**只标记**（甲秋/甲修），首字不同的近音**不标记**（队长/橘长）。

**幻觉自动丢弃（2026-10-24，默认关）**
- 实测证据：同一视频 GPU(float16) 首行「没事我有大血包」（真实，用户人耳确认），
  CPU(int8) 首行却变成「而且卡不了星标」——用户根本没说过这句。
  **认不全只是少内容，编造则是脏数据**，性质不同，所以给一个可选强过滤。
- `src/config.py` 新增三项：`SUBAI_ASR_DROP_HALLUCINATION`（默认 false）、
  `SUBAI_ASR_HALLUCINATION_NSP`（默认 0.6）、`SUBAI_ASR_HALLUCINATION_CR`（默认 2.4）。
- `src/pipeline.py` 新增 `_filter_hallucination()`：按 no_speech_prob / 压缩比剔除疑似段。
  丢弃内容**逐条打日志**（含阈值实测值），绝不静默删除——沿用项目「宁可少一行也要能对账」的原则。
- 新增 `tests/test_hallucination.py`（5 项）：高 no_speech 丢弃 / 高压缩比丢弃 /
  空文本不计入任一侧 / 阈值可配 / **默认阈值不误伤真实语音**（nsp 0.38、压缩比 1.9 应保留）。

**词表支持 variants：不同音、不同长度的强制映射（2026-10-24）**
- 起因：用户听原片后确认的误识别，**既不同音也不同长度**，原有「拼音全等才自动改」规则完全够不着：
  甲球→甲修(qiu/xiu)、小鸡→小金(ji/jin)、牛转→牛的(zhuan/de)、1414→M14(4字→3字)。
- `src/glossary.py` 的 `correct_text` 增加 `variants` 字段：用户**当面确认过**的误识别写法，
  做精确子串替换（长写法优先），不做任何拼音推断。填错才会改错，所以只收人工确认过的。
- 词表扩到 12 条：蓝斜/离斜/给箭/血包（同音类）+ 甲修/小金/牛的/M14（variants 类）+ 4 条锚点词。
  术语库扩到 13 条，新增 甲修→armor repair kit、小金→gold item、M14→M14、牛的→sick。
- 实测（4 行样本，全部命中）：`我要甲球 我要小鸡` → `I want armor repair kit I want gold item`；
  `1414 快拿快拿` → `M14 Hurry up and take it`；`牛转 牛转` → `sick sick`；`往里炫` → `dig in`。

**两段式第二段词表失效（2026-10-24 修复）**
- 词表纠错原本写在 `asr_segments` 内部，`from_srt` 跳过识别后**完全走不到** →
  两段式第二段（只翻译）的词表形同虚设（实测甲球/1414/牛转一个都没纠正）。
- 已在 `from_srt` 分支补上纠错，保证「纠错 → 摘要 → 翻译」顺序与直连路径一致。
- 顺带消解了一个连带现象：词表未纠正时占位符术语会错配，译文里残留 `[[T1]]`；修后术语命中 4/4 正常还原。

**三角洲术语表 + CLI 统计修复（2026-10-24）**
- 新增 `data/delta_terms.json`（9 条）：把用户确认过的**真实表达**做成翻译映射，与「词表」分工明确：
  - **词表（glossary）** 纠 ASR 听错的字：蓝鞋→蓝斜、给剑→给箭、雪包→血包
  - **术语库（terms）** 定译法：往里炫→dig in、血包→medkit、蓝斜→blue slope、宿舍→dorm
  - 「往里炫」是用户口癖（=尽情吃，炫表吃），**不是识别错误**，因此只进术语库不进词表。
- 实测效果（4 行样本）：`往里炫 往里炫` → **dig in dig in**（原直译 `Enjoy inside`）；
  `没事我有大血包` → `I have a big **medkit**`（原 `snow bag`）；`蓝斜上一个` → `**blue slope**`；
  `宿舍那边有人` → `**dorm** There is someone there`。
- **CLI 统计恒为 0 的缺陷（已修）**：`main()` 调 `run_pipeline` 时从未传 `stats`，于是日志里
  「术语命中」永远是 0 —— 明明术语生效了也看不出来（实测 4 处替换、日志报 0）。现在传入并额外打印统计行。

**compose 任务的取消与进度（2026-10-24 加固）**
- 发现两处原有缺陷：「我已有字幕文件」(mode=compose) 分支在 `register_cancel_token` **之前就 return**，
  导致这类任务**根本无法取消**（DELETE 置不了位），翻译长视频时只能干等；同时翻译期间进度恒为 0.15。
- 已修：compose 分支补上令牌注册/注销，`is_set` 作为 `should_cancel` 传进翻译阶段；
  新增进度映射 0.15→0.85（`run_pipeline` 的 progress_callback 经 `run_coroutine_threadsafe` 回主循环）；
  用户主动取消时标 `cancelled`（不再误报成「翻译失败」）。
- 新增 `tests/test_compose_task.py`（5 项）：无目标语言不翻译 / 有目标语言走 `from_srt` 且**优先用双语出片** /
  `target=none` 不翻译 / 翻译抛异常必须 failed 且**不允许继续出片** / 字幕文件缺失快速失败。

**「已有字幕 + 翻译」这条路（2026-10-24 补缺）**
- 原先「我已有字幕文件」(mode=compose) 只能**直接套用**，想翻译必须回头重跑一遍识别（白等一次 ASR）。
- `_run_compose_task` 增加 `target_lang`：给了目标语言就先跳过识别、只翻译已有字幕，再用
  **双语字幕**出片（优先 bilingual，没有则用目标语言单语），结果文件列表同步改为实际使用的那份。
- 对本地隐私流程的意义：可以用 GPU 先识别好字幕，之后再起本地 LLM 只做翻译，全程不出网。
- 新增 `tests/test_pipeline_from_srt.py`：把 `asr_segments`/`extract_audio` 换成**抛异常的桩**，
  以此证明 `from_srt` 路径绝不触发识别；同时验证时间轴沿用原字幕、双语与单语产物齐全。

**两段式拆分（本地隐私流程的关键改进，2026-10-24）**
- 背景：8GB 显存放不下「本地 LLM + GPU 识别」。koboldcpp 占 7.4G/8G 后，`get_asr_device()` 因空闲 <4GB
  回落到 CPU int8 —— 识别慢约 10 倍（100 秒音频 51 秒），且 **int8 与 float16 结果不同**，
  同一视频与云端模式跑出不同字幕。隐私内容用户被迫在「慢/不一致」和「上云」之间二选一。
- 新增 `--translate-only <SRT>`：读取已有字幕（如 `<名称>.source.srt`）只做翻译，跳过识别，
  时间轴沿用原文件（`src/subtitles.parse_srt`）。配合已有的 `--target none`（只识别）形成两段式：
  **阶段1 GPU 空闲时跑识别 → 阶段2 再起本地 LLM 翻译**，隐私流程也能拿到 GPU 级速度与一致性。
- 实测：只翻译阶段 **41 行 / 3.43s / 7 次请求 / 总耗时 5.3s**（完整链路同一视频为 49~63s）。
- 顺带：ASR 返回 0 行时不再静默，提示「未检测到语音内容，该片段可能只有游戏音效、没有人声」
  （实测 19 秒纯跑图片段印证：有音轨、0 行、覆盖 0%）。

**CLI 与启动**
- 修 `python src/pipeline.py` 直接运行会触发循环导入（`ImportError: cannot import name 'TaskManager'`）：
  直接运行该文件时 `src/` 被放进 sys.path[0]，aiosqlite 内部的 `import queue` 解析到本项目的 `src/queue/` 包
  而非标准库。已在文件顶部按 `src/start.py` 的同样做法纠正 sys.path[0] 为仓库根。
  （`python -m src.pipeline` 一直正常；README 承诺的直接运行方式现已兑现）

**测试隔离（修掉一处会污染真实数据的隐患）**
- **翻译缓存污染**：`get_translation_cache()` 是全局单例，**一旦初始化就一直用旧 db 路径** ——
  测试里 monkeypatch `config.cache.db_path` 形同虚设，于是 e2e 用例中 mock LLM 的「译文=原文」
  被写进真实 `data/translation_cache.db`，之后真实运行命中该缓存直接输出原文
  （实测：清缓存前 3 行全是中文，清后正常出英文）。
- 修法：`tests/conftest.py` 新增 **autouse fixture**，每个用例前后重置 `translation_cache` /
  `task_manager` 单例，并默认把缓存路径指到该用例的 tmp 目录；需要自定义路径的测试仍可覆盖。
- 验证硬证据：删掉真实 DB 后跑涉及 pipeline/翻译的 8 个测试文件 —— **61 passed**，
  且 `data/translation_cache.db` **未被重新创建**（修复前跑一次就会变成 24~90 KB）。

**体积**
- 清理过期产物与构建缓存约 3.9 GB：`src-tauri/target`(2.7G)、`build/`(209M)、
  `dist-green-lite/`(304M)、release 下 4.1.0 与 5.0.0-lite 旧包(735M)
- 明细见 `backup-20261024/CLEANUP-LOG.md`；`源码/dist/` 保留（打包脚本前置产物）

## [4.2.0] - 2026-10-02 —— 安装包与自动更新

### 新增
- **安装包（NSIS）**：精简版（不含 ASR 模型）；静默安装、开始菜单与卸载程序
- **自动更新**：应用内「检查更新 → 下载并安装 → 自动重启」，更新包经签名校验
- 版本号统一为单一来源 `src/__init__.py:__version__`

### 修复
- 版本号三处漂移（后端/界面/应用内帮助）已对齐

## [4.1.0] - 2026-10-01 —— 四期深化

### 新增
- 按 API 密钥限流（每密钥独立上限，0 = 不限），超限返回 429 与标准响应头
- Webhook 持久化兜底：启动重投 + 定期巡检 + 手动重投，重试预算跨重启累计
- 插件市场远端安装：sha256 校验、显式确认、体积双限、防目录穿越；**安装 ≠ 启用**
- 开放 API 建任务 `POST /api/open/v1/transcode`（含每密钥每日配额）
- 「开放平台」界面：密钥与 Webhook 管理

## [4.0.0] - 2026-10-01 —— 四期主体交付

### 新增
- **多语言**：72 种语言（识别 44 / 翻译 72 / 配音 35），自动检测（实测准确率 98.77%）
- **API 开放平台**：API 密钥（只存哈希）、Webhook（HMAC 签名 + 重试 + 投递记录）、`docs/API.md`、Python / JavaScript SDK
- **数据分析**：使用统计与质量分析，报表导出 Excel / PDF / HTML

## [3.4.0] - 2026-10-01 —— 插件系统

### 新增
- 插件框架与 5 个核心插件（本地/云端翻译、RapidOCR、SAPI、Edge TTS）
- 「插件」界面：启用/禁用、优先级、能力视图
- **禁用插件 = 能力真正不可用**（而非悄悄回退内置实现）

## [3.3.0] - 2026-10-01 —— 四期 4.1 / 4.2 接通界面

### 新增
- 硬字幕烧录、软字幕封装、时间轴对齐配音的界面入口

## [3.0.0] - 2026-09-29 —— 生产版

### 新增
- 任务队列、断点可取消、翻译缓存、术语库（强制锁定 / 软提示）
- 用户体系与数据隔离、自动备份、告警巡检、容器化与 CI

## [2.0] - 2026-09-20 —— 公测版

## [1.0] - 2026-09-15 —— 内部试用版
