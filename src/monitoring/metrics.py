# -*- coding: utf-8 -*-
"""
SubAI Translator —— 进程内指标采集（三期：监控与告警）
========================================================

轻量级指标注册表，不引入第三方监控依赖，支持：
1. 计数器（Counter）：请求数、任务成功/失败数等单调递增指标
2. 仪表盘（Gauge）：内存使用、队列长度、活跃任务数等可增可减指标
3. 直方图（Histogram）：请求延迟分布（sum/count + 指数分桶）

输出格式：
- `to_prometheus()`：Prometheus 文本格式，供 /api/metrics 抓取
- `snapshot()`：Python 字典，供告警引擎评估

系统指标（CPU/内存）优先使用 psutil；未安装时回退读取 /proc（Linux），
两者皆不可用时返回 None（不报错，保证监控模块在任何环境可运行）。
"""
from __future__ import annotations

import os
import threading
import time
from typing import Optional

# 延迟直方图分桶（秒）
LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


def _format_name(name: str, labels: Optional[dict] = None) -> str:
    """将 name + labels 编码为内部 key（labels 仅用于区分序列，不影响 Prometheus 导出）"""
    if not labels:
        return name
    parts = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return f"{name}{{{parts}}}"


class MetricsRegistry:
    """线程安全的指标注册表"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started_at = time.time()
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}
        # 每个直方图：{"count": int, "sum": float, "buckets": {upper_bound: int}}
        self._histograms: dict[str, dict] = {}

    # ------------------------------------------------------------------ #
    # 写入
    # ------------------------------------------------------------------ #

    def inc(self, name: str, value: float = 1.0, labels: Optional[dict] = None) -> None:
        """计数器自增"""
        key = _format_name(name, labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + value

    def set(self, name: str, value: float, labels: Optional[dict] = None) -> None:
        """仪表盘设值"""
        key = _format_name(name, labels)
        with self._lock:
            self._gauges[key] = value

    def observe(self, name: str, value: float, labels: Optional[dict] = None) -> None:
        """记录一次观测值（直方图）"""
        key = _format_name(name, labels)
        with self._lock:
            hist = self._histograms.setdefault(key, {"count": 0, "sum": 0.0, "buckets": {}})
            hist["count"] += 1
            hist["sum"] += value
            for bound in LATENCY_BUCKETS:
                if value <= bound:
                    hist["buckets"][bound] = hist["buckets"].get(bound, 0) + 1

    # ------------------------------------------------------------------ #
    # 读取
    # ------------------------------------------------------------------ #

    def snapshot(self) -> dict:
        """返回当前全部指标的深拷贝快照"""
        with self._lock:
            return {
                "uptime_seconds": time.time() - self._started_at,
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {
                    name: {
                        "count": h["count"],
                        "sum": h["sum"],
                        "buckets": dict(h["buckets"]),
                    }
                    for name, h in self._histograms.items()
                },
            }

    def get_counter(self, name: str, labels: Optional[dict] = None) -> float:
        key = _format_name(name, labels)
        with self._lock:
            return self._counters.get(key, 0.0)

    def get_gauge(self, name: str, labels: Optional[dict] = None) -> float:
        key = _format_name(name, labels)
        with self._lock:
            return self._gauges.get(key, 0.0)

    def reset(self) -> None:
        """清空所有指标（用于测试隔离）"""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
            self._started_at = time.time()

    # ------------------------------------------------------------------ #
    # Prometheus 文本格式
    # ------------------------------------------------------------------ #

    def to_prometheus(self) -> str:
        """导出 Prometheus 文本格式（OpenMetrics 兼容的 text exposition）"""
        snap = self.snapshot()
        lines: list[str] = []

        def _escape(s: str) -> str:
            return s.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')

        for name, value in sorted(snap["counters"].items()):
            base, labels = self._split(name)
            lines.append(f"{base}{labels} {_num(value)}")

        for name, value in sorted(snap["gauges"].items()):
            base, labels = self._split(name)
            lines.append(f"{base}{labels} {_num(value)}")

        for name, hist in sorted(snap["histograms"].items()):
            base, labels = self._split(name)
            lines.append(f"{base}_count{labels} {hist['count']}")
            lines.append(f"{base}_sum{labels} {_num(hist['sum'])}")
            for bound in LATENCY_BUCKETS:
                bucket_labels = self._merge_label(labels, "le", _num(bound))
                lines.append(f"{base}_bucket{bucket_labels} {hist['buckets'].get(bound, 0)}")
            lines.append(f"{base}_bucket{self._merge_label(labels, 'le', '+Inf')} {hist['count']}")

        lines.append(f"subai_uptime_seconds {_num(snap['uptime_seconds'])}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _split(name: str) -> tuple[str, str]:
        """把内部 key 拆成 metric 名与标签串"""
        if "{" in name:
            base, rest = name.split("{", 1)
            return base, "{" + rest
        return name, ""

    @staticmethod
    def _merge_label(labels: str, key: str, value: str) -> str:
        """在既有标签串里追加一个标签"""
        if not labels:
            return f'{{{key}="{value}"}}'
        return labels[:-1] + f',{key}="{value}"}}'


def _num(value: float) -> str:
    """数值格式化：整数不带小数点，浮点保留有限精度"""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.6g}"


# --------------------------------------------------------------------------- #
# 全局实例
# --------------------------------------------------------------------------- #

REGISTRY = MetricsRegistry()


# --------------------------------------------------------------------------- #
# 系统指标（CPU / 内存）
# --------------------------------------------------------------------------- #

def _read_memory_linux() -> Optional[tuple[int, int]]:
    """读取 Linux /proc/meminfo 的 (可用, 总量) 字节数；失败返回 None"""
    try:
        meminfo: dict[str, int] = {}
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    value = parts[1].strip().split()[0]
                    if value.isdigit():
                        meminfo[parts[0]] = int(value) * 1024  # kB -> bytes
        total = meminfo.get("MemTotal")
        available = meminfo.get("MemAvailable")
        if total and available:
            return available, total
    except (OSError, ValueError):
        pass
    return None


def collect_system_metrics() -> dict:
    """
    采集当前进程/系统资源指标，返回：
        {"memory_used_bytes", "memory_total_bytes", "memory_percent", "cpu_percent"}
    无法采集的字段为 None。
    """
    memory_used: Optional[int] = None
    memory_total: Optional[int] = None
    memory_percent: Optional[float] = None
    cpu_percent: Optional[float] = None

    try:
        import psutil  # type: ignore

        proc = psutil.Process()
        mem = proc.memory_info()
        memory_used = int(mem.rss)
        vmem = psutil.virtual_memory()
        memory_total = int(vmem.total)
        memory_percent = vmem.percent
        cpu_percent = proc.cpu_percent(interval=None)
    except Exception:  # noqa: BLE001
        # psutil 不可用或采样失败，回退到 /proc（Linux）
        mem = _read_memory_linux()
        if mem:
            available, total = mem
            memory_used = total - available
            memory_total = total
            if total > 0:
                memory_percent = round((memory_used / total) * 100, 2)

    return {
        "memory_used_bytes": memory_used,
        "memory_total_bytes": memory_total,
        "memory_percent": memory_percent,
        "cpu_percent": cpu_percent,
    }
