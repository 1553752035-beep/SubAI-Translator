# -*- coding: utf-8 -*-
"""免费免密钥翻译渠道。

为什么需要
----------
此前所有翻译渠道都要用户自己去申请 API Key：注册 → 实名 → 充值 → 建 Key。
对一个只想把一段游戏视频加个中文字幕的人来说，这道门槛直接把工具挡在门外。
本模块提供**开箱即用**的免费渠道，用户填不了 Key 也能出片。

已实测的渠道（2026-10-25，本机直连）
--------------------------------------
| 渠道 | 端点 | 实测 | 结论 |
|---|---|---|---|
| 腾讯交互翻译 | transmart.qq.com/api/imt | 544ms，单/多条均正确 | **采用** |

实测后**未采用**的渠道及原因（不采用也要写清楚，避免后人重复踩）：

- `translate.googleapis.com` / `translate.google.com` / `clients5.google.com`
  → 本机三个域名全部 12~15 秒连接超时。不是代码问题，是网络不可达。
  代码留着也是死代码，不如不写。
- 有道 `dict.youdao.com/webtranslate`
  → 需要先取 key，再做 AES-128-CBC 解密 + md5 签名（SmartSub 用 610 行实现）。
  协议是网页端私有的、会随版本变化，维护成本极高。本机实测 key 接口返回
  `HTTP 500 {"code":1,"msg":"request error"}`，暂时拿不到。**不做半成品**。
- 百度 `fanyi.baidu.com/sug` → 只返回词典释义不是整句翻译，不适合字幕。

设计要点
--------
1. **条数必须对齐**：字幕行与时间轴一一对应，返回条数不等就整批失败，
   绝不错位填充（错位比译不准严重得多，且极难察觉）。
2. **空行原样返回**：字幕里常有空行/纯空格，送进去会干扰对齐，
   本地直接返回原串，不占请求。
3. **分批**：单请求有条数与长度上限，按保守值切批，避免超限整个失败。
4. **不假装成功**：任何异常都抛出，由上层决定回落，不返回空串充数。
"""
from __future__ import annotations

from typing import Optional

import httpx

# 腾讯交互翻译端点（网页端公开接口，无需账号）
TENCENT_ENDPOINT = "https://transmart.qq.com/api/imt"

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 实测上限：60 条 / 3000 字都正常。取保守值留余量。
MAX_LINES_PER_REQUEST = 40
MAX_CHARS_PER_REQUEST = 2500

# 语言代码映射：我们用 BCP-47（zh / zh-TW / en / ja），腾讯用短码
_LANG = {
    "zh": "zh", "zh-cn": "zh", "zh-hans": "zh",
    "zh-tw": "zh-TW", "zh-hant": "zh-TW",
    "en": "en", "ja": "ja", "ko": "ko", "fr": "fr", "de": "de",
    "es": "es", "ru": "ru", "pt": "pt", "it": "it", "tr": "tr",
    "vi": "vi", "th": "th", "ar": "ar", "id": "id", "ms": "ms",
}

FREE_ENGINES = {
    "tencent_free": {
        "name": "腾讯交互翻译（免费免 Key）",
        "endpoint": TENCENT_ENDPOINT,
        "needs_key": False,
    },
}


class FreeTranslateError(RuntimeError):
    """免费渠道失败。上层据此回落到付费渠道或 LLM。"""


def _norm_lang(code: str) -> str:
    """归一化语言代码；未知的返回原值小写（让服务端自己判）。"""
    return _LANG.get((code or "").strip().lower(), (code or "").strip().lower())


def build_tencent_request(texts: list, source: str, target: str) -> dict:
    """构造腾讯交互翻译请求体（纯函数，便于单测）。"""
    return {
        "header": {
            "fn": "auto_translation",
            # 网页端公开的客户端标识，不是任何人的账号凭据
            "client_key": "browser-firefox-110.0.0-Windows 10",
        },
        "type": "plain",
        "model_category": "normal",
        "source": {"lang": _norm_lang(source), "text_list": list(texts)},
        "target": {"lang": _norm_lang(target)},
    }


def parse_tencent_response(data: dict, expected: int) -> list:
    """解析腾讯返回。

    强制校验：返回条数必须等于输入条数。不等就抛错。
    理由见模块开头「条数必须对齐」—— 错位填充会把字幕和时间轴搅乱，
    而这种错误在成片里极难发现。
    """
    if not isinstance(data, dict):
        raise FreeTranslateError("响应不是 JSON 对象: %r" % (type(data),))

    header = data.get("header") or {}
    if header.get("ret_code") not in (None, "succ"):
        raise FreeTranslateError("服务返回失败: %s" % (header.get("ret_code"),))

    out = data.get("auto_translation")
    if out is None:
        # 有些失败形态不带 header，只在顶层给 message
        msg = data.get("message") or data.get("msg") or "(无说明)"
        raise FreeTranslateError("响应缺少 auto_translation: %s" % msg)
    if not isinstance(out, list):
        raise FreeTranslateError("auto_translation 不是数组: %r" % (type(out),))
    if len(out) != expected:
        raise FreeTranslateError(
            "返回条数不符：输入 %d 条，返回 %d 条（会破坏字幕与时间轴对齐）"
            % (expected, len(out)))
    return [("" if x is None else str(x)) for x in out]


def _chunk(texts: list) -> list:
    """按条数与总字数切批，返回 [(start, end), ...] 区间列表。"""
    spans = []
    start = 0
    while start < len(texts):
        chars = 0
        end = start
        while end < len(texts):
            n = len(texts[end])
            if end > start and (end - start >= MAX_LINES_PER_REQUEST
                                or chars + n > MAX_CHARS_PER_REQUEST):
                break
            chars += n
            end += 1
        if end == start:      # 单行超长，也要前进，不能死循环
            end = start + 1
        spans.append((start, end))
        start = end
    return spans


def tencent_translate_free(texts: list, source: str, target: str,
                           timeout: float = 20.0) -> list:
    """腾讯交互翻译（免 Key）。返回与输入等长的译文列表。

    空串/纯空白行本地原样返回，不发请求也不占配额。
    """
    texts = [("" if t is None else str(t)) for t in texts or []]
    if not texts:
        return []

    # 空行本地处理：送进去会挤占配额，也可能让服务端返回不同条数
    blank_idx = [i for i, t in enumerate(texts) if not t.strip()]
    work_idx = [i for i, t in enumerate(texts) if t.strip()]

    result = list(texts)      # 空行保持原样
    if not work_idx:
        return result

    work = [texts[i] for i in work_idx]
    translated = []

    headers = {"User-Agent": _UA, "Content-Type": "application/json"}
    with httpx.Client(timeout=timeout, headers=headers) as client:
        for a, b in _chunk(work):
            batch = work[a:b]
            payload = build_tencent_request(batch, source, target)
            try:
                r = client.post(TENCENT_ENDPOINT, json=payload)
            except Exception as e:  # noqa: BLE001
                raise FreeTranslateError("网络请求失败: %s: %s"
                                         % (type(e).__name__, str(e)[:120]))
            if r.status_code != 200:
                raise FreeTranslateError("HTTP %d: %s"
                                         % (r.status_code, (r.text or "")[:200]))
            try:
                data = r.json()
            except Exception as e:  # noqa: BLE001
                raise FreeTranslateError("响应不是合法 JSON: %s" % (e,))
            translated.extend(parse_tencent_response(data, len(batch)))

    for pos, idx in enumerate(work_idx):
        result[idx] = translated[pos]
    return result


def translate_free(engine: str, texts: list, source: str, target: str,
                   timeout: float = 20.0) -> list:
    """统一入口。目前只有腾讯一家，保留分发结构便于以后加。"""
    eng = (engine or "").strip().lower()
    if eng in ("tencent_free", "tencent", "qq"):
        return tencent_translate_free(texts, source, target, timeout=timeout)
    raise FreeTranslateError("未知的免费渠道: %s" % (engine,))