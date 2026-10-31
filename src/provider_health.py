# -*- coding: utf-8 -*-
"""Provider 可用性批量核验。

为什么需要这个模块
------------------
`llm_providers.py` 里的 25 个 provider 只是「预填了 base_url + 模型名」。
预填不等于可用 —— base_url 可能已变更、模型名可能已下线、
该服务可能要求非 Bearer 认证。用户照着填完 key 才发现不能用，
这种「纸面数量」比老老实实只列 3 个更坑人。

本模块做两件事：
1. **探测**：对每个 provider 发一次极轻量的真实请求，判定「通 / 密钥错 / 地址错 / 网络不通」。
   判定逻辑复用 `llm.probe()` 的 `_classify`，保证和单端点测试口径一致。
2. **缓存**：探测要发网络请求，不能每次打开设置页都跑一遍。
   结果落 `data/provider_health.json`，带时间戳；超过 TTL 视为过期但仍会返回，
   由 UI 显示「上次验证于 N 天前」。

刻意不做的事
------------
- **不并发太多**：默认 4 并发。探测是「锦上添花」的功能，
  为了它触发对方服务限流（尤其免费额度）反而伤用户。
- **不自动删除失败项**：判定失败可能只是当次网络抖动。
  由用户看着报告决定，模块只如实记录。
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from src import llm_providers
from src import llm as llm_module

# 健康记录 TTL：7 天内算「近期验证过」
HEALTH_TTL_SEC = 7 * 24 * 3600
# 默认并发数：见模块开头「不并发太多」
DEFAULT_WORKERS = 4
# 单次探测超时（秒）。比 llm 的默认略长，给跨洋端点留余量
PROBE_TIMEOUT = 8.0


def _health_path() -> str:
    """健康记录文件路径（放在 data/ 下，与其它运行数据同处）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "data", "provider_health.json")


def load_health() -> dict:
    """读取已保存的健康记录。文件损坏/不存在时返回空字典，绝不抛异常。"""
    p = _health_path()
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_health(records: dict) -> str:
    """保存健康记录（原子写入：先写临时文件再替换，避免半截文件）。"""
    p = _health_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    return p


def probe_provider(provider_id: str, api_key: str = "",
                   timeout: float = PROBE_TIMEOUT) -> dict:
    """探测单个 provider。

    返回 {id, name, protocol, base_url, verdict, authorized, reachable,
          detail, checked_at, skipped}

    `skipped=True` 表示这个 provider 结构上不适用网络探测
    （例如翻译专用协议没有 /models 端点，或本地服务没启动）。
    """
    info = llm_providers.get_provider(provider_id)
    if not info:
        return {"id": provider_id, "verdict": "unknown_provider",
                "authorized": False, "reachable": False,
                "detail": "未知 provider", "checked_at": time.time(),
                "skipped": True}

    proto = info.get("protocol", "openai")
    base = info.get("base_url", "") or ""
    base_out = {"id": provider_id, "name": info.get("name", provider_id),
                "protocol": proto, "base_url": base, "checked_at": time.time()}

    # 翻译专用协议（DeepL / Google）没有 OpenAI 的 /models 端点，
    # 用同一套探测器会得到 404 的假失败。这里如实标记「不适用」。
    if proto != "openai":
        base_out.update({"verdict": "not_probeable", "authorized": False,
                         "reachable": False, "skipped": True,
                         "detail": "翻译专用协议，无 /models 端点，请用「测试连接」"})
        return base_out

    if not api_key:
        # 没有 key 也可以探活（很多服务 /models 不要求认证），
        # 但结论只能说明「端点存在」，不能说明「key 可用」。
        r = llm_module.probe(base, "", timeout=timeout)
        base_out.update({
            "verdict": "no_key" if r.get("verdict") == "ok" else r.get("verdict"),
            "authorized": False,
            "reachable": r.get("reachable", False),
            "detail": "未提供密钥，仅验证端点存在（%s）" % r.get("detail", ""),
            "skipped": False,
        })
        return base_out

    r = llm_module.probe(base, api_key, timeout=timeout)
    base_out.update({
        "verdict": r.get("verdict"),
        "authorized": r.get("authorized", False),
        "reachable": r.get("reachable", False),
        "http_status": r.get("http_status"),
        "detail": r.get("detail", ""),
        "skipped": False,
    })
    return base_out


def probe_many(provider_ids: Optional[list] = None,
               api_key: str = "",
               workers: int = DEFAULT_WORKERS,
               timeout: float = PROBE_TIMEOUT,
               progress_callback=None) -> dict:
    """批量探测并把结果落盘。

    `provider_ids` 为空时探测全部。返回 {results, summary, saved_at, path}。
    """
    ids = list(provider_ids) if provider_ids else [
        p["id"] for p in llm_providers.list_providers()]

    results = []
    done = 0
    if ids:
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(ids)))) as pool:
            futures = {pool.submit(probe_provider, pid, api_key, timeout): pid
                       for pid in ids}
            for fut in as_completed(futures):
                pid = futures[fut]
                try:
                    results.append(fut.result())
                except Exception as e:  # noqa: BLE001
                    results.append({"id": pid, "verdict": "probe_error",
                                    "authorized": False, "reachable": False,
                                    "detail": repr(e), "checked_at": time.time(),
                                    "skipped": True})
                done += 1
                if progress_callback:
                    try:
                        progress_callback(done, len(ids), pid)
                    except Exception:  # noqa: BLE001
                        pass

    # 保持与传入顺序一致，便于 UI 稳定显示
    order = {pid: i for i, pid in enumerate(ids)}
    results.sort(key=lambda r: order.get(r.get("id"), 999))

    records = load_health()
    for r in results:
        records[r["id"]] = r
    path = save_health(records)

    return {
        "results": results,
        "summary": summarize(results),
        "saved_at": time.time(),
        "path": path,
    }


def summarize(results: list) -> dict:
    """把一批探测结果汇总成计数。判据只认 authorized，不认「网络通」。"""
    s = {"total": len(results), "ok": 0, "auth_failed": 0, "not_found": 0,
         "rate_limited": 0, "network_error": 0, "other": 0, "skipped": 0,
         "authorized": 0}
    for r in results or []:
        if r.get("skipped"):
            s["skipped"] += 1
            continue
        if r.get("authorized"):
            s["authorized"] += 1
        v = r.get("verdict") or "other"
        if v in s:
            s[v] += 1
        else:
            s["other"] += 1
    return s


def get_health(provider_id: str) -> Optional[dict]:
    """取单个 provider 的健康记录；顺便标注新鲜度。"""
    rec = load_health().get(provider_id)
    if not rec:
        return None
    age = time.time() - float(rec.get("checked_at") or 0)
    rec = dict(rec)
    rec["age_sec"] = age
    rec["stale"] = age > HEALTH_TTL_SEC
    return rec