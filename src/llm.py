# -*- coding: utf-8 -*-
"""
SubAI Translator —— 翻译后端状态探测（联调）
=============================================

回答"当前 AI 调用模式到底是什么、是否真的可用"：
- 当前模式（local / cloud / hybrid）与有效端点（不含密钥，仅返回是否存在）
- 本地端点是否可达（探测 OpenAI 兼容的 /v1/models）
- 云端是否已配置 URL 与 API Key，可选取时探测可达性

被 /api/llm/status 与 /api/llm/mode 复用。
"""
from __future__ import annotations

import time
from typing import Optional

import httpx

from src.config import config

_PROBE_TIMEOUT = 4.0


def _models_url(chat_url: str) -> str:
    """由 OpenAI 兼容的 chat 端点推导出 models 端点，用于轻量探测。"""
    url = (chat_url or "").strip().rstrip("/")
    suffix = "/chat/completions"
    if url.endswith(suffix):
        return url[: -len(suffix)] + "/models"
    if url:
        return url + "/models"
    return ""


# [2026-10-25] HTTP 状态码 -> 语义。
#
# 原来的判据是 reachable = status_code < 500，这意味 401/403/404 全算「可达」。
# 后果很难受：用户填了一个**完全无效的 key**，页面显示「端点可达」，
# 直到真正跑翻译才报错 —— 而那时已经浪费时间了。
# 这两者是不同的问题，必须分开报：
#   端点能不能连上（网络层）  vs  这个 key 在这台服务上能不能用（认证层）
_STATUS_MEANING = {
    200: ("ok", "正常"),
    400: ("bad_request", "请求被拒绝（模型名或参数不对）"),
    401: ("auth_failed", "密钥无效或已过期"),
    402: ("no_balance", "账户余额不足"),
    403: ("forbidden", "无权限（密钥无该模型权限，或地区受限）"),
    404: ("not_found", "端点或模型不存在（地址可能已变更）"),
    429: ("rate_limited", "请求过于频繁或被限流"),
    # [2026-10-25] 410 Gone：服务方明确声明该接口/模型已停止提供。
    # 实测 01.AI（yi）的 /v1/models 返回 410 + model_service_closed，
    # 而我们仍把它列在 provider 列表里 —— 用户填 key 也永远不会成功。
    410: ("discontinued", "该服务或模型已被官方停止提供（需更换服务商）"),
}


def _classify(status_code: int) -> tuple:
    """把 HTTP 状态码归类成 (code, 中文说明)，未知码给保守判断。"""
    if status_code in _STATUS_MEANING:
        return _STATUS_MEANING[status_code]
    if 200 <= status_code < 300:
        return ("ok", "正常")
    if 500 <= status_code:
        return ("server_error", "服务端错误（非密钥问题）")
    return ("unexpected", "未预期的状态码 %d" % status_code)


def probe(url: str, api_key: str = "", timeout: float = _PROBE_TIMEOUT) -> dict:
    """探测端点**与密钥**的可用性。

    返回 configured / reachable / authorized / verdict / detail / probe_url。

    [2026-10-25] 语义变更（重要）：
    - reachable：服务器有没有应答（网络层）。5xx 仍算 reachable=False，因为它没法干活。
    - authorized：这个 key 在这台服务上**能不能用**。401/402/403 判 False。
    - verdict：ok / auth_failed / not_found / rate_limited / ... 供 UI 直接显示。

    为什么不能用「< 500」当通过：401 说明 key 是废的，403 说明没有该模型权限，
    404 说明地址或模型名已经过期。这三种情况用户**必须**被明确告知，
    否则「显示正常、一跑就错」比直接报错更消耗信任。
    """
    if not url:
        return {"configured": False, "reachable": False, "authorized": False,
                "verdict": "not_configured", "detail": "未配置端点", "probe_url": ""}

    headers = {"Authorization": "Bearer " + api_key} if api_key else {}
    probe_url = _models_url(url)
    try:
        r = httpx.get(probe_url, headers=headers, timeout=timeout)
        verdict, meaning = _classify(r.status_code)
        # 5xx 是服务端故障：网络通但用不了
        reachable = r.status_code < 500
        authorized = verdict in ("ok", "rate_limited")
        return {
            "configured": True,
            "reachable": reachable,
            "authorized": authorized,
            "verdict": verdict,
            "http_status": r.status_code,
            "detail": "HTTP %d（%s）" % (r.status_code, meaning),
            "probe_url": probe_url,
        }
    except Exception as e:  # noqa: BLE001
        return {
            "configured": True,
            "reachable": False,
            "authorized": False,
            "verdict": "network_error",
            "detail": "%s: %s" % (type(e).__name__, str(e)[:120]),
            "probe_url": probe_url,
        }


def status(probe_cloud: bool = False) -> dict:
    """汇总当前翻译模式与可用性（绝不返回密钥明文）。"""
    url, model, key = config.get_llm_endpoint()
    local = probe(config.llm.local_url, "")

    has_cloud_key = bool(config.llm.cloud_api_key)
    cloud: dict = {
        "url": config.llm.cloud_url,
        "model": config.llm.cloud_model,
        "configured": bool(config.llm.cloud_url and has_cloud_key),
        "has_key": has_cloud_key,
        "reachable": None,
    }
    if probe_cloud and has_cloud_key and config.llm.cloud_url:
        cloud["reachable"] = probe(config.llm.cloud_url, config.llm.cloud_api_key)["reachable"]

    # [2026-10-25] 翻译专用引擎状态（DeepL / Google）。
    # 它们不走 OpenAI 协议，所以「有没有 base_url」不能用来判断可用性，
    # 只看有没有 Key。用户在设置页能看到「现在实际用的是哪个引擎」，
    # 避免出现「选了 DeepL 但没填 Key，实际还在走 LLM」这种错觉。
    _proto = (getattr(config.llm, "protocol", "openai") or "openai").strip().lower()
    _eng_key = bool(getattr(config.llm, "engine_api_key", ""))
    dedicated = {
        "protocol": _proto,
        "is_dedicated": _proto in ("deepl", "google"),
        "has_key": _eng_key,
        "configured": _eng_key if _proto in ("deepl", "google") else False,
    }
    if _proto == "deepl":
        dedicated["tier"] = getattr(config.llm, "deepl_tier", "free")
        dedicated["endpoint"] = ("https://api-free.deepl.com/v2/translate"
                                 if dedicated["tier"] == "free"
                                 else "https://api.deepl.com/v2/translate")
        dedicated["glossary_id"] = getattr(config.llm, "deepl_glossary_id", "")
        dedicated["name"] = "DeepL"
    elif _proto == "google":
        dedicated["endpoint"] = "https://translation.googleapis.com/language/translate/v2"
        dedicated["name"] = "Google 翻译"

    return {
        "mode": config.llm.mode,
        "modes": ["local", "cloud", "hybrid"],
        "effective": {"url": url, "model": model, "has_key": bool(key)},
        "local": {
            "url": config.llm.local_url,
            "model": config.llm.local_model,
            "reachable": local["reachable"],
            "detail": local["detail"],
        },
        "cloud": cloud,
        "dedicated": dedicated,
    }


def _try_models(url: str, api_key: str, timeout: float) -> dict:
    probe_url = _models_url(url)
    headers = {"Authorization": "Bearer " + api_key} if api_key else {}
    try:
        r = httpx.get(probe_url, headers=headers, timeout=timeout)
        return {"ok": r.status_code < 400, "status": r.status_code, "detail": "HTTP %d" % r.status_code}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "status": None, "detail": "%s: %s" % (type(e).__name__, str(e)[:140])}


def _try_chat(url: str, model: str, api_key: str, timeout: float) -> dict:
    headers = {"Authorization": "Bearer " + api_key} if api_key else {}
    payload = {
        "model": model or "test",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    try:
        r = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        return {"ok": r.status_code < 400, "status": r.status_code, "detail": "HTTP %d" % r.status_code}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "status": None, "detail": "%s: %s" % (type(e).__name__, str(e)[:140])}


def test_endpoint(mode: Optional[str] = None, timeout: float = 6.0, chat_fallback: bool = True) -> dict:
    """对当前配置的翻译端点做**真实**连通性测试（只读，不修改任何配置）。

    依次尝试 OpenAI 兼容的 /v1/models，再回退到一次 max_tokens=1 的 chat 请求，
    以便区分"服务没起来"与"服务起来了但 /models 不支持"。

    Returns:
        {mode, url, model, configured, reachable, method, http_status, detail, elapsed_ms}
    """
    m = (mode or config.llm.mode or "local").strip().lower()
    if m not in ("local", "cloud", "hybrid"):
        raise ValueError("mode 必须是 local / cloud / hybrid")

    if m == "local":
        url, model, key = config.llm.local_url, config.llm.local_model, ""
    else:
        url, model, key = config.llm.cloud_url, config.llm.cloud_model, config.llm.cloud_api_key

    if not url:
        return {"mode": m, "url": "", "model": model, "configured": False, "reachable": False,
                "method": None, "http_status": None, "detail": "该模式未配置端点地址", "elapsed_ms": 0}
    if m in ("cloud", "hybrid") and not key:
        return {"mode": m, "url": url, "model": model, "configured": False, "reachable": False,
                "method": None, "http_status": None, "detail": "云端模式未配置 API Key", "elapsed_ms": 0}

    t0 = time.perf_counter()
    first = _try_models(url, key, timeout)
    if first["ok"]:
        return {"mode": m, "url": url, "model": model, "configured": True, "reachable": True,
                "method": "models", "http_status": first["status"], "detail": first["detail"],
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}

    if chat_fallback:
        second = _try_chat(url, model, key, timeout)
        if second["ok"]:
            return {"mode": m, "url": url, "model": model, "configured": True, "reachable": True,
                    "method": "chat", "http_status": second["status"], "detail": second["detail"],
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}
        detail = "models: %s；chat: %s" % (first["detail"], second["detail"])
        status = second["status"]
    else:
        detail = "models: %s" % first["detail"]
        status = first["status"]

    return {"mode": m, "url": url, "model": model, "configured": True, "reachable": False,
            "method": None, "http_status": status, "detail": detail,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}
