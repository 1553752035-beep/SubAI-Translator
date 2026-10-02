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
    base_url: str      # OpenAI 兼容基址（到 /v1 这一层）
    models: tuple      # 常用模型（预设下拉）
    key_url: str       # 去哪里拿 API Key
    group: str = "国内"  # 国内 / 国际 / 聚合 / 本地
    note: str = ""

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
    Provider("yi", "零一万物 Yi", "https://api.lingyiwanwu.com/v1",
             ("yi-lightning", "yi-large"), "https://platform.lingyiwanwu.com/apikeys"),
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
