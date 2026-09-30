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


def probe(url: str, api_key: str = "", timeout: float = _PROBE_TIMEOUT) -> dict:
    """探测端点可达性。返回 configured/reachable/detail/probe_url。"""
    if not url:
        return {"configured": False, "reachable": False, "detail": "未配置端点", "probe_url": ""}

    headers = {"Authorization": "Bearer " + api_key} if api_key else {}
    probe_url = _models_url(url)
    try:
        r = httpx.get(probe_url, headers=headers, timeout=timeout)
        reachable = r.status_code < 500
        return {
            "configured": True,
            "reachable": reachable,
            "http_status": r.status_code,
            "detail": "HTTP %d" % r.status_code,
            "probe_url": probe_url,
        }
    except Exception as e:  # noqa: BLE001
        return {
            "configured": True,
            "reachable": False,
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
