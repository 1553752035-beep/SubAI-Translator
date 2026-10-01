# -*- coding: utf-8 -*-
"""SubAI Translator 开放 API 的轻量 Python SDK。

设计取舍：**只依赖标准库**（urllib），因此可以在任何 Python 3.8+ 环境直接用，
不需要 `pip install httpx` 之类的额外依赖。

用法::

    from sdk.python.subai import SubAIClient

    client = SubAIClient("http://127.0.0.1:8000", api_key="subai_xxx")
    print(client.languages()["stats"])
    print(client.translate(["你好，世界"], "English"))
"""
from __future__ import annotations

import hashlib
import hmac
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

__all__ = ["SubAIClient", "SubAIError", "verify_webhook"]


class SubAIError(RuntimeError):
    """API 返回非 2xx，或网络不可达（此时 status=0）。"""

    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__("SubAI API error %s: %s" % (status, detail))


def verify_webhook(secret: str, body: bytes, signature: str) -> bool:
    """校验 Webhook 签名（HMAC-SHA256，constant-time 比较）。

    body 必须是**原始请求字节**，不是重新序列化后的 JSON。
    """
    if not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    got = signature.split("=", 1)[1] if signature.startswith("sha256=") else signature
    return hmac.compare_digest(expected, got)


class SubAIClient:
    """开放 API / 管理 API 客户端。

    - 第三方集成：传 `api_key`，走 `/api/open/v1/*`
    - 管理脚本：传 `token`（登录得到的 JWT），可调 `/api/openapi/*`
    """

    def __init__(self, base_url: str, api_key: Optional[str] = None,
                 token: Optional[str] = None, timeout: float = 60.0) -> None:
        self.base_url = (base_url or "").rstrip("/")
        if not self.base_url:
            raise ValueError("base_url 不能为空")
        self.api_key = api_key
        self.token = token
        self.timeout = timeout

    # ------------------------------------------------------------------ 内部
    def _request(self, method: str, path: str, payload: Optional[dict] = None,
                 params: Optional[dict] = None):
        url = self.base_url + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url += "?" + urllib.parse.urlencode(clean)
        headers = {"Accept": "application/json"}
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        if self.token:
            headers["Authorization"] = "Bearer %s" % self.token
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return json.loads(raw.decode("utf-8")) if raw else None
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                pass
            raise SubAIError(e.code, detail or str(e.reason))
        except urllib.error.URLError as e:
            raise SubAIError(0, "无法连接 %s: %s" % (self.base_url, e.reason))

        # 兼容网关返回非 JSON 的情况

    # ------------------------------------------------------------------ 开放 API
    def me(self) -> dict:
        """当前密钥信息与用量。"""
        return self._request("GET", "/api/open/v1/me")

    def languages(self) -> dict:
        """语言清单与能力矩阵。"""
        return self._request("GET", "/api/open/v1/languages")

    def translate(self, texts, target: str, terms: Optional[dict] = None,
                  use_cache: bool = True) -> dict:
        """翻译一组文本。"""
        return self._request("POST", "/api/open/v1/translate", {
            "texts": list(texts),
            "target": target,
            "terms": terms,
            "use_cache": use_cache,
        })

    def task(self, task_id: str) -> dict:
        """查询任务状态与产物。"""
        return self._request("GET", "/api/open/v1/tasks/%s" % urllib.parse.quote(str(task_id)))

    # ------------------------------------------------------------------ 管理 API
    def create_api_key(self, name: str, scopes=None) -> dict:
        """创建密钥；返回里含明文 secret（只出现这一次）。"""
        return self._request("POST", "/api/openapi/keys", {"name": name, "scopes": scopes})

    def list_api_keys(self) -> dict:
        return self._request("GET", "/api/openapi/keys")

    def revoke_api_key(self, key_id: str) -> dict:
        return self._request("DELETE", "/api/openapi/keys/%s" % urllib.parse.quote(str(key_id)))

    def create_webhook(self, url: str, events=None) -> dict:
        return self._request("POST", "/api/openapi/webhooks", {"url": url, "events": events})

    def test_webhook(self, webhook_id: str) -> dict:
        return self._request("POST", "/api/openapi/webhooks/%s/test" % urllib.parse.quote(str(webhook_id)))

    def webhook_deliveries(self, webhook_id: str, limit: int = 50) -> dict:
        return self._request("GET", "/api/openapi/webhooks/%s/deliveries" % urllib.parse.quote(str(webhook_id)),
                             params={"limit": limit})

    def stats(self) -> dict:
        return self._request("GET", "/api/openapi/stats")
