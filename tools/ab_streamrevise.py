# -*- coding: utf-8 -*-
"""A/B：StreamRevise GGUF（本地 koboldcpp）vs 云端 DeepSeek。

严格按 febilly/Hy-MT2-1.8B-StreamRevise-LoRA 的 README 实现：
- 首个 chunk 用 Hy-MT2 标准 prompt（无 history）
- raw completion 端点需手动套 chat template：
  <｜hy_begin▁of▁sentence｜><｜hy_User｜>{PROMPT}<｜hy_Assistant｜>
- greedy（temperature=0）
"""
import json
import os
import re
import sys
import time

import httpx

sys.stdout.reconfigure(encoding="utf-8")

LOCAL_URL = "http://127.0.0.1:5001/v1/completions"

LANGUAGE_NAMES = {"zh": "Chinese", "en": "English", "ja": "Japanese"}
STABILITY_RULE = (
    "When the source meaning has not changed, preserve the still-correct prefix "
    "of the previous translation whenever possible. When content is added or "
    "corrected, accuracy and completeness take priority."
)


def render_first_prompt(target_language: str, current_source: str, source_language: str = None) -> str:
    """首 chunk：Hy-MT2 标准 prompt（README 原文）。"""
    t = LANGUAGE_NAMES.get(target_language, target_language)
    s = LANGUAGE_NAMES.get(source_language, source_language)
    direction = ("from %s into %s" % (s, t)) if source_language else ("into %s" % t)
    return ("Translate the following text %s. Note that you should only output the "
            "translated result without any additional explanation:\n\n%s" % (direction, current_source))


def render_revise_prompt(target_language, current_source, history=(),
                         previous_source="", previous_translation="", source_language=None) -> str:
    """后续更新：四个 background 块（可选、顺序固定）。"""
    t = LANGUAGE_NAMES.get(target_language, target_language)
    s = LANGUAGE_NAMES.get(source_language, source_language)
    direction = ("from %s into %s" % (s, t)) if source_language else ("into %s" % t)
    blocks = []
    if history:
        blocks.append("Recent source utterances:\n" + "\n".join(list(history)[-10:]))
    if previous_source:
        blocks.append("Previous version of the current source:\n" + previous_source)
    if previous_translation:
        blocks.append("Previous translation of the current source:\n" + previous_translation)
    blocks.append(STABILITY_RULE)
    return ("[Background Information]\n" + "\n\n".join(blocks)
            + "\n\nPlease translate the following text %s, taking the provided background "
              "information into consideration.\n\n[Source Text]\n%s" % (direction, current_source))


def wrap_template(prompt: str) -> str:
    """README 给出的 raw completion 精确串（无尾随换行）。"""
    return "<｜hy_begin▁of▁sentence｜><｜hy_User｜>" + prompt + "<｜hy_Assistant｜>"


def read_srt_texts(path: str) -> list[str]:
    raw = open(path, encoding="utf-8", errors="ignore").read()
    out = []
    for blk in re.split(r"\n\s*\n", raw.strip()):
        lines = blk.splitlines()
        if len(lines) >= 3 and "-->" in lines[1]:
            out.append(lines[2].strip())
    return out


def translate_local(client: httpx.Client, texts: list[str], target="en", source="zh") -> tuple[list[str], float]:
    out, t0 = [], time.time()
    for i, src in enumerate(texts, 1):
        prompt = wrap_template(render_first_prompt(target, src, source))
        body = {"prompt": prompt, "max_tokens": 256, "temperature": 0.0, "top_p": 1.0,
                "stop": ["<｜hy_", "\n\n"], "stream": False}
        r = client.post(LOCAL_URL, json=body)
        r.raise_for_status()
        d = r.json()
        txt = (d.get("choices") or [{}])[0].get("text", "") or ""
        out.append(txt.strip())
        print("  [%d/%d] %s" % (i, len(texts), txt.strip()[:60]))
    return out, time.time() - t0


def translate_cloud(client: httpx.Client, texts: list[str], target="en", source="zh") -> tuple[list[str], float]:
    """云端：与项目现有翻译思路一致（批次 + JSON 数组），用于公平对比。"""
    api_key = os.environ.get("SUBAI_LLM_CLOUD_API_KEY", "")
    url = os.environ.get("SUBAI_LLM_CLOUD_URL", "https://api.deepseek.com/v1/chat/completions")
    model = os.environ.get("SUBAI_LLM_CLOUD_MODEL", "deepseek-chat")
    if not api_key:
        raise RuntimeError("缺少 SUBAI_LLM_CLOUD_API_KEY")
    numbered = "\n".join("%d. %s" % (i + 1, t) for i, t in enumerate(texts))
    sys_prompt = ("你是专业字幕翻译。把下面的中文逐行翻译成英文。只输出一个 JSON 数组，"
                  "每行一个字符串，数量与输入完全一致，不要编号、不要解释。\n\n" + numbered)
    t0 = time.time()
    r = client.post(url, headers={"Authorization": "Bearer " + api_key},
                    json={"model": model, "temperature": 0.0,
                          "messages": [{"role": "user", "content": sys_prompt}]},
                    timeout=300)
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    m = re.search(r"\[.*\]", content, re.S)
    arr = json.loads(m.group(0)) if m else []
    arr = [str(x).strip() for x in arr]
    if len(arr) != len(texts):
        print("  !! 云端返回 %d 行，期望 %d 行" % (len(arr), len(texts)))
        arr = (arr + [""] * len(texts))[:len(texts)]
    return arr, time.time() - t0


def main():
    srt = sys.argv[1] if len(sys.argv) > 1 else r"D:\SubAI-Translator\源码\output\Desktop 2026.03.17 - 21.13.00.02.DVR.asr-raw.srt"
    texts = read_srt_texts(srt)
    print("输入: %s" % srt)
    print("行数: %d" % len(texts))
    print()
    with httpx.Client(timeout=300) as client:
        print("=== 本地 StreamRevise（koboldcpp）===")
        local, t_local = translate_local(client, texts)
        print("本地耗时: %.1fs" % t_local)
        print()
        print("=== 云端 DeepSeek ===")
        cloud, t_cloud = translate_cloud(client, texts)
        print("云端耗时: %.1fs" % t_cloud)

    # 指标
    def stats(name, arr):
        empty = sum(1 for x in arr if not x.strip())
        same = sum(1 for a, b in zip(texts, arr) if a.strip() == b.strip())
        print("%-10s 空行=%d  与原文相同=%d  (共 %d)" % (name, empty, same, len(arr)))
        return empty
    print()
    print("=== 指标 ===")
    stats("本地", local)
    stats("云端", cloud)
    print()
    print("=== 抽样对比（前 12 行）===")
    for i, (s, a, b) in enumerate(zip(texts, local, cloud)):
        if i >= 12:
            break
        print("%2d. 源: %s" % (i + 1, s))
        print("    本地: %s" % (a or "(空)"))
        print("    云端: %s" % (b or "(空)"))
    outdir = os.path.dirname(srt)
    base = os.path.splitext(os.path.basename(srt))[0]
    with open(os.path.join(outdir, base + ".ab-local.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(local))
    with open(os.path.join(outdir, base + ".ab-cloud.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(cloud))
    print()
    print("完整结果已写入:<stem>.ab-local.txt / <stem>.ab-cloud.txt")


if __name__ == "__main__":
    main()
