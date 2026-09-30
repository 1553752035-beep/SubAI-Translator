# -*- coding: utf-8 -*-
"""
SubAI Translator —— 阶段A 本地可验证项验收脚本
================================================

覆盖方案 4.6 遗留验证项中不依赖 Docker / K8s / 生产域名、可在本机闭环的部分：

  V-6a  100 个任务排队（队列容量 + 并发上限）
  V-6b  备份 / 恢复耗时（目标：恢复 ≤ 30 分钟）
  V-6c  告警触发（目标：触发延迟 ≤ 1 分钟，由巡检间隔决定）

Docker / K8s / HTTPS 证书 / 漏洞扫描等项见项目总方案 4.6。

用法：
    .venv\\Scripts\\python.exe tools\\bench_stage_a.py
结果输出为 JSON（末尾 SUMMARY），便于汇总记录。
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.backup.manager import BackupManager
from src.config import config
from src.db.tasks import TaskManager
from src.monitoring.alerts import build_default_alert_manager
from src.queue.task_queue import TaskQueue


async def _noop(**kwargs):
    return None


async def check_queue() -> dict:
    """V-6a：队列可容纳 100 个任务；运行并发不超过 max_concurrent。"""
    tmp = tempfile.mkdtemp(prefix="subai_v6a_")
    tm = TaskManager(os.path.join(tmp, "tasks.db"))
    await tm.initialize()

    # (1) 容量：不启动处理器时前 100 个全部入队，第 101 个起被拒绝
    q = TaskQueue(tm, max_concurrent=2, max_queue_size=100)
    accepted = 0
    for i in range(105):
        if await q.submit(task_id="cap-%03d" % i, callback=_noop, priority="medium"):
            accepted += 1
    queue_size = q.queue_size

    # (2) 并发上限：启动处理器，提交 12 个慢任务，观测峰值并发
    q2 = TaskQueue(tm, max_concurrent=2, max_queue_size=100)
    await q2.initialize()
    lock = asyncio.Lock()
    state = {"peak": 0, "current": 0, "done": 0}

    async def slow(**kwargs):
        async with lock:
            state["current"] += 1
            state["peak"] = max(state["peak"], state["current"])
        await asyncio.sleep(0.05)
        async with lock:
            state["current"] -= 1
            state["done"] += 1

    for i in range(12):
        await q2.submit(task_id="run-%03d" % i, callback=slow, priority="high")
    deadline = time.time() + 15
    while time.time() < deadline and (q2.queue_size + q2.running_count) > 0:
        await asyncio.sleep(0.05)
    await q2.shutdown()
    await tm.close()

    return {
        "metric": "queue_100",
        "capacity": 100,
        "accepted": accepted,
        "queue_size_at_capacity": queue_size,
        "overflow_rejected": 105 - accepted,
        "tasks_dispatched": state["done"],
        "peak_concurrency": state["peak"],
        "max_concurrent": 2,
        "pass": accepted == 100 and queue_size == 100 and (105 - accepted) == 5
                and state["done"] == 12 and state["peak"] <= 2,
    }


def check_backup() -> dict:
    """V-6b：备份 / 恢复耗时（目标：恢复 ≤ 30 分钟）。"""
    tmp = tempfile.mkdtemp(prefix="subai_v6b_")
    saved = (
        config.paths.terminology_db,
        config.paths.tasks_db,
        config.cache.db_path,
        config.auth.users_db,
        config.backup.backup_dir,
    )
    try:
        config.paths.terminology_db = os.path.join(tmp, "terminology.db")
        config.paths.tasks_db = os.path.join(tmp, "tasks.db")
        config.cache.db_path = os.path.join(tmp, "translation_cache.db")
        config.auth.users_db = os.path.join(tmp, "users.db")
        config.backup.backup_dir = os.path.join(tmp, "backups")

        for p in (config.terminology_db, config.tasks_db, config.cache_db_path, config.users_db):
            conn = sqlite3.connect(p)
            conn.execute("CREATE TABLE t (x INTEGER)")
            conn.execute("INSERT INTO t VALUES (1)")
            conn.commit()
            conn.close()

        mgr = BackupManager(config.backup_dir, max_backups=10)
        t0 = time.perf_counter()
        manifest = mgr.create_backup()
        create_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        restored = mgr.restore_backup(manifest["id"])
        restore_s = time.perf_counter() - t0
    finally:
        (
            config.paths.terminology_db,
            config.paths.tasks_db,
            config.cache.db_path,
            config.auth.users_db,
            config.backup.backup_dir,
        ) = saved

    return {
        "metric": "backup_restore",
        "files_backed_up": sorted(manifest.get("files", {}).keys()),
        "create_seconds": round(create_s, 4),
        "restore_seconds": round(restore_s, 4),
        "target_restore_seconds": 1800,
        "restored": restored.get("restored"),
        "pass": restore_s <= 30 * 60 and len(restored.get("restored", [])) >= 3,
    }


def check_alert() -> dict:
    """V-6c：告警触发与恢复（目标：触发延迟 ≤ 1 分钟）。"""
    mgr = build_default_alert_manager()
    snapshot = {
        "memory_percent": 99.0,
        "queue_size": 95,
        "max_queue_size": 100,
        "task_succeeded": 0,
        "task_failed": 20,
        "request_latency_p99": 9.0,
    }
    t0 = time.perf_counter()
    fired = mgr.evaluate(snapshot)
    evaluate_ms = (time.perf_counter() - t0) * 1000
    repeat = mgr.evaluate(snapshot)          # 持续触发不应重复记录
    resolved = mgr.evaluate({})              # 条件消失应恢复
    interval = config.monitoring.alert_check_interval_seconds

    return {
        "metric": "alert",
        "fired": sorted(a.name for a in fired),
        "evaluate_ms": round(evaluate_ms, 3),
        "repeat_transitions": len(repeat),
        "resolved": sorted(a.name for a in resolved),
        "check_interval_seconds": interval,
        "target_interval_seconds": 60,
        "pass": len(fired) >= 3 and len(repeat) == 0 and len(resolved) >= 3 and 0 < interval <= 60,
    }


def main() -> int:
    results = [asyncio.run(check_queue()), check_backup(), check_alert()]
    print("=== STAGE-A LOCAL ACCEPTANCE ===")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    ok = all(r.get("pass") for r in results)
    print("SUMMARY:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
