# 插件开发指南（四期 4.3）

宿主把三类能力抽象成插件：**翻译（translator）/ 硬字幕识别（ocr）/ 配音（tts）**。
内置插件包装的就是宿主原有实现——换句话说，插件不是外挂，而是宿主能力的正规入口。

---

## 1. 目录结构

```
<插件目录>/
  my-plugin/
    plugin.json        # 清单（唯一契约）
    my_module.py       # 你的代码
```

插件目录默认为 `<安装目录>/plugins`，可用环境变量 `SUBAI_PLUGIN_DIR` 覆盖。

---

## 2. plugin.json 字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 唯一标识，只允许小写字母/数字与 `. _ -`，且以字母开头（如 `acme.translator.demo`）|
| `name` | 是 | 显示名 |
| `kind` | 是 | `translator` / `ocr` / `tts` |
| `entry` | 建议 | 入口，形如 `my_module:MyClass`；内置插件用 `builtin:ClassName` |
| `version` | 否 | 默认 `1.0.0` |
| `description` | 否 | 一句话说明 |
| `author` | 否 | 作者 |
| `priority` | 否 | 0..1000，**越小越优先**（默认 100）；同优先级时内置优先 |
| `enabled_by_default` | 否 | 默认 `true` |
| `tags` | 否 | 字符串数组 |

清单不合法**不会**让服务起不来：它会作为一条 `state=error` 的记录出现在插件列表里，
并带上具体错误信息（用户能看到，而不是莫名其妙地"少了一个插件"）。

---

## 3. 三类插件要实现的接口

### translator（翻译）

```python
class MyTranslator:
    capabilities = ["translate", "probe"]

    def probe(self) -> dict:          # 可选：供 POST /api/plugins/{id}/probe 调用
        return {"reachable": True}

    def translate_batch(self, texts: list, target: str, **kwargs) -> list:
        return [...]
```

### ocr（硬字幕识别）

```python
class MyOcr:
    capabilities = ["recognize"]

    def available(self) -> bool:      # 可选：列表页会展示；必须便宜（别在这里加载模型）
        return True

    def create_engine(self):          # 返回你的引擎对象
        ...

    def texts_from_frame(self, engine, frame, min_score: float) -> list:
        """返回该帧通过置信度阈值的文本片段（[] 表示没有字幕）。"""
```

主流程 `pipeline.hardsub_segments` 就是通过这两个方法取用 OCR 的。

### tts（配音）

```python
class MyTts:
    capabilities = ["synthesize", "voices"]

    def available(self) -> bool:
        return True

    def create_engine(self):          # 需与 src/tts.py 的引擎接口一致
        ...
```

---

## 4. 生命周期

```
发现（只读 plugin.json，不执行任何插件代码）
  -> 启用（写入 data/plugins.json）
  -> 加载（import 模块 + 实例化入口类）
  -> 使用（被接缝按 kind 取用）
  -> 停用（丢弃实例引用）
```

---

## 5. "停用"的准确含义（重要）

| 情况 | 行为 |
|---|---|
| 某个插件被停用 | 该能力**真的不可用**（例如停用 OCR 插件后，硬字幕识别会明确报错并提示去启用）|
| 插件系统整体关闭（`SUBAI_PLUGIN_ENABLED=false`）| 主流程回退到内置实现，功能不受影响 |
| 插件加载失败 / 清单损坏 | 视为不可用，列表里显示 `error` 与原因 |

这条规则是为了不让"停用"变成一句空话——否则用户以为关掉了，实际还在跑内置实现。

---

## 6. 安全须知

- **加载外部插件 = 执行其代码**。只放你信任的插件；可用 `SUBAI_PLUGIN_ALLOW_EXTERNAL=false` 完全禁止外部插件加载。
- 插件的异常会被宿主捕获（不会拖垮服务），但**插件自己不要阻塞主线程**，耗时操作请放到线程池。
- 宿主约定：`unload` 只是丢弃引用，插件不得持有无法释放的全局资源（如未关闭的句柄、后台线程）。
- 插件不应把密钥写进 `plugin.json`（它会出现在插件列表接口里）。

---

## 7. 调试

```
GET  /api/plugins?detail=true         # 列表 + 能力 + 可用性
GET  /api/plugins/{id}                # 单个插件详情
POST /api/plugins/{id}/probe          # 触发插件自己的 probe()
POST /api/plugins/reload              # 重新扫描插件目录
POST /api/plugins/{id}/enable|disable # 启停（仅管理员）
```

界面上对应「插件」页：分类筛选、启停、探测、目录搜索。

---

## 8. 当前边界（诚实声明）

- 插件目录（`marketplace`）目前是**本地索引**：可搜索、可分类、显示已安装状态；
  **远端安装/更新尚未实现**，接口里不会假装能联网下载。
- 翻译类插件已通过注册表暴露能力，但 `pipeline` 的翻译实现仍是 `_call_llm`
  （避免 pipeline 与 plugins 循环依赖）；OCR 与 TTS 已由接缝真实取用。
