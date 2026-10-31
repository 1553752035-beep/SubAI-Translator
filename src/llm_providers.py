# -*- coding: utf-8 -*-
"""五期：云端翻译服务商预设。

目的：让不懂「什么叫 OpenAI 兼容地址」的人也能用云端翻译——
选服务商 → 只填 API Key → 选模型（有预设，也能自己填），地址由预设带出来。

注意：端点与模型名会随服务商调整，这里以**官方文档**为准维护；
用户也可以用「自定义」直接填地址与模型名。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Provider:
    id: str            # 稳定标识
    name: str          # 显示名
    base_url: str      # OpenAI 兼容基址（到 /v1 这一层）；非 openai 协议时可为空
    models: tuple      # 常用模型（预设下拉）
    key_url: str       # 去哪里拿 API Key
    group: str = "国内"  # 国内 / 国际 / 聚合 / 本地 / 翻译专用
    note: str = ""
    # [2026-10-25] 协议类型。绝大多数 provider 是 openai（/chat/completions），
    # 但翻译专用服务不是 —— DeepL 用 /v2/translate、Google 用 /language/translate/v2。
    # 没有这个字段时，UI 会把 DeepL 当成 OpenAI 兼容端点去调，必然失败。
    protocol: str = "openai"   # openai | deepl | google | tencent_free
    # [2026-10-25] 可用性标注。实测发现「列出来但根本用不了」的服务：
    #   01.AI（yi）的 /v1/models 返回 410 + model_service_closed。
    # 与其让用户填完 key 才发现，不如在数据里标出来并由 UI 置灰。
    # 取值：""（正常）| "discontinued"（官方已停服）
    status: str = ""
    status_note: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["models"] = list(self.models)
        return data


PROVIDERS: tuple = (
    # ---------- 国内主流（常用的排前面）----------
    Provider("deepseek", "DeepSeek 深度求索", "https://api.deepseek.com/v1",
             ("deepseek-chat", "deepseek-reasoner"), "https://platform.deepseek.com/api_keys",
             note="翻译用 deepseek-chat 即可；reasoner 会思考、更贵更慢"),
    Provider("qwen", "阿里通义千问（百炼）", "https://dashscope.aliyuncs.com/compatible-mode/v1",
             ("qwen-turbo", "qwen-plus", "qwen-max"), "https://bailian.console.aliyun.com/",
             note="有免费额度；会自动关闭思考"),
    Provider("doubao", "字节豆包（火山方舟）", "https://ark.cn-beijing.volces.com/api/v3",
             ("doubao-seed-1-6", "doubao-1-5-pro-32k"), "https://console.volcengine.com/ark",
             note="要先在控制台创建推理接入点，模型名填接入点 ID"),
    Provider("kimi", "月之暗面 Kimi", "https://api.moonshot.cn/v1",
             ("moonshot-v1-8k", "moonshot-v1-32k", "kimi-k2-0905-preview"),
             "https://platform.moonshot.cn/console/api-keys", note="长文本见长"),
    Provider("zhipu", "智谱 GLM", "https://open.bigmodel.cn/api/paas/v4",
             ("glm-4-flash", "glm-4-plus", "glm-4-air"), "https://open.bigmodel.cn/usercenter/apikeys",
             note="glm-4-flash 有免费档"),
    Provider("siliconflow", "硅基流动 SiliconFlow", "https://api.siliconflow.cn/v1",
             ("Qwen/Qwen3-8B", "deepseek-ai/DeepSeek-V3", "THUDM/glm-4-9b-chat"),
             "https://cloud.siliconflow.cn/account/ak", group="聚合",
             note="聚合平台，开源模型多且便宜"),
    Provider("hunyuan", "腾讯混元", "https://api.hunyuan.cloud.tencent.com/v1",
             ("hunyuan-turbo", "hunyuan-large"), "https://console.cloud.tencent.com/hunyuan/api-key"),
    Provider("qianfan", "百度文心（千帆）", "https://qianfan.baidubce.com/v2",
             ("ernie-4.5-turbo-128k", "ernie-speed-128k"), "https://console.bce.baidu.com/iam/#/iam/apikey/list"),
    Provider("spark", "讯飞星火", "https://spark-api-open.xf-yun.com/v1",
             ("generalv3.5", "4.0Ultra"), "https://console.xfyun.cn/services/cbm"),
    Provider("minimax", "MiniMax", "https://api.minimax.chat/v1",
             ("MiniMax-Text-01", "abab6.5s-chat"), "https://platform.minimaxi.com/user-center/basic-information"),
    Provider("stepfun", "阶跃星辰 StepFun", "https://api.stepfun.com/v1",
             ("step-2-16k", "step-1-8k"), "https://platform.stepfun.com/interface-key"),
    # [2026-10-25] 实测确认已停服：/v1/models 返回
    #   HTTP 410 {"error":{"code":"model_service_closed",
    #                     "message":"Model service has been discontinued"}}
    # 保留条目（用户可能已有历史配置，突然消失会更困惑），但明确标注。
    Provider("yi", "零一万物 Yi", "https://api.lingyiwanwu.com/v1",
             ("yi-lightning", "yi-large"), "https://platform.lingyiwanwu.com/apikeys",
             status="discontinued",
             status_note="2026-10-25 实测该服务已关闭：/v1/models 返回 "
                         "HTTP 410 model_service_closed（Model service has been discontinued）"),
    # ---------- 国际 ----------
    Provider("openai", "OpenAI", "https://api.openai.com/v1",
             ("gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"), "https://platform.openai.com/api-keys",
             group="国际", note="国内需自备网络条件"),
    Provider("gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai/",
             ("gemini-2.0-flash", "gemini-2.5-flash"), "https://aistudio.google.com/app/apikey",
             group="国际", note="有免费额度"),
    Provider("grok", "xAI Grok", "https://api.x.ai/v1", ("grok-3-mini", "grok-3"),
             "https://console.x.ai/", group="国际"),
    Provider("mistral", "Mistral", "https://api.mistral.ai/v1", ("mistral-small-latest",),
             "https://console.mistral.ai/api-keys/", group="国际"),
    Provider("groq", "Groq（超快）", "https://api.groq.com/openai/v1",
             ("llama-3.3-70b-versatile", "qwen-2.5-32b"), "https://console.groq.com/keys",
             group="国际", note="推理速度极快"),
    # ---------- 聚合 ----------
    Provider("openrouter", "OpenRouter", "https://openrouter.ai/api/v1",
             ("openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet", "google/gemini-2.0-flash-001"),
             "https://openrouter.ai/keys", group="聚合", note="一个 Key 用很多家模型"),
    Provider("together", "Together AI", "https://api.together.xyz/v1",
             ("meta-llama/Llama-3.3-70B-Instruct-Turbo",), "https://api.together.xyz/settings/api-keys",
             group="聚合"),
    Provider("deepinfra", "DeepInfra", "https://api.deepinfra.com/v1/openai",
             ("meta-llama/Meta-Llama-3.1-8B-Instruct",), "https://deepinfra.com/dash/api_keys", group="聚合"),
    # ---------- 翻译专用（不产生幻觉，术语一致性更好）----------
    # 与 LLM 的区别：LLM 会漏句/改写/合并行，专用翻译不会，但不懂上下文。
    # 字幕场景里两者互补，所以并列提供而不是替换。
    Provider("deepl", "DeepL（翻译专用）", "",
             # 注意：tencent_free 条目本应排在本组第一位更合适，
             # 但 deepl 在前便于已有用户保持原有下拉顺序位置稳定。
             ("default",), "https://www.deepl.com/pro-api",
             group="翻译专用", protocol="deepl",
             note="不会改写原文、术语稳定；免费档 50 万字符/月。Key 形如 xxx:fx 走免费端点"),
    Provider("google_translate", "Google 翻译（翻译专用）", "",
             ("default",), "https://console.cloud.google.com/apis/credentials",
             group="翻译专用", protocol="google",
             note="便宜量大，支持术语表；适合先机翻再让 LLM 润色"),
    # [2026-10-25] 免费免 Key 渠道。这是唯一「什么都不用申请就能用」的选项，
    # 实测 2026-10-25：单条/多条均正确、3 条进 3 条出、中英日互译正常、544ms。
    # 放在翻译专用组最前面 —— 没有 Key 的用户应该第一眼看到它。
    Provider("tencent_free", "腾讯交互翻译（免费免 Key）", "",
             ("default",), "https://transmart.qq.com/",
             group="翻译专用", protocol="tencent_free",
             note="不需要注册和 Key，开箱即用；适合先跑通流程再考虑换更好的服务"),

    # ---------- 本地 ----------
    Provider("ollama", "Ollama（本地）", "http://127.0.0.1:11434/v1", ("qwen2.5:7b", "llama3.1:8b"),
             "https://ollama.com/download", group="本地", note="装好即可用，不需要 Key"),
    Provider("lmstudio", "LM Studio（本地）", "http://127.0.0.1:1234/v1", ("local-model",),
             "https://lmstudio.ai/", group="本地", note="图形界面加载本地模型"),
    Provider("koboldcpp", "koboldcpp / llama.cpp（本地）", "http://127.0.0.1:5001/v1", ("koboldcpp",),
             "https://github.com/LostRuins/koboldcpp", group="本地", note="本项目默认的本地方案"),
)

_BY_ID = {p.id: p for p in PROVIDERS}


def list_providers() -> list:
    return [p.to_dict() for p in PROVIDERS]


def get_provider(provider_id: str) -> dict:
    p = _BY_ID.get((provider_id or "").strip())
    return p.to_dict() if p else {}
