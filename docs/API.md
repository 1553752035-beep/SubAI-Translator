# 开放 API 与 Webhook（四期 4.5）

本文件是**开放平台**的完整接口参考：怎么拿密钥、能调什么、回调怎么验签。

---

## 1. 两种鉴权，别混用

| 用途 | 鉴权方式 | 适用接口 |
|---|---|---|
| 本程序自己（桌面端 / 前端）| `Authorization: Bearer <JWT>`（登录获得）| `/api/*` 全部业务接口 |
| 第三方程序 | **API 密钥**：`Authorization: Bearer subai_xxx` 或 `X-API-Key: subai_xxx` | `/api/open/v1/*` |

管理密钥与 Webhook 需要**管理员 JWT**。

---

## 2. 开放 API（`/api/open/v1`）

### GET `/api/open/v1/me`
当前密钥信息与用量（`call_count` / `error_count` / `success_rate`）。

```bash
curl -H "X-API-Key: subai_xxx" http://127.0.0.1:8000/api/open/v1/me
```

### GET `/api/open/v1/languages`
语言清单与能力矩阵（哪些语言支持识别 / 翻译 / 配音）。计一次调用。

### POST `/api/open/v1/translate`
翻译一组文本。需要密钥具备 `translate` 权限。

```json
{
  "texts": ["今天天气不错，我们出去走走吧。", "人工智能正在改变世界。"],
  "target": "English",
  "terms": {"人工智能": "Artificial Intelligence"},
  "use_cache": true
}
```

返回：

```json
{
  "translations": ["The weather is nice today, let's go for a walk.", "Artificial Intelligence is changing the world."],
  "target": "en",
  "count": 2
}
```

### GET `/api/open/v1/tasks/{task_id}`
查询任务状态与产物。需要 `tasks` 权限。任务不存在返回 404（并计入该密钥的错误数）。

---

## 3. 管理接口（`/api/openapi`，需管理员 JWT）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/openapi/stats` | 密钥与回调的总览（调用数、成功率）|
| GET | `/api/openapi/keys` | 密钥列表（只显示前缀）|
| POST | `/api/openapi/keys` | 创建密钥，**明文只在响应里出现一次** |
| POST | `/api/openapi/keys/{id}/enable` `/disable` | 启用 / 停用 |
| DELETE | `/api/openapi/keys/{id}` | **吊销**（哈希打散，不可恢复）|
| GET | `/api/openapi/usage?key_id=&days=30` | 按天调用量 |
| GET | `/api/openapi/webhooks` | Webhook 列表 + 投递统计 |
| POST | `/api/openapi/webhooks` | 注册 Webhook（返回 secret）|
| POST | `/api/openapi/webhooks/{id}/enable` `/disable` | 启停 |
| DELETE | `/api/openapi/webhooks/{id}` | 删除（含投递记录）|
| POST | `/api/openapi/webhooks/{id}/test` | 立即发一条测试事件 |
| GET | `/api/openapi/webhooks/{id}/deliveries` | 投递记录（状态/尝试次数/HTTP 码/错误）|

> 密钥安全：服务端**只保存 sha256(密钥)**，比对用 constant-time；明文只在创建时返回一次。

---

## 4. Webhook

### 事件类型

| 事件 | 触发时机 |
|---|---|
| `task.completed` | 任务完成 |
| `task.failed` | 任务失败 |
| `task.cancelled` | 任务被取消 |
| `key.created` | 新建 API 密钥 |
| `webhook.test` | 手动测试 |

### 请求格式

```http
POST /your-hook HTTP/1.1
Content-Type: application/json; charset=utf-8
X-SubAI-Event: task.completed
X-SubAI-Delivery: dl_xxx
X-SubAI-Signature: sha256=<hex>

{"event":"task.completed","delivery_id":"dl_xxx","webhook_id":"wh_xxx","sent_at":1790866368.3,
 "data":{"task_id":"t1","status":"completed","target_lang":"en","result_files":["a.srt"]}}
```

### 验签（务必做）

签名算法：`HMAC-SHA256(secret, 原始请求体)` 的十六进制，前缀 `sha256=`。
**要校验原始字节**（先读 body 再解析 JSON），并做常数时间比较。

```python
import hashlib, hmac

def verify(secret: str, body: bytes, signature: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    got = signature.split("=", 1)[1] if signature.startswith("sha256=") else signature
    return hmac.compare_digest(expected, got)
```

```javascript
import { createHmac, timingSafeEqual } from 'node:crypto';

export function verifyWebhook(secret, body, signature) {
  const expected = createHmac("sha256", secret).update(body).digest("hex");
  const got = signature.startsWith("sha256=") ? signature.slice(7) : signature;
  const a = Buffer.from(expected), b = Buffer.from(got);
  return a.length === b.length && timingSafeEqual(a, b);
}
```

### 重试策略

- 只有 **2xx 算成功**；其余（含超时、连接失败）都算失败并重试；
- 默认最多 **4 次**，第 n 次重试前等待 `n × 1s`（可用环境变量调整）；
- 每次投递都落库，可在管理接口看到尝试次数与错误原因；
- **回调失败绝不影响任务本身**。

---

## 5. 错误码

| HTTP | 含义 |
|---|---|
| 401 | 缺少 / 无效 / 已吊销的密钥；或未登录 |
| 403 | 密钥缺少该权限，或非管理员 |
| 404 | 任务 / 密钥 / Webhook 不存在 |
| 400 | 参数错误（如回调地址不是 http(s)）|
| 502 | 翻译后端失败（已在响应里给出原因）|

---

## 6. SDK

官方轻量 SDK（无第三方依赖）：

| 语言 | 路径 |
|---|---|
| Python | `sdk/python/subai.py` |
| JavaScript / TypeScript | `sdk/javascript/subai.js` |

```python
from sdk.python.subai import SubAIClient

client = SubAIClient("http://127.0.0.1:8000", api_key="subai_xxx")
print(client.languages()["stats"])
print(client.translate(["你好，世界"], "English"))
```

```javascript
import { SubAIClient, verifyWebhook } from './sdk/javascript/subai.js';

const client = new SubAIClient("http://127.0.0.1:8000", "subai_xxx");
const result = await client.translate(["你好，世界"], "English");
console.log(result.translations);
```

---

## 7. 边界（诚实声明）

- 开放 API 目前提供**翻译 / 语言清单 / 任务查询**三件事；上传视频建任务仍走主接口（需要登录态）。
- 未实现按密钥的独立限流（沿用全局限流中间件）；密钥维度的**用量统计**已提供。
- Webhook 只做 at-least-once 语义下的有限重试，**没有持久队列**：进程退出时未投递完的会留在 `pending`。
