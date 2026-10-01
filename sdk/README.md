# SubAI Translator 开放 API SDK

零第三方依赖的轻量客户端，接口细节见 [`docs/API.md`](../docs/API.md)。

| 语言 | 文件 | 运行要求 |
|---|---|---|
| Python | `python/subai.py` | Python 3.8+（仅标准库）|
| JavaScript | `javascript/subai.js` | Node 18+ 或现代浏览器（fetch）|

## 快速开始

```python
import sys
sys.path.insert(0, ".")  # 指向仓库根目录
from sdk.python.subai import SubAIClient, verify_webhook

client = SubAIClient("http://127.0.0.1:8000", api_key="subai_xxx")
print(client.me())
print(client.translate(["你好，世界"], "English")["translations"])
```

```javascript
import { SubAIClient, verifyWebhook } from "./sdk/javascript/subai.js";

const client = new SubAIClient("http://127.0.0.1:8000", "subai_xxx");
console.log((await client.translate(["你好，世界"], "English")).translations);
```

## Webhook 验签示例（Flask 风格伪代码）

```python
from flask import Flask, request
from sdk.python.subai import verify_webhook

app = Flask(__name__)
SECRET = "你注册 Webhook 时拿到的 secret"

@app.post("/subai-hook")
def hook():
    raw = request.get_data()                     # 必须用原始字节
    sig = request.headers.get("X-SubAI-Signature", "")
    if not verify_webhook(SECRET, raw, sig):
        return "bad signature", 401
    event = request.headers.get("X-SubAI-Event")
    data = request.get_json()["data"]
    # ... 处理事件
    return "ok", 200
```
