/**
 * SubAI Translator 开放 API 的轻量 JavaScript SDK（零依赖，Node 18+ 或浏览器）。
 *
 * 用法：
 *   import { SubAIClient, verifyWebhook } from "./subai.js";
 *   const client = new SubAIClient("http://127.0.0.1:8000", "subai_xxx");
 *   console.log((await client.translate(["你好，世界"], "English")).translations);
 */

export class SubAIError extends Error {
  constructor(status, detail) {
    super("SubAI API error " + status + ": " + detail);
    this.name = "SubAIError";
    this.status = status;
    this.detail = detail;
  }
}

export class SubAIClient {
  /**
   * @param {string} baseUrl 例如 http://127.0.0.1:8000
   * @param {string} [apiKey] 开放 API 密钥（第三方集成用）
   * @param {string} [token] 管理端 JWT（管理脚本用）
   */
  constructor(baseUrl, apiKey, token) {
    if (!baseUrl) throw new Error("baseUrl 不能为空");
    this.baseUrl = String(baseUrl).replace(/\/+$/, "");
    this.apiKey = apiKey;
    this.token = token;
  }

  async request(method, path, payload, params) {
    let url = this.baseUrl + path;
    if (params) {
      const qs = new URLSearchParams(
        Object.entries(params).filter(([, v]) => v !== undefined && v !== null),
      ).toString();
      if (qs) url += "?" + qs;
    }
    const headers = { Accept: "application/json" };
    const init = { method, headers };
    if (payload !== undefined && payload !== null) {
      headers["Content-Type"] = "application/json; charset=utf-8";
      init.body = JSON.stringify(payload);
    }
    if (this.apiKey) headers["X-API-Key"] = this.apiKey;
    if (this.token) headers.Authorization = "Bearer " + this.token;

    let resp;
    try {
      resp = await fetch(url, init);
    } catch (e) {
      throw new SubAIError(0, "无法连接 " + this.baseUrl + ": " + e);
    }
    const text = await resp.text();
    if (!resp.ok) throw new SubAIError(resp.status, text || resp.statusText);
    return text ? JSON.parse(text) : null;
  }

  // ---- 开放 API ----
  me() { return this.request("GET", "/api/open/v1/me"); }
  languages() { return this.request("GET", "/api/open/v1/languages"); }
  translate(texts, target, terms, useCache = true) {
    return this.request("POST", "/api/open/v1/translate", {
      texts: Array.from(texts), target, terms: terms || null, use_cache: useCache,
    });
  }
  task(taskId) { return this.request("GET", "/api/open/v1/tasks/" + encodeURIComponent(taskId)); }

  // ---- 管理 API ----
  createApiKey(name, scopes) { return this.request("POST", "/api/openapi/keys", { name, scopes }); }
  listApiKeys() { return this.request("GET", "/api/openapi/keys"); }
  revokeApiKey(keyId) { return this.request("DELETE", "/api/openapi/keys/" + encodeURIComponent(keyId)); }
  createWebhook(url, events) { return this.request("POST", "/api/openapi/webhooks", { url, events }); }
  testWebhook(id) { return this.request("POST", "/api/openapi/webhooks/" + encodeURIComponent(id) + "/test"); }
  webhookDeliveries(id, limit = 50) {
    return this.request("GET", "/api/openapi/webhooks/" + encodeURIComponent(id) + "/deliveries", null, { limit });
  }
  stats() { return this.request("GET", "/api/openapi/stats"); }
}

/**
 * 校验 Webhook 签名（HMAC-SHA256）。
 * body 必须是**原始请求体字符串/字节**，不要用重新序列化的 JSON。
 * @param {string} secret
 * @param {string} body
 * @param {string} signature 形如 sha256=<hex> 或直接 <hex>
 * @returns {Promise<boolean>}
 */
export async function verifyWebhook(secret, body, signature) {
  if (!signature) return false;
  const got = signature.startsWith("sha256=") ? signature.slice(7) : signature;

  // Node 18+
  try {
    const { createHmac, timingSafeEqual } = await import("node:crypto");
    const expected = createHmac("sha256", secret).update(body, "utf8").digest("hex");
    const a = Buffer.from(expected, "utf8");
    const b = Buffer.from(got, "utf8");
    return a.length === b.length && timingSafeEqual(a, b);
  } catch (e) {
    // 浏览器：用 Web Crypto
  }

  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const mac = await crypto.subtle.sign("HMAC", key, enc.encode(body));
  const hex = Array.from(new Uint8Array(mac)).map((b) => b.toString(16).padStart(2, "0")).join("");
  if (hex.length !== got.length) return false;
  let diff = 0;
  for (let i = 0; i < hex.length; i += 1) diff |= hex.charCodeAt(i) ^ got.charCodeAt(i);
  return diff === 0;
}
