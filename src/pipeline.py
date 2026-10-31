# -*- coding: utf-8 -*-
"""
SubAI Translator —— 正式Pipeline（一期完整版）
===============================================

基于冒烟脚本 src/pipeline_smoke.py 的增强版，新增：
1. 术语库集成（SQLite，精确匹配）
2. 多格式输出（SRT/VTT/ASS/JSON）
3. CLI批处理（支持目录扫描）
4. 断点续翻（翻译结果落库，失败可续）
5. 进度回调（供API或CLI显示进度）

设计约定：
* 完全兼容冒烟脚本的CLI参数
* 新增 --db 参数指定术语库路径
* 新增 --output-format 参数指定输出格式（默认srt）
* 新增 --resume 参数支持断点续翻
* 所有核心函数都可被API调用
"""
from __future__ import annotations

# [P1 2026-10-24] 支持 `python src/pipeline.py` 直接运行。
# 直接运行该文件时，Python 会把 `src/` 放进 sys.path[0]，于是 aiosqlite 内部的
# `import queue` 会解析到本项目的 `src/queue/` 包而不是标准库，触发循环导入：
#   ImportError: cannot import name 'TaskManager' from partially initialized module
# 修法：把 sys.path[0] 纠正为仓库根（与 src/start.py 的做法一致），标准库优先。
import os as _os
import sys as _sys

if __name__ == "__main__":
    _HERE = _os.path.dirname(_os.path.abspath(__file__))
    if _sys.path and _os.path.abspath(_sys.path[0]) == _HERE:
        _sys.path[0] = _os.path.dirname(_HERE)

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

# 添加项目根目录到路径
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src import languages as languages_module
from src.db.terminology import TerminologyManager
from src.config import config as _cfg, ensure_cuda_dll_path
from src.plugins.seams import CapabilityDisabled, ocr_provider
from src import languages as languages_module
from src.cancel import raise_if_cancelled
from src.cache.translation_cache import TranslationCache
from src.retry import retry, RetryExhausted

# 常量定义（统一从 config 读取，避免硬编码路径；保留模块级常量便于外部引用）
FFMPEG = _cfg.ffmpeg
# 五期：模型目录允许用 SUBAI_ASR_MODEL_DIR 覆盖（默认仍是 models/faster-whisper-small）。
# 有了它就能在 small / large-v3-turbo 之间切换**而不必动 junction**，避免 junction
# 被 Tauri 打进安装包（models/** 是 resources）。
MODEL_DIR = (os.environ.get("SUBAI_ASR_MODEL_DIR") or "").strip() or _cfg.models_dir
OUT_DIR = _cfg.out_dir
TMP_DIR = _cfg.tmp_dir

# 兼容旧字段：保留 KOBOLD_URL/KOBOLD_MODEL 以便外部 import 不破坏
KOBOLD_URL = _cfg.llm.local_url
KOBOLD_MODEL = _cfg.llm.local_model

# 字幕切分阈值（从 config 读取，支持环境变量覆盖）
MAX_CHARS = _cfg.max_chars
MAX_DUR = _cfg.max_dur
BREAK_PUNCT = _cfg.break_punct

# [P1 2026-10-24] 单行字幕最长显示时长（秒），可用 SUBAI_MAX_SUBTITLE_SEC 覆盖。
# 起因：VAD 判定「一段时间都在说话」时，whisper 可能只认出两三个字（实测「有敌」这一行
# 被写成 36 秒，因为紧接着的 36 秒音频里模型只抠出这两个字）——观众会以为一直在说同一句。
# 超时就截断，宁可留出静默，也不让一行字霸屏半分钟。
MAX_DISPLAY_SEC = float(os.getenv("SUBAI_MAX_SUBTITLE_SEC") or 8.0)


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
_pipeline_logger = logging.getLogger("src.pipeline")


def log(msg: str, force_flush: bool = True) -> None:
    # 保留 print 以兼容 CLI 即时输出；同时写入统一日志（API 场景可观测）
    print(msg, flush=force_flush)
    _pipeline_logger.info(msg)


def fmt_ts(seconds: float) -> str:
    """秒 -> SRT时间戳 00:00:00,000"""
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def run_ffmpeg(args: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error"] + args,
        capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace"
    )


# --------------------------------------------------------------------------- #
# 第1步：抽音轨
# --------------------------------------------------------------------------- #
def extract_audio(video: str) -> str:
    """视频 -> 16kHz单声道PCM wav（Whisper原生输入格式）。

    [2026-10-25 修] 两个 bug 一起修，都很严重：

    1. **固定输出文件名会串任务**。原来是 `TMP_DIR/audio16k.wav` 写死，
       多任务并发时互相覆盖；更糟的是抽音轨失败时下面那个
       `os.path.exists(wav)` 检查的是**上一次残留的文件**，于是通过了，
       把**上一个视频的语音**当成本次的输入，用户拿到完全错误的字幕。
       实测：传一个不存在的视频路径，居然"成功"得出 3 行字幕
       （内容来自上一次跑过的素材）。现在改成单一来源的临时文件名。

    2. **输入根本没被校验**。ffmpeg 失败时只报「抽音轨失败」，
       用户不知道是路径错、文件损坏、还是没有音轨。现在先明确校验。

    另外失败时清理输出文件，避免残留再次被下一次误用。
    """
    if not os.path.isfile(video):
        raise FileNotFoundError("视频文件不存在：%s" % video)
    os.makedirs(TMP_DIR, exist_ok=True)
    # 每次独立文件名：杜绝并发覆盖 + 杜绝读到上次残留
    import uuid
    wav = os.path.join(TMP_DIR, "audio16k_%s.wav" % uuid.uuid4().hex[:12])
    r = run_ffmpeg(["-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000",
                    "-c:a", "pcm_s16le", wav])
    ok = os.path.exists(wav) and os.path.getsize(wav) >= 1000
    if not ok:
        # 清理干净，别把半成品留给后续逻辑（也避免占盘）
        try:
            if os.path.exists(wav):
                os.remove(wav)
        except OSError:
            pass
        err = (r.stderr or "").strip()
        # 把 ffmpeg 的常见错误翻成人话，用户照着改就能解决
        hint = ""
        low = err.lower()
        if "no such file" in low:
            hint = "（路径不存在，请确认文件还在）"
        elif "does not contain any stream" in low or "matches no streams" in low:
            hint = "（这个文件没有音轨，可能只有画面）"
        elif "invalid data" in low or "moov atom not found" in low:
            hint = "（文件损坏或不是有效视频）"
        raise RuntimeError("抽音轨失败%s：%s" % (hint, err[:300]))
    return wav


# --------------------------------------------------------------------------- #
# 第2步（A）：语音识别
# --------------------------------------------------------------------------- #
# [2026-10-25] 停顿标点 vs 句末标点 —— 这两类不能同等对待。
#
# 原实现把 break_punct（默认值已含「，,；;、」）里的所有标点一律当「立即切」，
# 结果「好，我们继续走」被切成「好，」「我们继续走」两行：第一条只有 2 个字，
# 观众眼睛还没定位就闪走了。实测这类碎片行在游戏素材里占比很高。
#
# 现在分两类：
#   - 句末标点（。！？!?…）→ 语义完整，立即切
#   - 停顿标点（，,；;、）  → 只是句中停顿，达到软上限才切，否则继续累积
#
# 软上限取 max(MIN_SOFT_CUT_CHARS, 60% * max_chars)：既避免切出极短行，
# 又保证标点不会被无谓地顶到硬上限之后（一行 20 字才断，读起来憋）。
_PAUSE_PUNCT = "，,；;、"
MIN_SOFT_CUT_CHARS = 6


def _cut_backtrack(words: list, max_chars: int) -> int:
    """硬切点回溯：当前一批词超过 max_chars，返回「切在前 i 个词之后」的 i（1-based）。

    [2026-10-25] 背景：原实现是**字数一到就硬切**，于是「我们广泛应用」会在
    「广|泛」之间断开，切出「我们广」「泛应用」两条——单看每条都成立，合起来是半个词。
    SmartSub 对此的处理是「硬上限回溯到最近可断标点，无标点则退回词边界」，
    这里照同一思路实现，但只用**已有信息**（whisper 的词级切分本身就是词边界，
    不需要引入 Intl.Segmenter 那样的分词器）。

    回溯优先级：
    1. 最近一个**软切标点**（，；等）之后 —— 语义最自然
    2. 否则退到「不超过上限的最后一个词」—— 保证不拆词
       （whisper 的 word 已是词/字级单元，切在词之间就不会拆开中文词）

    返回 0 表示无法回溯（例如第一个词自身就超长），调用方按原样直切。
    """
    if not words:
        return 0
    # 从后往前找软切标点（只看不超过 max_chars 的范围，避免切出过短的一条）
    acc = ""
    limit_idx = 0
    for i, w in enumerate(words, 1):
        acc += w.word
        if len(acc.strip()) <= max_chars:
            limit_idx = i
        tail = w.word.strip()[-1:] if w.word.strip() else ""
        if tail and tail in _PAUSE_PUNCT and len(acc.strip()) <= max_chars:
            # 找到软切标点：只有当它后面还有词（否则等于不回溯）才采用
            if i < len(words):
                return i
    # 没有软切标点：退到不超过上限的最后一个词边界
    return limit_idx if 0 < limit_idx < len(words) else 0


def _enforce_min_display(rows: list[dict], min_sec: float) -> tuple:
    """最短显示时长护栏：过短的字幕延长到 min_sec，但**不越过下一行开始时间**。

    [2026-10-25] 背景：原来只有「最长不超过 MAX_DISPLAY_SEC」这一道护栏，
    没有下限。实测会切出 0.15 秒的「给我」这种行——字是出来了，人眼来不及读。
    SmartSub 也有同一道护栏（enforceMinDisplayDuration）。

    三条硬约束（缺一条都会让结果更糟）：
    1. 只延长 end，不动 start —— 起点是语音真实起点，改它会与音频错位
    2. 不得越过下一行的 start（否则两行同时显示）
    3. 不得越过音频总时长（调用方不传则不限制）

    返回 (rows, 调整行数)。
    """
    if min_sec <= 0 or not rows:
        return rows, 0
    fixed = 0
    for i, r in enumerate(rows):
        try:
            start = float(r["start"])
            end = float(r["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end - start >= min_sec:
            continue
        target = start + min_sec
        # 约束 2：不越过下一行起点
        if i + 1 < len(rows):
            try:
                nxt = float(rows[i + 1]["start"])
            except (KeyError, TypeError, ValueError):
                nxt = None
            if nxt is not None and target > nxt:
                target = nxt
        if target > end:
            r["end"] = round(target, 3)
            fixed += 1
    return rows, fixed


# [2026-10-25] 语音覆盖率 / 漏句检测 —— 结构化输出。
#
# 背景：这段逻辑原本只把结果写进日志（"[ASR 覆盖] 音频 146.3s / 字幕覆盖 105.6s（72%）"），
# 普通用户永远看不到。同类项目 SmartSub 会把「这段有人说话但没识别出内容」提示到界面
# （missedSpeechWarning）。算法我们早有，缺的是**让用户看见**。
#
# 这里把它抽成纯函数：不依赖 info 对象、不写日志、不抛异常，便于单测与复用。
#
# 口径说明（重要，避免误读）：
# - 统计的是「字幕覆盖时长 / 音频总时长」，能反映**漏识别**，
#   但**不等于**「VAD 检出段被保留的比例」（whisper 不暴露 VAD 段数）。
# - 空洞 = 相邻字幕之间、或首尾与音频边界之间，静默 ≥ gap_min_sec 的区间。
#   它既可能是「真没人说话」，也可能是「有人说话但没识别出来」——
#   两者用现有信息无法区分，所以文案必须写成「未覆盖」而不是「漏识别」。
GAP_MIN_SEC = 2.5

# 超过这个比例才提示用户。低于它属于正常（换气、停顿、音效段落）。
COVERAGE_WARN_PCT = 60.0


def probe_duration(media: str) -> float:
    """用 ffprobe 取媒体总时长（秒）。失败返回 0（调用方据此跳过覆盖率统计）。

    为什么不用识别结果的 info.duration：hardsub（OCR）与 from_srt（只翻译）两条路径
    根本没有 ASR 的 info 对象，而覆盖率对这两条路径同样有意义。
    """
    # 本机绿色版只带 ffmpeg.exe、不带 ffprobe.exe（实测 bin/ 下只有 ffmpeg），
    # 所以优先找同目录 ffprobe，找不到就退回用 ffmpeg 自己打印的 Duration 行。
    try:
        import subprocess as _sp
        probe = os.path.join(os.path.dirname(FFMPEG), "ffprobe.exe") if FFMPEG else "ffprobe"
        if os.path.isfile(probe):
            r = _sp.run([probe, "-v", "error", "-show_entries", "format=duration",
                         "-of", "default=noprint_wrappers=1:nokey=1", media],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", timeout=30)
            val = (r.stdout or "").strip()
            if val:
                return float(val)
        # 回退：ffmpeg -i 的 stderr 里有 "Duration: HH:MM:SS.ss"
        import re as _re
        r2 = _sp.run([FFMPEG, "-hide_banner", "-i", media],
                     capture_output=True, text=True, encoding="utf-8",
                     errors="replace", timeout=30)
        m = _re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)", r2.stderr or "")
        if not m:
            return 0.0
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:  # noqa: BLE001
        return 0.0


def compute_coverage(rows: list, duration: float, gap_min_sec: float = GAP_MIN_SEC) -> dict:
    """计算字幕覆盖率与空洞。返回 dict；duration<=0 时返回空 dict。

    返回字段：
      duration      音频总时长（秒）
      covered       被字幕覆盖的时长（秒）
      coverage_pct  覆盖率百分比（0~100）
      blank         未覆盖时长（秒）
      gaps          [{start, end, sec}, ...] 每处空洞
      gap_min_sec   判定空洞的最小静默时长
      warn          是否值得提示用户（覆盖率低 或 存在 ≥3 处空洞）
    """
    try:
        dur = float(duration or 0)
    except (TypeError, ValueError):
        return {}
    if dur <= 0:
        return {}
    try:
        gmin = float(gap_min_sec)
    except (TypeError, ValueError):
        gmin = GAP_MIN_SEC

    covered = 0.0
    gaps = []
    prev_end = 0.0
    for r in rows or []:
        try:
            s = float(r["start"])
            e = float(r["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if s > prev_end:
            seg = s - prev_end
            if seg >= gmin:
                gaps.append({"start": round(prev_end, 3), "end": round(s, 3), "sec": round(seg, 3)})
        # [2026-10-25] 只累计「未被前面行覆盖」的部分。
        # 原实现写 covered += (e - s) 会把重叠区间算两遍 —— 实测两行 [0,15] 与 [5,20]
        # 在 20 秒音频上得出 150% 覆盖率。字幕本不该重叠，但用户手改时间码、
        # 或多段合并时确实会出现，统计一旦失真，界面上的提示就不可信。
        covered += max(0.0, e - max(s, prev_end))
        prev_end = max(prev_end, e)
    # 尾部空白
    if dur - prev_end >= gmin:
        gaps.append({"start": round(prev_end, 3), "end": round(dur, 3), "sec": round(dur - prev_end, 3)})

    pct = 100.0 * covered / dur if dur > 0 else 0.0
    return {
        "duration": round(dur, 3),
        "covered": round(covered, 3),
        "coverage_pct": round(pct, 1),
        "blank": round(max(0.0, dur - covered), 3),
        "gaps": gaps,
        "gap_min_sec": gmin,
        "warn": pct < COVERAGE_WARN_PCT or len(gaps) >= 3,
    }


def _regroup(segments, max_chars: int = MAX_CHARS, max_dur: float = MAX_DUR) -> list[dict]:
    """把Whisper的长段落按标点/字数/时长切成一屏一行的字幕"""
    out: list[dict] = []
    for seg in segments:
        words = list(getattr(seg, "words", None) or [])
        if not words:
            text = (seg.text or "").strip()
            if text:
                out.append({"start": seg.start, "end": seg.end, "text": text,
                            "words": [round(seg.start, 3), round(seg.end, 3)]})
            continue
        cur = []
        for w in words:
            if not cur and not w.word.strip():
                continue
            cur.append(w)
            text = "".join(x.word for x in cur).strip()
            dur = cur[-1].end - cur[0].start
            tail = w.word.strip()[-1:] if w.word.strip() else ""
            # [2026-10-25] 标点分两类处理（见 _PAUSE_PUNCT 注释）：
            #   句末标点 → 立即切；停顿标点 → 达软上限才切，否则继续累积。
            _punct_hit = False
            if tail and tail in BREAK_PUNCT:
                if tail in _PAUSE_PUNCT:
                    _soft = max(MIN_SOFT_CUT_CHARS, int(max_chars * 0.6))
                    _punct_hit = len(text) >= _soft
                else:
                    _punct_hit = True
            if len(text) >= max_chars or dur >= max_dur or _punct_hit:
                # [2026-10-25] 因「字数」触发时先做词边界回溯，避免把词切成两半。
                # 因「标点」或「时长」触发时不回溯 —— 那两种情况本身就是天然断点。
                emit = cur
                carry = []
                if len(text) >= max_chars and not _punct_hit:
                    _k = _cut_backtrack(cur, max_chars)
                    if 0 < _k < len(cur):
                        emit, carry = cur[:_k], cur[_k:]
                if emit:
                    _t = "".join(x.word for x in emit).strip()
                    if _t:
                        out.append({"start": emit[0].start, "end": emit[-1].end, "text": _t,
                                    "words": [round(x.start, 3) for x in emit] + [round(emit[-1].end, 3)]})
                cur = carry
        if cur:
            text = "".join(x.word for x in cur).strip()
            if text:
                out.append({"start": cur[0].start, "end": cur[-1].end, "text": text,
                            "words": [round(w.start, 3) for w in cur] + [round(cur[-1].end, 3)]})

    # 过短的碎片（<2字）并入上一行
    merged: list[dict] = []
    for seg in out:
        if merged and len(seg["text"]) < 2:
            merged[-1]["text"] = (merged[-1]["text"] + seg["text"]).strip()
            # 五期修复：原来这里写 merged[-1]["end"] = seg["end"]，会把上一行字幕的结束时间
            # 推到碎片的时间点，于是"没人说话"的空档也被上一行字幕覆盖（用户看到"静默"占 4 秒）。
            # 文字接上即可，时间保持上一行自己的结束点。
        else:
            merged.append(seg)
    return merged


# 五期：通用称谓黑名单 —— 摘要的 terms 绝不能收这些词。
# 原因（真机实测）：prompt 里明确写了「不要收局长/队长这类通用词」，LLM 照样收，
# 还把它标成 type=person 并意译成 Director —— 把「主播名被听错」固化成术语错误。
# 所以这一层必须用代码兜底，不能只靠提示词。
_COMMON_NOUNS = {
    "局长", "队长", "长官", "指挥官", "将军", "领导", "老板", "主任", "经理",
    "老师", "师傅", "医生", "护士", "警官", "大哥", "大姐", "兄弟", "老弟",
    "小妹", "阿姨", "大叔", "同学", "朋友", "大家", "各位", "观众", "宝宝",
    "宝贝", "老铁", "家人", "家人们", "同志", "主播", "导演", "教授",
}


def _looks_like_common_noun(src: str) -> bool:
    """判断摘要抽出的词是不是通用称谓/日常词（这类词不能当术语注入翻译）。"""
    t = (src or "").strip()
    if not t:
        return True
    if t in _COMMON_NOUNS:
        return True
    # 「小明哥」「大哥们」这类：去掉后缀再比一次
    for suf in ("们", "哥", "姐", "叔", "姨", "老师", "大人"):
        if t.endswith(suf) and t[: -len(suf)] in _COMMON_NOUNS:
            return True
    return False


def _foreign_ratio(text: str) -> float:
    """非中文字符占比（韩文/日文假名/英文单词等），用于发现语言混杂的幻觉行。"""
    if not text:
        return 0.0
    _cn = _punct = _foreign = 0
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            _cn += 1
        elif ch in "，。！？、：；“”‘’（）《》…—·":
            _punct += 1
        elif ch.isascii() and (ch.isspace() or ch in ".,!?'\"-:;"):
            _punct += 1
        else:
            _foreign += 1
    total = _cn + _punct + _foreign
    return (_foreign / total) if total else 0.0


def _filter_hallucination(segs, nsp_th: float = 0.6, cr_th: float = 2.4):
    """把疑似幻觉的识别段剔掉。返回 (保留列表, 丢弃明细列表)。

    [P0 2026-10-24] 为什么需要：whisper 在低信噪比/量化(CPU int8)下会**凭空生成句子**。
    实测同一段视频：GPU(float16) 首行是「没事我有大血包」(真实)，CPU(int8) 首行变成
    「而且卡不了星标」——用户人耳复核确认根本没说过。认不全只是少内容，编造则是脏数据，
    性质完全不同，所以给一个可选的强过滤。

    判据沿用既有诊断口径（no_speech_prob 高 = 模型自己觉得没人说话；
    压缩比高 = 重复循环型幻觉），两个阈值都可配。
    """
    kept: list = []
    dropped: list = []
    for s in segs or []:
        text = (getattr(s, "text", "") or "").strip()
        if not text:
            continue
        nsp = float(getattr(s, "no_speech_prob", 0.0) or 0.0)
        cr = float(getattr(s, "compression_ratio", 0.0) or 0.0)
        if nsp >= nsp_th or cr >= cr_th:
            dropped.append((text, nsp, cr))
        else:
            kept.append(s)
    return kept, dropped


# [2026-10-25] 引擎名 → 模型目录名。放在模块级是为了：
#   1. 报错信息和实际查找路径用同一份数据（原来内联三元表达式，两处容易改漏）
#   2. 测试能直接断言这张表，新增引擎漏改会被测出来
# 注意目录名不是「引擎名 + 后缀」：qwen3 -> qwen3-asr、firered -> firered-asr
_SHERPA_ENGINE_DIRS = {
    "sensevoice": "sensevoice-small",
    "paraformer": "paraformer-zh",
    "qwen3": "qwen3-asr",
    "firered": "firered-asr",
}


def asr_segments(wav: str, language: Optional[str], progress_callback: Optional[Callable] = None,
                 glossary: Optional[list] = None,
                 engine: Optional[str] = None) -> list[dict]:
    # [2026-10-25] 引擎分流：sensevoice / paraformer / qwen3 / firered 走 sherpa-onnx。
    # 它们都返回 [{"start","end","text"}]，下游（幻觉过滤/regroup/词表/SRT）完全复用，
    # 因此这里直接返回、不重复写一套后处理 —— 但**词表纠错仍要在外层跑**（见调用点）。
    #
    # [2026-10-25] 新增 engine 参数：**逐任务**覆盖全局配置。
    # 为什么需要：不同素材适合不同引擎（实测同一段游戏解说，
    # SenseVoice 4.1s / Qwen3 23.0s；粤语和英语说唱则 Qwen3 明显更准）。
    # 如果只能全局改，用户每换一种素材就得回设置页改一次再重启任务，
    # 批量处理混合素材时更是不可能。
    # 传 None 时行为与改动前完全一致（读全局配置）。
    _engine = (engine or getattr(_cfg.asr, "engine", "whisper") or "whisper").strip().lower()
    _SHERPA_ENGINES = _SHERPA_ENGINE_DIRS
    if _engine in _SHERPA_ENGINES:
        from src.asr_sherpa import transcribe as _sherpa_transcribe, models_available
        _ready = models_available()
        _sub = _SHERPA_ENGINES[_engine]
        if not _ready.get(_engine):
            raise RuntimeError(
                "ASR 引擎=%s 但模型未安装（%s）。请把模型文件放到 models/sherpa/%s/ 下。"
                % (_engine, os.path.join(MODEL_DIR, "sherpa", _sub), _sub)
            )
        if not _ready.get("vad"):
            raise RuntimeError("Silero VAD 模型缺失（models/sherpa/silero_vad.onnx），sherpa 引擎必需")
        _rows = _sherpa_transcribe(wav, _engine, progress_callback)
        if glossary and _rows:
            try:
                from src.glossary import apply_glossary
                _auto = _sus = 0
                for _r in apply_glossary(_rows, glossary):
                    for _h in (_r.get("corrections") or []):
                        if _h.get("kind") == "auto":
                            _auto += 1
                        else:
                            _sus += 1
                if _auto or _sus:
                    log("  [词表/sherpa] 同音自动纠正 %d 处；疑似 %d 处（只标记，不改）" % (_auto, _sus))
            except Exception as _e:  # noqa: BLE001
                log("  [词表/sherpa] 纠错失败（忽略）: %r" % (_e,))
        return _rows

    from faster_whisper import WhisperModel

    t0 = time.time()
    if not os.path.isdir(MODEL_DIR):
        raise RuntimeError("未找到本地模型目录 %s" % MODEL_DIR)

    # 走 config 自动检测设备（auto → CTranslate2 支持 CUDA + 显存充足才用 cuda）
    device, compute_type = _cfg.get_asr_device()

    # [P0 2026-10-24] 设备必须可见：此前设备是静默判定的，用户只会看到「这次 8 秒、下次 51 秒」，
    # 更糟的是 **float16(GPU) 与 int8(CPU) 在 CTranslate2 上的识别结果本来就不同** ——
    # 同一视频两次跑出完全不同的字幕（实测 46 行 vs 41 行，内容几乎无重叠），
    # 用户会判定软件不可靠，且缓存 key 基于文本 → 每次切设备缓存全失效，改进也无法验收。
    log("[ASR] 设备=%s 精度=%s" % (device, compute_type))
    if device == "cpu" and (_cfg.asr.device or "auto").lower() == "auto":
        _d = _cfg.describe_asr_device()
        _free = _d.get("free_vram_gb")
        if _d.get("ct2_cuda_supported") and _d.get("cuda_dll_dirs") \
                and _free is not None and _free < 4.0:
            log("[ASR][注意] 显存不足（空闲 %.1f GB < 4 GB），已回落到 CPU 推理（约慢 5~10 倍）。" % _free)
            log("[ASR][注意] 常见原因：本地 LLM（koboldcpp 等）正占用显存；8GB 显卡放不下「本地LLM+GPU识别」。")
            log("[ASR][注意] 换云端翻译模式可释放显存让识别走 GPU；若要保持结果一致，可固定 SUBAI_ASR_DEVICE=cpu。")
        log("[ASR][注意] GPU(float16) 与 CPU(int8) 的识别结果本就不同：切换设备会让同一视频出现不同字幕。")

    if device == "cuda":
        # CTranslate2 通过 LoadLibrary 加载 cuBLAS/cuDNN，需先把 DLL 目录加入搜索路径
        ensure_cuda_dll_path()
    model = WhisperModel(MODEL_DIR, device=device, compute_type=compute_type,
                         cpu_threads=_cfg.asr.cpu_threads)
    t_load = time.time() - t0

    t0 = time.time()
    # 五期修复：faster-whisper 对中文常输出繁体。language 未指定时先用 12 秒音频探测语言，
    # 确认是中文才带 initial_prompt 全量转写（不给非中文音频塞中文提示，避免污染输出）。
    _lang = (language or "").strip().lower() or None
    if _lang is None:
        try:
            _probe, _pinfo = model.transcribe(wav, language=None, beam_size=1,
                                              vad_filter=False, clip_timestamps="0,12")
            list(_probe)
            _lang = (_pinfo.language or "").strip().lower() or None
            log("[ASR] 语言探测: %s" % _lang)
        except Exception as _e:  # noqa: BLE001
            log("[ASR] 语言探测失败（忽略，按原逻辑继续）: %r" % (_e,))
    _prompt = "以下是普通话的句子，请用简体中文转写。" if (_lang or "").startswith("zh") else None
    if _prompt:
        log("[ASR] 检测到中文：用 initial_prompt 引导简体输出")
    # condition_on_previous_text=False：否则模型会把 initial_prompt 当成"前文"续写出来，
    # 实测出现过整段字幕变成「请使用简体中文」这类 prompt 残留（真机复现）。
    segments, info = model.transcribe(wav, language=language, beam_size=5,
                                      vad_filter=True, word_timestamps=True,
                                      initial_prompt=_prompt,
                                      condition_on_previous_text=False)
    segs = list(segments)
    t_asr = time.time() - t0

    # 五期：ASR 诊断（**观察模式**）—— 只记录可疑段，**绝不删行**。
    # 理由：字符过滤/收紧阈值会把「听错字」变成「字幕缺行」，后者更难发现。
    # 先跑一轮拿数据（哪些段会被拦、为什么），由人决定是否启用拦截及阈值。
    _diag = []
    for _s in segs:
        _t = (getattr(_s, "text", "") or "").strip()
        if not _t:
            continue
        _nsp = float(getattr(_s, "no_speech_prob", 0.0) or 0.0)
        _cr = float(getattr(_s, "compression_ratio", 0.0) or 0.0)
        _fr = _foreign_ratio(_t)
        if _nsp >= 0.6 or _cr >= 2.4 or _fr >= 0.25:
            _diag.append((_t[:26], _nsp, _cr, _fr))
    if _diag:
        log("  [ASR 诊断·观察模式] %d/%d 段可疑（不删行，仅供调阈值参考）：" % (len(_diag), len(segs)))
        for _t, _nsp, _cr, _fr in _diag[:12]:
            log("     no_speech=%.2f 压缩比=%.2f 外语占比=%.0f%% | %s" % (_nsp, _cr, _fr * 100, _t))

    # [P0 2026-10-24] 可选强过滤：丢弃疑似幻觉段（默认关，丢弃明细必落日志）
    if getattr(_cfg.asr, "drop_hallucination", False):
        segs, _dropped = _filter_hallucination(
            segs,
            float(getattr(_cfg.asr, "hallucination_nsp", 0.6)),
            float(getattr(_cfg.asr, "hallucination_cr", 2.4)))
        if _dropped:
            log("[ASR] 已丢弃 %d 段疑似幻觉（宁可少一行，不凭空编一句）：" % len(_dropped))
            for _t, _nsp, _cr in _dropped[:10]:
                log("   丢弃 no_speech=%.2f 压缩比=%.2f | %s" % (_nsp, _cr, _t[:34]))
            if len(_dropped) > 10:
                log("   ……另有 %d 段" % (len(_dropped) - 10))

    rows = _regroup(segs)

    # 限制单行显示时长（见 MAX_DISPLAY_SEC 注释）：只截短，不延长，不动 words
    _trim = 0
    for _r in rows:
        _span = float(_r["end"]) - float(_r["start"])
        if _span > MAX_DISPLAY_SEC:
            _r["end"] = round(float(_r["start"]) + MAX_DISPLAY_SEC, 3)
            _trim += 1
    if _trim:
        log("  [ASR] %d 行超过 %.0f 秒，已截短显示时长（原音频该段持续更久，但只识别出这一句）"
            % (_trim, MAX_DISPLAY_SEC))

    # [2026-10-25] 最短显示时长护栏：太短的行延长到可读时长（不越过下一行起点）。
    # 顺序必须在「截短」之后：先保证不超上限，再保证不低于下限，两者不会互相打架
    # （截短只会让 end 变小，下限只会让它变大；若某行同时被两道护栏碰到，
    #  下限取 min(start+min_sec, 下一行 start)，而上限已把 end 压到 start+8s，
    #  因此只在 min_sec > 8s 的荒谬配置下才可能冲突，届时以「不越过下一行」为准。）
    try:
        _min_sec = float(getattr(_cfg, "min_display_sec", 1.0) or 0)
    except (TypeError, ValueError):
        _min_sec = 1.0
    rows, _min_fixed = _enforce_min_display(rows, _min_sec)
    if _min_fixed:
        log("  [ASR] %d 行显示不足 %.2f 秒，已延长（不越过下一行）" % (_min_fixed, _min_sec))

    # 说话人分离 [2026-10-25]
    # 放在 regroup/enforce_min_display **之后**：分离只给已定版的行贴标签，
    # 不参与切分。这样「关掉分离」和「开着分离」的字幕切分完全一致，
    # 用户不会因为开了个附加功能发现字幕排版变了。
    try:
        if getattr(_cfg, "diarize", False):
            from src import diarize as _dz
            if not _dz.available():
                log("  [分离] 模型未就绪，跳过（models/sherpa/diarization）")
            else:
                log("  [分离] 说话人分离中…")
                _diar = _dz.diarize(
                    wav,
                    num_speakers=int(getattr(_cfg, "diarize_speakers", -1) or -1),
                    threshold=float(getattr(_cfg, "diarize_threshold", 0.9) or 0.9),
                    progress_callback=progress_callback,
                )
                _st = _dz.assign_speakers(rows, _diar)
                stats["diarization"] = _st
                log("  [分离] %d 人，%d/%d 行已标注"
                    % (_st["speaker_count"], _st["labeled"], len(rows)))
    except Exception as _e:  # noqa: BLE001
        # 分离是附加功能，失败不能拖垮出字幕
        log("  [分离] 失败，已跳过：%s" % _e)

    # 兜底：个别情况下 initial_prompt 仍会被复述成一行字幕，直接丢弃这种残留
    if _prompt:
        _leak = ("简体中文", "普通话", "转写")
        _before = len(rows)
        rows = [r for r in rows if not any(k in (r.get("text") or "") for k in _leak)]
        if len(rows) != _before:
            log("  [ASR] 已过滤 %d 行 prompt 残留" % (_before - len(rows)))

    # 五期 P2：用户词表同音纠正 —— **必须在摘要与缓存 key 之前**（改的是原文，
    # 否则双语字幕对不上、缓存会命中旧译文）。近音/冲突只标记不自动改。
    if glossary:
        try:
            from src.glossary import apply_glossary
            _auto = _sus = 0
            for _r in apply_glossary(rows, glossary):
                for _h in (_r.get("corrections") or []):
                    if _h.get("kind") == "auto":
                        _auto += 1
                    else:
                        _sus += 1
            if _auto or _sus:
                log("  [词表] 同音自动纠正 %d 处；疑似 %d 处（只标记，不改）" % (_auto, _sus))
                # 同一次运行内的「纠正前原文」快照：验收要靠它对账，不能跨轮次比
                log("  [词表] ASR 原文快照（纠正前，%d 行）：" % len(rows))
                for _r in rows[:60]:
                    log("     | %s" % ((_r.get("original_text") or "")[:40]))
                # 明细：必须能核对「疑似」到底是哪个词、有没有被真的改掉
                _shown = 0
                for _r in rows:
                    for _h in (_r.get("corrections") or []):
                        if _shown >= 10:
                            break
                        log("     [%s] %r -> %r（%s）"
                            % (_h.get("kind"), _h.get("original"), _h.get("corrected"),
                               _h.get("reason") or "-"))
                        _shown += 1
        except Exception as _e:  # noqa: BLE001
            log("  [词表] 纠正跳过: %r" % (_e,))

    # 五期：按启用的术语包纠正 ASR 错字（只改文本，不动时间轴）
    try:
        from src.term_packs import apply_fixes
        _fixed = 0
        for _r in rows:
            _t = _r.get("text") or ""
            _new, _ap = apply_fixes(_t)
            if _ap:
                _r["text"] = _new
                _fixed += len(_ap)
        if _fixed:
            log("  [ASR] 术语包纠正识别错字 %d 处" % _fixed)
    except Exception as _e:  # noqa: BLE001
        log("  [ASR] 术语包纠错跳过: %s" % _e)
    log("  [ASR] 模型加载 %.2fs / 推理 %.2fs / 语言=%s(%.2f) / 段落 %d -> 字幕行 %d"
        % (t_load, t_asr, info.language, info.language_probability, len(segs), len(rows)))

    # 五期：语音覆盖率。原实现只写日志；[2026-10-25] 抽成 compute_coverage() 以便
    # 上层拿到结构化数据（任务卡片要显示「漏识别多少秒、几处空洞」）。
    try:
        _cov = compute_coverage(rows, float(getattr(info, "duration", 0) or 0))
        if _cov:
            log("  [ASR 覆盖] 音频 %.1fs / 字幕覆盖 %.1fs（%.0f%%）/ 留白 %.1fs / ≥%.1fs 空洞 %d 处"
                % (_cov["duration"], _cov["covered"], _cov["coverage_pct"],
                   _cov["blank"], _cov["gap_min_sec"], len(_cov["gaps"])))
    except Exception:  # noqa: BLE001
        pass
    
    if progress_callback:
        progress_callback(0.3, "ASR完成")
    
    return rows


# --------------------------------------------------------------------------- #
# 第2步（B）：硬字幕OCR
# --------------------------------------------------------------------------- #
def hardsub_segments(video: str, sample_fps: Optional[float] = None,
                     min_score: Optional[float] = None, gap_tol: Optional[float] = None,
                     progress_callback: Optional[Callable] = None) -> list[dict]:
    import cv2

    # 未显式传参时回退到 config.ocr 配置（支持环境变量覆盖）
    if sample_fps is None:
        sample_fps = _cfg.ocr.sample_fps
    if min_score is None:
        min_score = _cfg.ocr.min_score
    if gap_tol is None:
        gap_tol = _cfg.ocr.gap_tol

    t0 = time.time()
    # OCR 引擎由插件系统提供（内置 RapidOCR 插件包装的就是原实现）；
    # 插件被停用时抛 CapabilityDisabled 并给出可执行的提示。
    provider = ocr_provider()
    engine = provider.create_engine()
    log("  [OCR] 引擎加载 %.2fs" % (time.time() - t0))

    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise RuntimeError("无法打开视频：%s" % video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, int(round(fps / sample_fps)))

    t0 = time.time()
    frames = 0
    ocr_calls = 0
    raw: list[tuple[float, str]] = []
    idx = 0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    while True:
        ok = cap.grab()
        if not ok:
            break
        if idx % step == 0:
            ok, frame = cap.retrieve()
            if ok:
                frames += 1
                # 解析逻辑（含 [box, text, score] 的多版本兼容）由 provider 提供
                parts = provider.texts_from_frame(engine, frame, min_score)
                ocr_calls += 1
                if parts:
                    text = " ".join(parts).strip()
                    if text:
                        raw.append((idx / fps, _norm(text)))
        
        # 进度回调
        if progress_callback and total_frames > 0:
            progress = (idx / total_frames) * 0.3 + 0.3
            progress_callback(progress, f"OCR处理中 {idx}/{total_frames} 帧")
        
        idx += 1
    cap.release()
    t_ocr = time.time() - t0

    # 合并时间上相邻、文本相同的采样点
    rows: list[dict] = []
    for ts, text in raw:
        if rows and rows[-1]["text"] == text and ts - rows[-1]["end"] <= gap_tol:
            rows[-1]["end"] = ts
        else:
            rows.append({"start": ts, "end": ts, "text": text})
    for r in rows:
        r["end"] = max(r["end"], r["start"] + 0.5)

    log("  [OCR] 采样 %.0f 帧 / OCR %d 次 / 耗时 %.2fs(%.3fs 每帧) / 去重后字幕 %d 行"
        % (frames, ocr_calls, t_ocr, t_ocr / max(1, ocr_calls), len(rows)))
    
    if progress_callback:
        progress_callback(0.6, "OCR完成")
    
    return rows


def _norm(text: str) -> str:
    """去空格和常见标点，仅用于"同一句话"判定"""
    return re.sub(r"[\s，。！？!?,.;:；：、\-—_]+", "", text)


# --------------------------------------------------------------------------- #
# 第3步：翻译（集成术语库）
# --------------------------------------------------------------------------- #
#: 五期：累计 token 用量（云端模式烧的是钱，要能看见）
_TOKEN_USAGE = {"prompt": 0, "completion": 0}


def reset_token_usage() -> None:
    _TOKEN_USAGE["prompt"] = 0
    _TOKEN_USAGE["completion"] = 0


def get_token_usage() -> dict:
    return {"prompt": _TOKEN_USAGE["prompt"], "completion": _TOKEN_USAGE["completion"],
            "total": _TOKEN_USAGE["prompt"] + _TOKEN_USAGE["completion"]}


def _no_thinking_params(url: str, model: str) -> dict:
    """按服务商关掉「思考」，防止推理模型把额度烧在思考 token 上。

    只对**明确支持该参数**的端点发送，避免未知参数导致请求报错。
    """
    u = (url or "").lower()
    m = (model or "").lower()
    if any(k in u for k in ("siliconflow", "bigmodel", "dashscope", "aliyun", "modelscope")):
        return {"enable_thinking": False}
    if "openrouter" in u:
        return {"reasoning": {"enabled": False}}
    if m.startswith(("o1", "o3", "o4")):
        return {"reasoning_effort": "low"}
    return {}


def _adaptive_max_tokens(text: str) -> int:
    """按文本长度自适应上限：固定 256 会截断长句，也会给短句浪费额度。"""
    base = int(_cfg.llm.max_tokens)
    ceiling = max(base, 1024)
    return max(base, min(ceiling, 32 + len(text) * 3))


# 五期性能修复：全局复用 httpx.Client（连接池）。
# 实测：33 行单句翻译，httpx.post 每次新建连接 13.1s，连接池 2.2s（慢 6 倍）。
# 本地模型（单句模式）必须复用连接，否则速度不达标。
_HTTP_CLIENT = None


def _get_http_client():
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None:
        import httpx
        _HTTP_CLIENT = httpx.Client()
    return _HTTP_CLIENT


def _call_llm(text: str, target: str, timeout: float = None,  # type: ignore[assignment]
              url: Optional[str] = None, model: Optional[str] = None,
              api_key: Optional[str] = None,
              system_extra: Optional[str] = None) -> str:
    """
    翻译请求（带重试）。timeout 不传则使用 config.llm.timeout。

    url / model / api_key 不传则按 config.llm.mode 自动选 local/cloud 端点。
    - 本地模式：无需鉴权（api_key 为空）
    - 云端/混合模式：自动附加 Authorization: Bearer <api_key> 头
    """
    import httpx

    # 端点解析：显式传参优先，缺失项回退到 config.llm.mode 的端点配置
    if url is None or model is None or api_key is None:
        _url, _model, _key = _cfg.get_llm_endpoint()
        if url is None:
            url = _url
        if model is None:
            model = _model
        if api_key is None:
            api_key = _key

    if timeout is None:
        timeout = _cfg.llm.timeout

    # 端点缺失时给出明确提示，避免误把空地址发出去
    if not url:
        raise RuntimeError(
            "LLM 端点未配置：本地模式请设置 SUBAI_LLM_LOCAL_URL，"
            "云端/混合模式请设置 SUBAI_LLM_CLOUD_URL 与 SUBAI_LLM_CLOUD_API_KEY"
        )

    # 云端鉴权头（本地模式 api_key 为空，等价于无鉴权）
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = "Bearer %s" % api_key

    # 五期：raw completion 模式（StreamRevise 等「指令在 user」的模型）。
    # chat 端点会给这类模型套错模板，实测输出截断/未翻译；见 config.llm.raw_mode 注释。
    if _cfg.llm.raw_mode:
        _raw_url = (url or "").replace("/v1/chat/completions", "/v1/completions")
        # 必须用**语言全名**（English），不能用代码（en）：
        # 云端能理解 "into en"，本地 StreamRevise 不能 —— 实测传 en 时整句原样不翻译。
        _lang_name = target
        try:
            _lobj = languages_module.get(target)
            if _lobj is not None and getattr(_lobj, "name_en", None):
                _lang_name = _lobj.name_en
        except Exception:  # noqa: BLE001
            pass
        _instr = ("Translate the following Chinese subtitle line into %s. "
                  "Output only the translation, no numbering, no explanation." % _lang_name)
        if system_extra:
            _instr = _instr + "\n\n" + system_extra
        _prompt = ("<｜hy_begin▁of▁sentence｜><｜hy_User｜>"
                   + _instr + "\n\n" + text + "<｜hy_Assistant｜>")
        _rpayload = {"prompt": _prompt, "max_tokens": _adaptive_max_tokens(text),
                     "temperature": _cfg.llm.temperature, "stop": ["<｜hy_"]}

        def _do_raw():
            resp = _get_http_client().post(_raw_url, json=_rpayload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp

        try:
            r = retry(_do_raw, max_retries=_cfg.llm.max_retries,
                      base_delay=_cfg.llm.retry_delay,
                      retry_on=(httpx.HTTPError, ConnectionError, TimeoutError))
            return (r.json()["choices"][0].get("text") or "").strip()
        except RetryExhausted as e:
            raise RuntimeError(f"翻译请求失败（重试 {_cfg.llm.max_retries} 次后仍失败）: {e.last_exception}")
        except Exception as e:
            raise RuntimeError(f"翻译请求失败: {e}")

    # 五期：system_extra（摘要/术语块）放进 **system**，让固定前缀只预填充一次。
    # 实测：把它拼进 user 会让每行多 300-400 字符 prefill，单句模式下慢 8 倍
    # （0.489s/行 vs 0.058s/行）。system 固定时 llama.cpp/koboldcpp 可复用前缀缓存。
    _sys = ("You are a professional subtitle translator. Translate the user's "
            "subtitle into %s. Output only the translation, no explanation, "
            "no quotes, keep it short." % target)
    if system_extra:
        _sys = _sys + "\n\n" + system_extra
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _sys},
            {"role": "user", "content": text},
        ],
        "max_tokens": _adaptive_max_tokens(text),
        "temperature": _cfg.llm.temperature,
    }
    # 五期：关思考（推理模型的思考 token 也计费，翻译场景完全不需要）
    payload.update(_no_thinking_params(url, model or ""))

    def _do_post():
        # raise_for_status 必须放在**重试内部**：
        # httpx.post 对 5xx 不会抛异常,若在重试之外 raise,retry() 根本看不到服务端错误,
        # "5xx 可重试"就形同虚设;4xx 则由 non_retryable_http_status 立即失败。
        resp = _get_http_client().post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp

    try:
        r = retry(
            _do_post,
            max_retries=_cfg.llm.max_retries,
            base_delay=_cfg.llm.retry_delay,
            retry_on=(httpx.HTTPError, ConnectionError, TimeoutError),
        )
        data = r.json()
        try:
            usage = data.get("usage") or {}
            _TOKEN_USAGE["prompt"] += int(usage.get("prompt_tokens") or 0)
            _TOKEN_USAGE["completion"] += int(usage.get("completion_tokens") or 0)
        except Exception:  # noqa: BLE001
            pass
        return data["choices"][0]["message"]["content"].strip()
    except RetryExhausted as e:
        raise RuntimeError(f"翻译请求失败（重试 {_cfg.llm.max_retries} 次后仍失败）: {e.last_exception}")
    except Exception as e:
        raise RuntimeError(f"翻译请求失败: {e}")


def _protect_terms(text: str, terms: dict[str, str]) -> tuple[str, dict[str, str]]:
    """把句中出现命中的术语替换为占位符（**长词优先**），返回 (受保护文本, 占位符->译文)。

    为什么要占位符:术语往往是句子的一部分（如"人工智能"出现在
    "欢迎使用人工智能视频字幕翻译软件"里），既要让译名固定,又不能丢掉上下文,
    因此先替换成 [[T0]] 这类记号、翻译后再还原。
    """
    mapping: dict[str, str] = {}
    out = text
    n = 0
    for src in sorted(terms.keys(), key=len, reverse=True):
        if src and src in out:
            ph = "[[T%d]]" % n
            n += 1
            out = out.replace(src, ph)
            mapping[ph] = terms[src]
    return out, mapping


def _glossary_hint(hit: dict[str, str]) -> str:
    """软提示模式下的术语要求片段（长词优先，避免短词先出现造成歧义）。"""
    if not hit:
        return ""
    items = "; ".join("%s = %s" % (k, v) for k, v in sorted(hit.items(), key=lambda kv: -len(kv[0])))
    return "\nRequired terminology (you MUST use these exact translations): " + items


def _restore_terms(text: str, mapping: dict[str, str]) -> str:
    """把译文中保留下来的占位符还原为术语译文。"""
    out = text
    for ph, tgt in mapping.items():
        out = out.replace(ph, tgt)
    return out


# --------------------------------------------------------------------------- #
# 五期 P0：翻译前视频语境摘要
#   问题：现在每批 10 行、无上下文地送 LLM，跨行的代词/称呼/专有名词译名不稳。
#   做法：ASR 完成后先花一次调用生成结构化摘要，注入后续每批 prompt；
#        摘要内容参与翻译缓存 key（hash 变了旧缓存自然失效）。
#   铁律：摘要只是增强，任何失败都必须静默降级，绝不能影响翻译本身。
# --------------------------------------------------------------------------- #
def _sample_text(text: str, limit: int) -> str:
    """长文本采样：首 50% + 尾 20% + 中间均匀 5 段（长视频也能覆盖头尾与中段）。"""
    if len(text) <= limit:
        return text
    head_len = int(limit * 0.5)
    tail_len = int(limit * 0.2)
    head = text[:head_len]
    tail = text[-tail_len:] if tail_len > 0 else ""
    body = text[head_len:len(text) - tail_len] if tail_len > 0 else text[head_len:]
    mid_budget = limit - len(head) - len(tail)
    chunks = []
    if body and mid_budget > 0:
        # 预算必须严格可控：每段 = 中间预算 / 5（不设下限，否则 5 段会超预算）
        seg = max(1, mid_budget // 5)
        step = max(1, len(body) // 5)
        for i in range(5):
            piece = body[i * step: i * step + seg].strip()
            if piece:
                chunks.append(piece)
    parts = [head] + chunks + ([tail] if tail else [])
    return "\n…\n".join(parts)


def _parse_context_json(raw: str) -> Optional[dict]:
    """从 LLM 输出里抠出 JSON；容忍代码块包裹和前后废话。"""
    t = (raw or "").strip()
    t = re.sub(r"^\x60{3}(?:json)?\s*", "", t, flags=re.S)
    t = re.sub(r"\s*\x60{3}$", "", t, flags=re.S)
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        data = json.loads(t[i:j + 1])
    except Exception:  # noqa: BLE001
        return None
    return data if isinstance(data, dict) else None


def build_video_context(texts: list[str], target: str) -> Optional[dict]:
    """生成视频语境摘要；返回 dict（含 key）或 None（降级）。"""
    if not _cfg.llm.context_enabled or not texts:
        return None
    body = "\n".join(t.strip() for t in texts if t and str(t).strip())
    # 太短的视频没有摘要价值，省一次调用（行数为主；字数下限放到 100，
    # 否则 1~2 分钟的短视频（约 20 行/280 字）会被误跳过）
    if len(texts) < 5 or len(body) < 100:
        log("  [摘要] 视频太短（%d 行 / %d 字），跳过摘要" % (len(texts), len(body)))
        return None
    sample = _sample_text(body, max(500, int(_cfg.llm.context_max_chars)))
    prompt = (
        "下面是一段视频字幕全文（长视频已做头尾+中段采样，用 … 分隔）。"
        "请只输出一个 JSON 对象，不要代码块、不要解释：\n"
        '{"content_type": "内容类型（游戏解说/影视剧/教程/访谈/新闻...）",'
        ' "tone": "语气（口语激情/平静叙述/幽默玩梗...）",'
        ' "speakers": ["出现的角色或称呼"],'
        ' "terms": [{"src": "原文专有名词", "suggested": "建议的目标语译名", "type": "person|game|term"}]}\n'
        "terms 只收**专有名词**：人名/主播名、游戏名、角色名、技能名、道具名、网络梗，最多 20 条。\n"
        "**不要收通用名词**（局长、队长、老师、老板、兄弟这类普通称谓或日常词），"
        "除非它明确是游戏角色名。type 取值：person=人名、game=游戏/角色、term=其他专名。\n"
        "没有就给空数组。\n\n" + sample
    )
    try:
        raw = _call_llm(prompt, target)
    except Exception as e:  # noqa: BLE001
        log("  [摘要] 生成失败，降级为无摘要：%r" % (e,))
        return None
    data = _parse_context_json(raw)
    if not data:
        log("  [摘要] 返回内容无法解析为 JSON，降级为无摘要")
        return None
    out = {
        "content_type": str(data.get("content_type") or "")[:60],
        "tone": str(data.get("tone") or "")[:60],
        "speakers": [str(x)[:40] for x in (data.get("speakers") or []) if str(x).strip()][:10],
        "terms": [],
    }
    _dropped = 0
    for item in (data.get("terms") or []):
        if isinstance(item, dict) and item.get("src") and _looks_like_common_noun(str(item["src"])):
            _dropped += 1
            continue
        if isinstance(item, dict) and item.get("src"):
            out["terms"].append({"src": str(item["src"])[:40],
                                 "suggested": str(item.get("suggested") or "")[:40],
                                 "type": str(item.get("type") or "term")[:16]})
    out["terms"] = out["terms"][:20]
    if _dropped:
        log("  [摘要] 已丢弃 %d 个通用称谓词（不当术语注入）" % _dropped)
    if not any([out["content_type"], out["tone"], out["speakers"], out["terms"]]):
        log("  [摘要] 模型未给出有效信息，降级为无摘要")
        return None
    out["key"] = hashlib.sha1(
        json.dumps(out, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    log("  [摘要] %s / %s / 角色 %d / 专有名词 %d（key=%s）"
        % (out["content_type"] or "-", out["tone"] or "-",
           len(out["speakers"]), len(out["terms"]), out["key"]))
    return out


def _cache_key_of(context: Optional[dict], glossary_key: str = "") -> str:
    """翻译缓存 key = 摘要hash + 词表hash。

    词表必须进 key：同一句原文，填了词表（纠正后文本不同）与没填词表，
    译文应当不同；若不进 key，会静默命中旧缓存，表现为「填了词表却没效果」。
    """
    return "%s|%s" % (str((context or {}).get("key") or ""), glossary_key or "")


def _context_prompt_block(context: Optional[dict]) -> str:
    """把摘要转成注入 prompt 的文本块；无摘要返回空串。"""
    if not context:
        return ""
    parts = []
    if context.get("content_type"):
        parts.append("内容类型：%s" % context["content_type"])
    if context.get("tone"):
        parts.append("语气：%s" % context["tone"])
    if context.get("speakers"):
        parts.append("角色/称呼：%s" % "、".join(context["speakers"]))
    terms = context.get("terms") or []
    persons = [t for t in terms if (t.get("type") or "") == "person"]
    others = [t for t in terms if (t.get("type") or "") != "person"]
    if persons:
        # 人名默认音译：意译会把「橘长」变成「Director」这类错误被固化
        parts.append("人名（必须音译成拼音/原名，不要意译）：%s" % "、".join(
            str(t.get("src")) for t in persons))
    if others:
        parts.append("专有名词（必须按此译名）：%s" % "；".join(
            ("%s→%s" % (t["src"], t["suggested"])) if t.get("suggested") else t["src"]
            for t in others))
    if not parts:
        return ""
    return "[视频背景] " + " | ".join(parts) + "\n\n"

def translate(
    texts: list[str],
    target: str,
    terms: dict[str, str],
    batch_size: int = 10,
    progress_callback: Optional[Callable] = None,
    use_cache: bool = True,
    stats: Optional[dict] = None,
    should_cancel: Optional[Callable] = None,
    term_mode: Optional[str] = None,
    context: Optional[dict] = None,
    glossary_key: str = "",
) -> list[str]:
    """
    逐批复用一次请求翻译多行（编号协议），解析失败自动退回逐行翻译。

    术语处理（v3.1.6 改进）：
    - 整行恰好等于术语 → 直接采用术语译文，不送 LLM；
    - 术语出现在句中 → 先替换为 [[T#]] 占位符再送 LLM，译文回来后还原，
      既固定专有名词译名，又不破坏上下文（此前只支持整行精确匹配，
      导致真实字幕里的术语几乎永远不命中）。
    - 命中术语的行**不读也不写缓存**：其译文取决于术语库，术语一旦修改，
      缓存必须失效，因此直接跳过以保证正确性。

    容错：单行翻译失败不抛异常，留空并计入 stats["failed"]。

    stats（出参）: total / terms / cache_hits / llm_requests / failed
    """
    t0 = time.time()
    out: list[str] = [""] * len(texts)
    todo: list[int] = []

    # 目标语言校验（四期 4.4）：不在支持清单里**只提示不阻断**，
    # 因为用户可能写自定义名称（例如 "Japanese (anime)"），强行拦下反而碍事。
    if target and languages_module.get(target) is None:
        log("  [语言] 目标语言 %r 不在支持清单中，将按原样交给模型" % target)

    if stats is not None:
        stats.update({"total": len(texts), "terms": 0, "cache_hits": 0, "llm_requests": 0, "failed": 0})

    # 五期：语境摘要参与缓存 key —— 摘要变了，本视频的旧译文就不再命中
    ctx_key = _cache_key_of(context, glossary_key)
    ctx_block = _context_prompt_block(context)

    # 整行精确命中：直接用术语译文
    exact_hits = 0
    for i, t in enumerate(texts):
        if t in terms:
            out[i] = terms[t]
            exact_hits += 1
        else:
            todo.append(i)

    # 句中命中：按模式处理
    #   strict —— 占位符替换，译名强制一致；
    #   hint   —— 不改写原文，只把命中的术语作为"必须使用"的要求随提示词交给模型。
    mode = (term_mode or _cfg.term.mode or "strict").strip().lower()
    if mode not in ("strict", "hint"):
        mode = "strict"

    protected: dict[int, tuple[str, dict]] = {}
    applied: dict[int, dict] = {}
    term_lines: set = set()
    for i in todo:
        hit = {src: terms[src] for src in terms if src and src in texts[i]}
        applied[i] = hit
        if mode == "strict":
            protected[i] = _protect_terms(texts[i], hit)
        else:
            protected[i] = (texts[i], {})
        if hit:
            term_lines.add(i)

    if stats is not None:
        stats["terms"] = exact_hits + len(term_lines)

    cache_hits = 0
    todo_after_cache: list[int] = []
    cache_obj: Optional[TranslationCache] = None
    cache_loop: Optional[asyncio.AbstractEventLoop] = None

    # 术语命中的行跳过缓存（见 docstring）
    cacheable = [i for i in todo if i not in term_lines]

    if use_cache and cacheable:
        try:
            cache_loop = asyncio.new_event_loop()
            cache_obj = TranslationCache(
                _cfg.cache_db_path,
                max_entries=_cfg.cache.max_entries,
                ttl_days=_cfg.cache.ttl_days,
            )
            cache_loop.run_until_complete(cache_obj.initialize())
        except Exception as e:
            log("  [缓存] 初始化失败，本次跳过缓存: %r" % e)
            cache_obj = None
            if cache_loop is not None:
                cache_loop.close()
                cache_loop = None

    try:
        if cache_obj is not None and cache_loop is not None:
            for i in todo:
                if i in term_lines:
                    todo_after_cache.append(i)
                    continue
                cached = None
                try:
                    cached = cache_loop.run_until_complete(cache_obj.get(texts[i], target, ctx_key))
                except Exception as e:
                    log("  [缓存] 查询失败: %r" % e)
                    cached = None
                if cached:
                    out[i] = cached
                    cache_hits += 1
                else:
                    todo_after_cache.append(i)
        else:
            todo_after_cache = list(todo)
        if stats is not None:
            stats["cache_hits"] = cache_hits

        n_batch = 0
        failed = 0
        total_batches = (len(todo_after_cache) + batch_size - 1) // batch_size if todo_after_cache else 0
        current_batch = 0

        def _translate_one(i: int) -> None:
            """单行翻译（含术语占位符保护）；失败不抛异常，只记录并留空。"""
            nonlocal n_batch, failed
            ptext, mapping = protected[i]
            if mapping == {} and applied.get(i):
                ptext = ptext + _glossary_hint(applied[i])
            try:
                out[i] = _restore_terms(
                    _call_llm(ptext, target, system_extra=ctx_block), mapping)
                n_batch += 1
            except Exception as e:  # noqa: BLE001
                out[i] = ""
                failed += 1
                log("  [翻译] 第 %d 行失败：%r" % (i + 1, e))

        # 五期：单句模式（batch_size=1）直接走 _translate_one。
        # 若先走批量编号格式再回退，会白跑一次请求（实测 66 次 = 33 行 × 2），
        # 且 raw 端点收到编号格式会输出未翻译行。
        if batch_size == 1 and todo_after_cache:
            for _i in todo_after_cache:
                raise_if_cancelled(should_cancel)
                _translate_one(_i)
            total_batches = len(todo_after_cache)
            if cache_obj is not None and cache_loop is not None:
                for _i in todo_after_cache:
                    if _i in term_lines:
                        continue
                    if out[_i] and not out[_i].startswith("[翻译失败"):
                        try:
                            cache_loop.run_until_complete(
                                cache_obj.set(texts[_i], target, out[_i], ctx_key))
                        except Exception as _e:  # noqa: BLE001
                            log("  [缓存] 写入失败: %r" % _e)
            todo_after_cache = []

        # [2026-10-25] 翻译专用引擎（DeepL / Google）：走它们自己的批量接口。
        #
        # 为什么不能复用 LLM 路径：
        # 1. 它们不接受 prompt。整个「Translate each numbered line...」的指令
        #    会被当成正文翻译掉 —— 实测会得到一串翻译过的提示词。
        # 2. 它们的接口本身按数组返回，与输入行序一一对应，
        #    比 LLM 的「编号对齐」可靠得多（LLM 会漏编号、合并行）。
        # 3. 它们不产生幻觉，所以术语占位符保护也不需要 —— 但为保持
        #    「术语命中」统计一致，仍然走 protected/restore 那一套。
        _proto = (getattr(_cfg.llm, "protocol", "openai") or "openai").strip().lower()

        # [2026-10-25] 免费免 Key 渠道（腾讯交互翻译）。
        # 与 DeepL/Google 同一条处理路径，但它不需要 Key ——
        # 这是「用户完全没有账号也能出片」的唯一入口。
        if _proto == "tencent_free" and todo_after_cache:
            log("  [翻译] 使用免费渠道：腾讯交互翻译（无需 Key，%d 行）"
                % len(todo_after_cache))
            _plain = [protected[i][0] for i in todo_after_cache]
            try:
                from src import translate_free as _tfree
                _tr = _tfree.translate_free(
                    "tencent_free", _plain, source_lang, target)
                # translate_free 内部已保证条数对齐，这里再断言一次：
                # 条数不等会让字幕与时间轴整体错位，比译不准严重得多。
                if len(_tr) != len(todo_after_cache):
                    raise RuntimeError("条数不符: %d vs %d"
                                       % (len(_tr), len(todo_after_cache)))
                for _n, _i in enumerate(todo_after_cache):
                    out[_i] = _restore_terms(_tr[_n], protected[_i][1])
                n_batch += len(todo_after_cache)
                if cache_obj is not None and cache_loop is not None:
                    for _i in todo_after_cache:
                        if _i in term_lines or not out.get(_i):
                            continue
                        try:
                            cache_loop.run_until_complete(
                                cache_obj.set(texts[_i], target, out[_i], ctx_key))
                        except Exception:  # noqa: BLE001
                            pass
                todo_after_cache = []
            except Exception as _e:  # noqa: BLE001
                log("  [翻译] 免费渠道失败（%r），回落到 LLM 逐行" % _e)

        if _proto in ("deepl", "google") and todo_after_cache:
            _engine_key = getattr(_cfg.llm, "engine_api_key", "") or ""
            _eng_name = {"deepl": "DeepL", "google": "Google 翻译"}[_proto]
            log("  [翻译] 使用翻译专用引擎：%s（%d 行，一次批量请求）"
                % (_eng_name, len(todo_after_cache)))
            _plain = [protected[i][0] for i in todo_after_cache]
            try:
                from src import translate_engines as _te
                _tr = _te.translate_batch(
                    _proto, _plain, source_lang, target,
                    api_key=_engine_key,
                    **({"tier": getattr(_cfg.llm, "deepl_tier", "free"),
                        "glossary_id": getattr(_cfg.llm, "deepl_glossary_id", "") or None}
                       if _proto == "deepl" else {}),
                )
                for _n, _i in enumerate(todo_after_cache):
                    out[_i] = _restore_terms(_tr[_n], protected[_i][1])
                n_batch += len(todo_after_cache)
                if cache_obj is not None and cache_loop is not None:
                    for _i in todo_after_cache:
                        if _i in term_lines or not out.get(_i):
                            continue
                        try:
                            cache_loop.run_until_complete(
                                cache_obj.set(texts[_i], target, out[_i], ctx_key))
                        except Exception:  # noqa: BLE001
                            pass
                todo_after_cache = []
            except Exception as _e:  # noqa: BLE001
                # 专用引擎失败：记录下来并回落到 LLM 路径，不让整批字空白
                log("  [翻译] %s 失败（%r），回落到 LLM 逐行" % (_eng_name, _e))

        for s in range(0, len(todo_after_cache), batch_size):
            # 协作式取消检查点：每个翻译批次前
            raise_if_cancelled(should_cancel)
            idxs = todo_after_cache[s:s + batch_size]

            block = "\n".join(
            "%d. %s" % (n + 1, protected[i][0]) for n, i in enumerate(idxs)
        )
            glossary: dict = {}
            for i in idxs:
                glossary.update(applied.get(i, {}))
            hint = _glossary_hint(glossary) if mode == "hint" else ""
            # 五期修复：目标是中文时明确要求简体（模型默认可能输出繁体）
            _script = ""
            try:
                _code = languages_module.normalize(target)
                if _code == "zh":
                    _script = " Use Simplified Chinese (简体中文)."
                elif _code == "zh-TW":
                    _script = " Use Traditional Chinese (繁體中文)."
            except Exception:  # noqa: BLE001
                pass
            prompt = ctx_block + ("Translate each numbered Chinese subtitle line into %s.%s "
                      "Keep the same numbering, one line per input line, output nothing else. "
                      "Keep any [[T#]] placeholder unchanged.%s\n\n%s" % (target, _script, hint, block))

            try:
                raw = _call_llm(prompt, target)
                n_batch += 1
                current_batch += 1

                got = {}
                for line in raw.splitlines():
                    m = re.match(r"^\s*(\d+)\s*[.、)]\s*(.+?)\s*$", line)
                    if m:
                        got[int(m.group(1))] = m.group(2).strip()

                if len(got) >= len(idxs):
                    for n, i in enumerate(idxs):
                        out[i] = _restore_terms(got.get(n + 1, ""), protected[i][1])
                else:
                    for i in idxs:
                        _translate_one(i)
            except Exception as e:
                log("  [翻译] 批量请求失败(%r)，退回逐行" % e)
                for i in idxs:
                    _translate_one(i)

            if cache_obj is not None and cache_loop is not None:
                for i in idxs:
                    if i in term_lines:
                        continue
                    if out[i] and not out[i].startswith("[翻译失败"):
                        try:
                            cache_loop.run_until_complete(cache_obj.set(texts[i], target, out[i], ctx_key))
                        except Exception as e:
                            log("  [缓存] 写入失败: %r" % e)

            if progress_callback and total_batches > 0:
                progress = 0.6 + (current_batch / total_batches) * 0.35
                progress_callback(progress, f"翻译中 {current_batch}/{total_batches} 批")

        if stats is not None:
            stats["llm_requests"] = n_batch
            stats["failed"] = failed

        dt = time.time() - t0
        log("  [翻译] %d 行 -> %s | 模式=%s | 请求 %d 次 / 耗时 %.2fs（术语命中 %d / 缓存命中 %d / 失败 %d 行）"
            % (len(texts), target, mode, n_batch, dt, int((stats or {}).get("terms", 0)), cache_hits, failed))

        if progress_callback:
            progress_callback(0.95, "翻译完成")

        return out
    finally:
        if cache_obj is not None and cache_loop is not None:
            try:
                cache_loop.run_until_complete(cache_obj.close())
            except Exception:
                pass
        if cache_loop is not None:
            cache_loop.close()



# --------------------------------------------------------------------------- #
# 第4步：落盘（多格式输出）
# --------------------------------------------------------------------------- #
def write_srt(rows: list[dict], path: str, texts: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for i, (row, text) in enumerate(zip(rows, texts), 1):
            f.write("%d\n%s --> %s\n%s\n\n"
                    % (i, fmt_ts(row["start"]), fmt_ts(row["end"]), text))
    log("  [输出] %s" % path)



    # 五期：把词级时间戳另存一份（SRT 存不下；确认页拆分功能依赖它）
    try:
        import json as _json
        with open(path + ".words.json", "w", encoding="utf-8") as _f:
            _json.dump(
                [{"start": r.get("start"), "end": r.get("end"), "words": r.get("words") or []} for r in rows],
                _f, ensure_ascii=False)
    except Exception as _e:  # noqa: BLE001
        print("  [words] 写入失败: %s" % _e)
def write_vtt(rows: list[dict], path: str, texts: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for i, (row, text) in enumerate(zip(rows, texts), 1):
            f.write("%s --> %s\n%s\n\n"
                    % (fmt_ts(row["start"]).replace(",", "."),
                       fmt_ts(row["end"]).replace(",", "."),
                       text))
    log("  [输出] %s" % path)


def write_ass(rows: list[dict], path: str, texts: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("[Script Info]\n")
        f.write("Title: SubAI Translator\n")
        f.write("ScriptType: v4.00+\n\n")
        f.write("[Events]\n")
        f.write("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n\n")
        
        for i, (row, text) in enumerate(zip(rows, texts), 1):
            start = fmt_ts(row["start"]).replace(",", ".")
            end = fmt_ts(row["end"]).replace(",", ".")
            f.write("Dialogue: 0,%s,%s,Default,,0,0,0,,%s\n" % (start, end, text))
    
    log("  [输出] %s" % path)


def write_json(rows: list[dict], path: str, texts: list[str], translated: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = []
    for i, (row, src, dst) in enumerate(zip(rows, texts, translated), 1):
        data.append({
            "id": i,
            "start": row["start"],
            "end": row["end"],
            "start_ts": fmt_ts(row["start"]),
            "end_ts": fmt_ts(row["end"]),
            "source": src,
            "translation": dst
        })
    
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log("  [输出] %s" % path)


# --------------------------------------------------------------------------- #
# 主函数
# --------------------------------------------------------------------------- #
#: 五期：「不翻译，只识别」的目标语言写法
NO_TRANSLATE_TARGETS = ("none", "original", "source", "off", "no")


def is_no_translate(target_lang: str) -> bool:
    """目标语言是不是「不翻译、保留原文」。界面上的第 2 个入口就靠它。"""
    return str(target_lang or "").strip().lower() in NO_TRANSLATE_TARGETS


def load_glossary_from_db() -> list[dict]:
    """从词表库读取全部词条（CLI 路径兜底）。

    [P1 2026-10-24] 起因：`run_pipeline` 的 `glossary` 只有 API 路径会传（server 从 DB 读），
    命令行 `python -m src.pipeline` 一直是 `None` → **用户在界面里加的词表，用 CLI 跑完全不生效**。
    实测：词表里加「血包」后，GUI 能把 ASR 的「雪包」纠正回来，CLI 跑同一段视频仍输出 snow bag。
    这里做同步读取（不走 aiosqlite，避免与 pipeline 内部逻辑抢事件循环）。
    """
    import json as _json
    import sqlite3 as _sqlite3
    try:
        _db = _cfg.paths.resolve("{root}/data/glossary.db")
    except Exception:  # noqa: BLE001
        return []
    if not os.path.isfile(_db):
        return []
    out: list[dict] = []
    try:
        _con = _sqlite3.connect(_db)
        try:
            for (terms,) in _con.execute("SELECT terms FROM glossary_series"):
                try:
                    out.extend(_json.loads(terms or "[]"))
                except Exception:  # noqa: BLE001
                    continue
        finally:
            _con.close()
    except Exception:  # noqa: BLE001
        return []
    return out


def run_pipeline(
    video: str,
    mode: str = "asr",
    source_lang: Optional[str] = None,
    target_lang: str = "en",
    glossary: Optional[list] = None,
    terms_file: Optional[str] = None,
    db_path: Optional[str] = None,
    output_format: str = "srt",
    sample_fps: Optional[float] = None,
    progress_callback: Optional[Callable] = None,
    stats: Optional[dict] = None,
    should_cancel: Optional[Callable] = None,
    from_srt: Optional[str] = None,
    asr_engine: Optional[str] = None,
) -> list[str]:
    """
    完整Pipeline（视频 -> 字幕 -> 翻译 -> 输出）
    
    Args:
        video: 视频文件路径
        mode: asr 或 hardsub
        source_lang: 源语言（None=自动检测）
        target_lang: 目标语言
        terms_file: 术语库JSON文件
        db_path: 术语库SQLite数据库路径
        output_format: 输出格式（srt/vtt/ass/json）
        sample_fps: hardsub模式采样帧率
        progress_callback: 进度回调函数 callback(progress: float, message: str)
    
    Returns:
        list[str]: 输出的文件路径列表
    """
    t_all = time.time()
    stem = os.path.splitext(os.path.basename(video))[0]
    output_files = []

    # CLI 兜底：没显式传词表时，从词表库读（否则命令行跑的同音纠正永远不生效）
    if glossary is None:
        glossary = load_glossary_from_db()
        if glossary:
            log("[词表] 从词表库载入 %d 条（CLI 兜底）" % len(glossary))
    
    log("=" * 72)
    log("SubAI Translator Pipeline: %s mode=%s target=%s" % (video, mode, target_lang))
    log("=" * 72)
    
    # 加载术语库
    terms = {}
    if terms_file and os.path.isfile(terms_file):
        with open(terms_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 支持两种格式：dict或list
            if isinstance(data, list):
                terms = {t["source"]: t["translation"] for t in data if "source" in t and "translation" in t}
            else:
                terms = {str(k): str(v) for k, v in data.items()}
        log("[术语库] 从JSON加载 %d 条术语" % len(terms))
    elif db_path:
        tm = TerminologyManager(db_path)
        term_list = tm.list_terms()
        terms = {t["source"]: t["translation"] for t in term_list}
        log("[术语库] 从SQLite加载 %d 条术语" % len(terms))
    else:
        log("[术语库] 未加载术语库（使用纯AI翻译）")
    
    if progress_callback:
        progress_callback(0.05, "术语库加载完成")
    
    # 协作式取消检查点：开始重活之前
    raise_if_cancelled(should_cancel)

    # 第2步：字幕提取
    log("[2/4] 字幕提取 ...")
    if from_srt:
        # [P0 2026-10-24] 两段式拆分：只翻译，跳过识别。
        # 动机：本地隐私流程被迫吃 CPU int8（koboldcpp 占显存 → 空闲 <4GB → 回落 CPU），
        # 结果又慢(51s/100s音频)又和 GPU(float16) 不一致。拆成两段后：
        #   阶段1 用 GPU 跑识别（快 10 倍、结果稳定）→ 阶段2 再起 koboldcpp 做翻译（隐私不出门）。
        log("[2/4] 跳过识别，读取已有字幕：%s" % from_srt)
        # [2026-10-25] 从「只认 SRT」扩到 srt/vtt/ass/lrc 四种。
        # 原来固定走 src.subtitles.parse_srt，用户拿 .vtt 或 .ass 进来会解析出 0 行
        # 然后报「未提取到任何字幕」，实际是格式没识别。现在按扩展名+内容自动判格式。
        from src import subtitle_formats as _sf
        _fmt_in = _sf.detect_format(from_srt)
        rows = _sf.read_file(from_srt)
        rows = [r for r in rows if (r.get("text") or "").strip()]
        log("  读到 %d 行字幕（格式=%s，时间轴沿用原文件）" % (len(rows), _fmt_in))
        # [P1 2026-10-24] 词表纠错原本挂在 asr_segments 内部，跳过识别后就完全走不到 ——
        # 于是两段式的第二段（只翻译）词表形同虚设：实测「甲球/1414/牛转」一个都没纠正。
        # 这里补上，保证「纠错 → 摘要 → 翻译」的顺序与直连路径一致。
        if glossary:
            from src.glossary import apply_glossary as _apply_glossary
            _rows_fixed = _apply_glossary(rows, glossary)
            _auto = _sus = 0
            for _r in _rows_fixed:
                for _h in (_r.get("corrections") or []):
                    if _h.get("kind") == "auto":
                        _auto += 1
                    else:
                        _sus += 1
            if _auto or _sus:
                log("  [词表] 自动纠正 %d 处；疑似 %d 处（只标记，不改）" % (_auto, _sus))
            rows = _rows_fixed
    elif mode == "asr":
        wav = extract_audio(video)
        # [2026-10-25] asr_engine：逐任务指定引擎，None 时用全局配置
        rows = asr_segments(wav, source_lang, progress_callback, glossary=glossary,
                            engine=asr_engine)
    else:
        rows = hardsub_segments(video, sample_fps=sample_fps, progress_callback=progress_callback)
    
    if not rows:
        log("未提取到任何字幕，结束。")
        if not from_srt and mode == "asr":
            # 实测：游戏录像里有大量「有音轨但纯音效」的片段（如 19 秒的纯跑图片段），
            # 静默返回 0 行会让用户以为程序坏了，必须说清是「没有语音」而不是「识别失败」。
            log("  [说明] 未检测到语音内容。该片段可能只有游戏音效、没有人声；")
            log("         若确认有人说话，可尝试调低 VAD 阈值或改用 --source zh 指定语言。")
        return []
    
    # 协作式取消检查点：识别完成后
    raise_if_cancelled(should_cancel)

    # 第3步：翻译（五期：支持「不翻译，只识别」——直接输出原文）
    texts = [r["text"] for r in rows]
    no_translate = is_no_translate(target_lang)
    if no_translate:
        log("[3/4] 跳过翻译（按选择只做识别，输出原文）")
        translated = list(texts)
        target_lang = "source"        # 产物命名沿用 <stem>.source.srt
        if stats is not None:
            stats["total"] = len(texts)   # 让统计里也有行数（不是 0）
    else:
        log("[3/4] 翻译 ...")
        # 五期 P0：翻译前生成语境摘要（失败自动降级，不影响翻译）
        _video_ctx = build_video_context(texts, target_lang)
        if stats is not None:
            stats["context"] = _video_ctx or {}     # 供 API 写进任务记录（确认页可见）
        _glossary_hash = ""
        if glossary:
            try:
                _glossary_hash = hashlib.sha1(
                    json.dumps(glossary, ensure_ascii=False, sort_keys=True).encode("utf-8")
                ).hexdigest()[:12]
            except Exception:  # noqa: BLE001
                _glossary_hash = ""
        translated = translate(texts, target_lang, terms, progress_callback=progress_callback,
                               stats=stats, should_cancel=should_cancel, context=_video_ctx,
                               glossary_key=_glossary_hash,
                               # 让 SUBAI_LLM_BATCH_SIZE 生效：本地单句模型设 1 走快路径，
                               # 否则默认批量 10 行（编号协议）对单句直译模型既慢又可能返回空
                               batch_size=_cfg.llm.batch_size)
    
    # 协作式取消检查点：写盘前（取消则不留半成品）
    raise_if_cancelled(should_cancel)

    # 第4步：落盘
    log("[4/4] 写出字幕 ...")
    out_dir = OUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    
    if output_format == "srt":
        write_srt(rows, os.path.join(out_dir, "%s.%s.srt" % (stem, target_lang)), translated)
        output_files.append(os.path.join(out_dir, "%s.%s.srt" % (stem, target_lang)))
        if not no_translate:
            write_srt(rows, os.path.join(out_dir, "%s.bilingual.srt" % stem),
                      ["%s\n%s" % (a, b) for a, b in zip(texts, translated)])
            output_files.append(os.path.join(out_dir, "%s.bilingual.srt" % stem))
    
    elif output_format == "vtt":
        write_vtt(rows, os.path.join(out_dir, "%s.%s.vtt" % (stem, target_lang)), translated)
        output_files.append(os.path.join(out_dir, "%s.%s.vtt" % (stem, target_lang)))
        if not no_translate:
            write_vtt(rows, os.path.join(out_dir, "%s.bilingual.vtt" % stem),
                      ["%s\n%s" % (a, b) for a, b in zip(texts, translated)])
            output_files.append(os.path.join(out_dir, "%s.bilingual.vtt" % stem))
    
    elif output_format == "ass":
        write_ass(rows, os.path.join(out_dir, "%s.%s.ass" % (stem, target_lang)), translated)
        output_files.append(os.path.join(out_dir, "%s.%s.ass" % (stem, target_lang)))
        if not no_translate:
            write_ass(rows, os.path.join(out_dir, "%s.bilingual.ass" % stem),
                      ["%s\n%s" % (a, b) for a, b in zip(texts, translated)])
            output_files.append(os.path.join(out_dir, "%s.bilingual.ass" % stem))
    
    elif output_format in ("lrc", "txt"):
        # [2026-10-25] 新增 lrc / txt 导出（对齐同类项目的格式覆盖）。
        # lrc 只有起始时间（点歌词用），txt 无时间轴（纯文本分发用）。
        from src import subtitle_formats as _sf
        _ext = _sf.extension_for(output_format)
        _p = os.path.join(out_dir, "%s.%s%s" % (stem, target_lang, _ext))
        _sf.write_file(rows, _p, output_format, translated)
        output_files.append(_p)
        log("  [输出] %s" % _p)
        if not no_translate:
            _bp = os.path.join(out_dir, "%s.bilingual%s" % (stem, _ext))
            _sf.write_file(rows, _bp, output_format,
                           ["%s / %s" % (a, b) for a, b in zip(texts, translated)])
            output_files.append(_bp)
            log("  [输出] %s" % _bp)

    elif output_format == "json":
        write_json(rows, os.path.join(out_dir, "%s.%s.json" % (stem, target_lang)), texts, translated)
        output_files.append(os.path.join(out_dir, "%s.%s.json" % (stem, target_lang)))

    # 五期：ASR 原文快照**落盘**（纠正前的文本）。
    # 只写日志不行——日志会轮转/重跑就没了，而验收必须能按文件对齐
    # 「原始 ASR 文本 / 纠正日志 / 最终字幕」，且不能跨轮次比较（ASR 非确定性）。
    if glossary and any(r.get("original_text") for r in rows):
        _raw_rows = [{"start": r["start"], "end": r["end"],
                      "text": r.get("original_text") or r.get("text") or ""} for r in rows]
        _raw_path = os.path.join(out_dir, "%s.asr-raw.srt" % stem)
        write_srt(_raw_rows, _raw_path, [x["text"] for x in _raw_rows])
        output_files.append(_raw_path)
        log("  [词表] ASR 原始文本快照已落盘：%s（纠正前，供人工核对）" % _raw_path)

    # 翻译有失败行时，额外输出原文转录，保证识别结果不丢失
    failed = int((stats or {}).get("failed", 0) or 0)
    if failed:
        src_path = os.path.join(out_dir, "%s.source.srt" % stem)
        write_srt(rows, src_path, texts)
        output_files.append(src_path)
        log("  [警告] %d/%d 行翻译失败，已额外输出原文转录：%s" % (failed, len(texts), src_path))
    
    log("-" * 72)
    for i, (row, src, dst) in enumerate(zip(rows, texts, translated), 1):
        log("%2d  %s --> %s\n    %s\n    %s"
            % (i, fmt_ts(row["start"]), fmt_ts(row["end"]), src, dst))
    log("-" * 72)
    log("完成：%d 行字幕，总耗时 %.1fs" % (len(rows), time.time() - t_all))

    # [2026-10-25] 覆盖率写进 stats，供 API 任务详情展示「未覆盖多少秒、几处空洞」。
    # 数据在 ASR 阶段已算过（见 compute_coverage 调用点），这里重算一次成本可忽略，
    # 好处是无论走 asr 还是 hardsub、走不走 from_srt，stats 里都有一致的字段。
    try:
        _dur_all = probe_duration(video)
        if _dur_all <= 0:
            # ffprobe 不可用时用最后一行的 end 兜底（偏保守：会低估空白）
            _dur_all = float(rows[-1]["end"]) if rows else 0.0
        _cov_final = compute_coverage(rows, _dur_all)
        if _cov_final:
            stats["coverage"] = _cov_final
            if _cov_final.get("warn"):
                log("  [ASR 覆盖][提示] 覆盖率仅 %.0f%%，有 %d 处 ≥%.1f 秒未覆盖区间"
                    % (_cov_final["coverage_pct"], len(_cov_final["gaps"]), _cov_final["gap_min_sec"]))
    except Exception:  # noqa: BLE001
        pass

    if progress_callback:
        progress_callback(1.0, "全部完成")

    return output_files


def main() -> int:
    ap = argparse.ArgumentParser(description="SubAI Translator 一期完整版")
    ap.add_argument("video", help="输入视频文件（或目录）")
    ap.add_argument("--mode", choices=["asr", "hardsub"], default="asr")
    ap.add_argument("--source", default=None, help="源语言，如zh；默认自动检测")
    ap.add_argument("--target", default="en", help="目标语言，默认en")
    ap.add_argument("--terms", default=None, help="术语库JSON文件")
    ap.add_argument("--db", default=None, help="术语库SQLite数据库路径")
    ap.add_argument("--output-format", default="srt",
                    choices=["srt", "vtt", "ass", "json", "lrc", "txt"],
                    help="输出格式，默认srt（lrc 只有起始时间；txt 无时间轴）")
    ap.add_argument("--sample-fps", type=float, default=2.0, help="hardsub模式采样帧率")
    ap.add_argument("--batch", action="store_true", help="批处理模式（处理目录下所有视频）")
    ap.add_argument("--translate-only", metavar="SRT", default=None,
                    help="只翻译：读取已有字幕（如 <名称>.source.srt），跳过识别。"
                    "用于「先用 GPU 识别、再起本地 LLM 翻译」的两段式本地隐私流程")
    args = ap.parse_args()
    
    # 批处理模式
    if args.batch and os.path.isdir(args.video):
        video_files = [
            str(f) for f in Path(args.video).iterdir()
            if f.suffix.lower() in [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"]
        ]
        log("批处理模式：找到 %d 个视频文件" % len(video_files))
        
        for video in video_files:
            try:
                run_pipeline(
                    video=video,
                    mode=args.mode,
                    source_lang=args.source,
                    target_lang=args.target,
                    terms_file=args.terms,
                    db_path=args.db,
                    output_format=args.output_format,
                    sample_fps=args.sample_fps
                )
            except Exception as e:
                log("处理 %s 失败: %s" % (video, e))
        
        return 0
    
    # 单文件模式
    if not os.path.isfile(args.video):
        log("输入文件不存在：%s" % args.video)
        return 2
    
    _cli_stats: dict = {}
    try:
        run_pipeline(
            video=args.video,
            mode=args.mode,
            source_lang=args.source,
            target_lang=args.target,
            terms_file=args.terms,
            db_path=args.db,
            output_format=args.output_format,
            sample_fps=args.sample_fps,
            from_srt=args.translate_only,
            # [P1 2026-10-24] CLI 一直没传 stats → 日志里「术语命中」永远显示 0，
            # 明明术语生效了也看不出来（实测 dig in/medkit 已替换，日志却报 0 命中）。
            stats=_cli_stats,
        )
        if _cli_stats.get("terms"):
            log("  [统计] 术语命中 %d 行 / 缓存命中 %d 行" % (
                int(_cli_stats.get("terms", 0)), int(_cli_stats.get("cache_hits", 0))))
        return 0
    except Exception as e:
        log("Pipeline失败: %s" % e)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())