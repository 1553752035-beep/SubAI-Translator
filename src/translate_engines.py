# -*- coding: utf-8 -*-
"""非 OpenAI 协议的翻译引擎适配层。

为什么单独写这一层
------------------
项目现有 25 个 provider 全部走 OpenAI 兼容协议，这对 LLM 是对的，
但**翻译专用服务不是这个协议**：

- **DeepL**：/v2/translate，一次多行、返回 translations[]。
  质量在多语言字幕上长期领先，且不会「自由发挥」改写原文。
- **Google Cloud Translation**：/language/translate/v2，支持术语表，
  便宜量大，适合先机翻再让 LLM 润色。

这三家的共同点：**不产生幻觉**（LLM 会漏句/改写/合并行），
代价是不能理解上下文。字幕场景里两者正好互补：
- 术语多、要一致 -> 专用翻译
- 要语气、要口语化 -> LLM

设计要点
--------
1. **统一接口** translate_batch(texts, src, tgt) -> list[str]。
   返回列表长度必须与输入一致，失败整批抛异常（不做静默截断 ——
   长度不一致会让字幕和时间轴错位，是最坏的失败方式）。
2. **批量优先**。DeepL/Google 都支持一次传多行，比逐行快一个量级，
   而且能保留行序（逐行拼接容易错序）。
3. **纯协议构造与解析可单测**：不发网络的函数单独拆出来。
"""
from __future__ import annotations

import html as _html
from typing import Optional

import httpx

# 各引擎的语言代码与项目内部代码不一致，必须显式映射
# 例：DeepL 用 PT-PT / ZH-HANS，Google 用 pt / zh-CN
_DEEPL_LANG = {
    "zh": "ZH-HANS", "zh-cn": "ZH-HANS", "zh-tw": "ZH-HANT",
    "en": "EN-US", "ja": "JA", "ko": "KO",
    "de": "DE", "fr": "FR", "es": "ES", "ru": "RU",
    "pt": "PT-PT", "it": "IT", "nl": "NL", "pl": "PL",
}
_GOOGLE_LANG = {
    "zh": "zh-CN", "zh-cn": "zh-CN", "zh-tw": "zh-TW",
    "en": "en", "ja": "ja", "ko": "ko",
    "de": "de", "fr": "fr", "es": "es", "ru": "ru",
    "pt": "pt", "it": "it", "nl": "nl", "pl": "pl",
}

DEEPL_ENDPOINTS = {
    "free": "https://api-free.deepl.com/v2/translate",
    "pro": "https://api.deepl.com/v2/translate",
}
GOOGLE_ENDPOINT = "https://translation.googleapis.com/language/translate/v2"


class TranslateError(RuntimeError):
    """翻译失败。消息里保留服务端返回，便于用户判断是 Key 错还是超限。"""


def _norm(code: str) -> str:
    return (code or "").strip().lower().replace("_", "-")


# --------------------------------------------------------------------------- #
# DeepL
# --------------------------------------------------------------------------- #
def build_deepl_request(texts: list, source: Optional[str], target: str,
                        api_key: str, tier: str = "free",
                        glossary_id: Optional[str] = None) -> dict:
    """构造 DeepL 请求（纯函数，可单测）。

    DeepL 的 target_lang 必填且必须是它认识的代码，传错会直接 400；
    unknown 代码时保留原值让服务端报错，比悄悄译成错误语言好 ——
    后者用户很难发现。
    """
    url = DEEPL_ENDPOINTS.get((tier or "free").lower(), DEEPL_ENDPOINTS["free"])
    tgt = _DEEPL_LANG.get(_norm(target), (target or "").upper())
    body = {
        "text": [str(t) for t in (texts or [])],
        "target_lang": tgt,
    }
    src = _norm(source or "")
    if src and src != "auto":
        body["source_lang"] = _DEEPL_LANG.get(src, src.upper())
    if glossary_id:
        body["glossary_id"] = glossary_id
    return {
        "url": url,
        "headers": {
            "Authorization": "DeepL-Auth-Key %s" % api_key,
            "Content-Type": "application/json",
        },
        "json": body,
    }


def parse_deepl_response(data: dict, expected: int) -> list:
    """解析 DeepL 响应。

    严格要求条数与输入一致：DeepL 理论上按序返回同样条数，
    但一旦不一致（比如某行是纯空白被服务端丢弃），
    继续用会让**字幕整体错位**，必须立刻报错。
    """
    tr = (data or {}).get("translations") or []
    out = [str(t.get("text", "")) for t in tr]
    if len(out) != expected:
        raise TranslateError(
            "DeepL 返回条数与输入不一致（输入 %d，返回 %d）。"
            "为避免字幕错位，已中止。请检查是否有空白行。" % (expected, len(out))
        )
    return out


def deepl_translate(texts: list, source: Optional[str], target: str,
                    api_key: str, tier: str = "free",
                    glossary_id: Optional[str] = None,
                    timeout: float = 60.0) -> list:
    if not api_key:
        raise TranslateError("DeepL 未配置 API Key")
    req = build_deepl_request(texts, source, target, api_key, tier, glossary_id)
    try:
        r = httpx.post(req["url"], headers=req["headers"], json=req["json"], timeout=timeout)
    except Exception as e:  # noqa: BLE001
        raise TranslateError("DeepL 请求失败：%s" % e)
    if r.status_code != 200:
        raise TranslateError("DeepL HTTP %d：%s" % (r.status_code, (r.text or "")[:300]))
    return parse_deepl_response(r.json(), len(texts or []))


# --------------------------------------------------------------------------- #
# Google Cloud Translation
# --------------------------------------------------------------------------- #
def build_google_request(texts: list, source: Optional[str], target: str,
                         api_key: str) -> dict:
    """构造 Google 请求。

    Google v2 用 q 参数可重复传多段；这里**用 JSON body 传数组**，
    比 URL 拼接安全 —— 字幕里常有 & 和 #，
    URL 编码稍有差池就会截断文本。
    """
    tgt = _GOOGLE_LANG.get(_norm(target), target or "en")
    body = {
        "q": [str(t) for t in (texts or [])],
        "target": tgt,
        "format": "text",
    }
    src = _norm(source or "")
    if src and src != "auto":
        body["source"] = _GOOGLE_LANG.get(src, src)
    return {
        "url": GOOGLE_ENDPOINT,
        "params": {"key": api_key},
        "json": body,
    }


def _unescape_html(s: str) -> str:
    return _html.unescape(s)


def parse_google_response(data: dict, expected: int) -> list:
    trs = (((data or {}).get("data") or {}).get("translations")) or []
    out = []
    for t in trs:
        s = str(t.get("translatedText", ""))
        # Google 会把单引号转成 &#39; 等 HTML 实体，字幕里必须还原
        out.append(_unescape_html(s))
    if len(out) != expected:
        raise TranslateError(
            "Google 返回条数与输入不一致（输入 %d，返回 %d），已中止以避免字幕错位。"
            % (expected, len(out))
        )
    return out


def google_translate(texts: list, source: Optional[str], target: str,
                     api_key: str, timeout: float = 60.0) -> list:
    if not api_key:
        raise TranslateError("Google 翻译未配置 API Key")
    req = build_google_request(texts, source, target, api_key)
    try:
        r = httpx.post(req["url"], params=req["params"], json=req["json"], timeout=timeout)
    except Exception as e:  # noqa: BLE001
        raise TranslateError("Google 翻译请求失败：%s" % e)
    if r.status_code != 200:
        raise TranslateError("Google HTTP %d：%s" % (r.status_code, (r.text or "")[:300]))
    return parse_google_response(r.json(), len(texts or []))


# --------------------------------------------------------------------------- #
# 统一入口
# --------------------------------------------------------------------------- #
ENGINES = {
    "deepl": {
        "name": "DeepL",
        "doc": "https://www.deepl.com/pro-api",
        "note": "翻译专用，不产生幻觉、不会改写原文；免费档 50 万字符/月",
        "needs_key": True,
    },
    "google": {
        "name": "Google Cloud Translation",
        "doc": "https://console.cloud.google.com/apis/credentials",
        "note": "便宜量大，支持术语表；适合先机翻再润色",
        "needs_key": True,
    },
}


def translate_batch(engine: str, texts: list, source: Optional[str], target: str,
                    api_key: str = "", **kwargs) -> list:
    """统一入口。texts 为空时直接返回空列表（不发请求）。"""
    if not texts:
        return []
    e = (engine or "").strip().lower()
    if e == "deepl":
        return deepl_translate(texts, source, target, api_key, **kwargs)
    if e == "google":
        return google_translate(texts, source, target, api_key, **kwargs)
    raise TranslateError("未知翻译引擎：%s（支持 %s）" % (engine, ", ".join(ENGINES)))