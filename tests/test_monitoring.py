# -*- coding: utf-8 -*-
"""
SubAI Translator —— 监控与告警单元测试（三期）
================================================
覆盖：
1. MetricsRegistry：计数器/仪表盘/直方图/Prometheus 导出/重置
2. collect_system_metrics：返回结构完整（值可为 None）
3. AlertManager：默认规则触发、恢复、历史记录
"""
from __future__ import annotations

import pytest

from src.monitoring.metrics import MetricsRegistry, collect_system_metrics
from src.monitoring.alerts import AlertManager, build_default_alert_manager


# --------------------------------------------------------------------------- #
# MetricsRegistry
# --------------------------------------------------------------------------- #

class TestMetricsRegistry:
    def test_counter_and_gauge(self):
        reg = MetricsRegistry()
        reg.inc("http_requests")
        reg.inc("http_requests")
        reg.inc("http_requests", 3)
        reg.set("active_tasks", 5)

        snap = reg.snapshot()
        assert snap["counters"]["http_requests"] == 5
        assert snap["gauges"]["active_tasks"] == 5

    def test_labels_distinguish_series(self):
        reg = MetricsRegistry()
        reg.inc("requests", labels={"method": "GET"})
        reg.inc("requests", labels={"method": "POST"})

        snap = reg.snapshot()
        assert snap["counters"]['requests{method="GET"}'] == 1
        assert snap["counters"]['requests{method="POST"}'] == 1

    def test_observe_histogram(self):
        reg = MetricsRegistry()
        reg.observe("latency", 0.03)
        reg.observe("latency", 3.0)

        hist = reg.snapshot()["histograms"]["latency"]
        assert hist["count"] == 2
        assert hist["sum"] == pytest.approx(3.03)
        # 0.03 落在第一个桶，3.0 落在中间桶
        assert hist["buckets"][0.05] == 1
        assert hist["buckets"][5.0] == 2

    def test_to_prometheus(self):
        reg = MetricsRegistry()
        reg.inc("subai_request_total", labels={"path": "/api/health"})
        reg.set("subai_queue_size", 3)
        reg.observe("subai_request_duration_seconds", 0.2)

        text = reg.to_prometheus()
        assert 'subai_request_total{path="/api/health"} 1' in text
        assert "subai_queue_size 3" in text
        assert "subai_request_duration_seconds_count 1" in text
        assert "subai_request_duration_seconds_sum 0.2" in text

    def test_reset(self):
        reg = MetricsRegistry()
        reg.inc("x")
        reg.reset()
        assert reg.snapshot()["counters"] == {}


# --------------------------------------------------------------------------- #
# collect_system_metrics
# --------------------------------------------------------------------------- #

class TestSystemMetrics:
    def test_returns_expected_keys(self):
        m = collect_system_metrics()
        assert set(m) == {
            "memory_used_bytes",
            "memory_total_bytes",
            "memory_percent",
            "cpu_percent",
        }


# --------------------------------------------------------------------------- #
# AlertManager
# --------------------------------------------------------------------------- #

class TestAlertManager:
    def test_high_memory_fires_and_resolves(self):
        mgr = build_default_alert_manager()
        # 内存 95% → 触发 high_memory
        transitions = mgr.evaluate({"memory_percent": 95.0})
        names = {a.name for a in transitions}
        assert "high_memory" in names

        # 内存回落 → 恢复
        transitions = mgr.evaluate({"memory_percent": 30.0})
        assert any(a.name == "high_memory" and a.state == "resolved" for a in transitions)

    def test_queue_backlog_rule(self):
        mgr = build_default_alert_manager()
        # 90/100 = 90% ≥ 80% → 触发
        transitions = mgr.evaluate({"queue_size": 90, "max_queue_size": 100})
        assert any(a.name == "queue_backlog" for a in transitions)

        # 不触发
        transitions = mgr.evaluate({"queue_size": 10, "max_queue_size": 100})
        assert not any(a.name == "queue_backlog" and a.state == "firing" for a in transitions)

    def test_high_failure_rate_needs_min_sample(self):
        mgr = build_default_alert_manager()
        # 3 个样本失败 2 个，但样本不足 10，不触发
        transitions = mgr.evaluate({"task_succeeded": 1, "task_failed": 2})
        assert not any(a.name == "high_failure_rate" for a in transitions)

        # 100 个样本失败 40 个（40% ≥ 30%）→ 触发
        transitions = mgr.evaluate({"task_succeeded": 60, "task_failed": 40})
        assert any(a.name == "high_failure_rate" and a.state == "firing" for a in transitions)

    def test_high_latency_rule(self):
        mgr = build_default_alert_manager()
        transitions = mgr.evaluate({"request_latency_p99": 8.0})
        assert any(a.name == "high_latency" for a in transitions)

    def test_history_records_transitions(self):
        mgr = build_default_alert_manager()
        mgr.evaluate({"memory_percent": 95.0})   # firing
        mgr.evaluate({"memory_percent": 10.0})   # resolved
        history = mgr.recent_history()
        assert len(history) == 2
        assert history[0].state == "firing"
        assert history[1].state == "resolved"

    def test_active_alerts_only_firing(self):
        mgr = build_default_alert_manager()
        mgr.evaluate({"memory_percent": 95.0})
        assert [a.name for a in mgr.active_alerts()] == ["high_memory"]
        mgr.evaluate({"memory_percent": 10.0})
        assert mgr.active_alerts() == []
