# -*- coding: utf-8 -*-
"""
SubAI Translator —— 阈值告警引擎（三期：监控与告警）
======================================================

基于「规则条件 + 状态机」的轻量告警：
1. 每个规则定义一个 `evaluate(snapshot) -> Optional[str]` 条件，
   返回非空字符串表示告警触发（返回值为告警消息），None 表示正常。
2. AlertManager 跟踪每条规则的状态（firing / resolved），
   在状态跃迁时记录一次历史，便于追查。
3. 告警同时写入日志，支持后台定时巡检（由 server 的 lifespan 启动）。

设计要点：
- 不依赖外部告警服务（Prometheus Alertmanager / 邮件网关），
  仅保留「触发即记录 + 可查询」能力，后续可无缝接入 Webhook。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class Alert:
    """一条告警的当前状态"""
    name: str
    severity: str
    message: str
    state: str = "firing"  # firing / resolved
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "severity": self.severity,
            "message": self.message,
            "state": self.state,
            "timestamp": self.timestamp,
        }


@dataclass
class AlertRule:
    """告警规则定义"""
    name: str
    severity: str
    condition: Callable[[dict], Optional[str]]
    description: str


# --------------------------------------------------------------------------- #
# 内置规则
# --------------------------------------------------------------------------- #

def _rule_high_memory(snapshot: dict) -> Optional[str]:
    cfg = _cfg().monitoring
    percent = snapshot.get("memory_percent")
    if percent is not None and percent >= cfg.alert_memory_percent:
        return f"内存使用率 {percent:.1f}% 超过阈值 {cfg.alert_memory_percent}%"
    return None


def _rule_queue_backlog(snapshot: dict) -> Optional[str]:
    cfg = _cfg().monitoring
    queue_size = snapshot.get("queue_size") or 0
    max_size = snapshot.get("max_queue_size") or 0
    if max_size > 0 and (queue_size / max_size) * 100 >= cfg.alert_queue_percent:
        return f"任务队列积压 {queue_size}/{max_size}，超过阈值 {cfg.alert_queue_percent}%"
    return None


def _rule_high_failure_rate(snapshot: dict) -> Optional[str]:
    cfg = _cfg().monitoring
    succeeded = snapshot.get("task_succeeded") or 0
    failed = snapshot.get("task_failed") or 0
    total = succeeded + failed
    # 样本太少时不判定，避免偶发失败误报
    if total >= 10 and failed / total >= cfg.alert_failure_rate:
        return f"任务失败率 {failed}/{total} 超过阈值 {cfg.alert_failure_rate:.0%}"
    return None


def _rule_high_latency(snapshot: dict) -> Optional[str]:
    cfg = _cfg().monitoring
    p99 = snapshot.get("request_latency_p99")
    if p99 is not None and p99 >= cfg.alert_latency_seconds:
        return f"请求 P99 延迟 {p99:.2f}s 超过阈值 {cfg.alert_latency_seconds}s"
    return None


def _cfg():
    """动态读取配置（避免热重载后引用失效）"""
    from src.config import config
    return config


def build_default_rules() -> list[AlertRule]:
    """构建默认告警规则集"""
    return [
        AlertRule("high_memory", "warning", _rule_high_memory, "内存使用率过高"),
        AlertRule("queue_backlog", "warning", _rule_queue_backlog, "任务队列积压"),
        AlertRule("high_failure_rate", "critical", _rule_high_failure_rate, "任务失败率过高"),
        AlertRule("high_latency", "warning", _rule_high_latency, "请求延迟过高"),
    ]


# --------------------------------------------------------------------------- #
# 告警管理器
# --------------------------------------------------------------------------- #

class AlertManager:
    """跟踪规则状态并记录告警跃迁历史"""

    def __init__(self, rules: Optional[list[AlertRule]] = None, history_limit: int = 200):
        self.rules = rules or build_default_rules()
        self.history_limit = history_limit
        self._alerts: dict[str, Alert] = {}
        self._history: list[Alert] = []

    def evaluate(self, snapshot: dict) -> list[Alert]:
        """
        评估所有规则，返回本次发生状态跃迁的告警列表。

        状态机：
        - 首次触发 -> firing，记录历史 + 日志
        - 持续触发 -> 不重复记录
        - 触发后恢复 -> resolved，记录历史 + 日志
        """
        transitions: list[Alert] = []
        for rule in self.rules:
            try:
                message = rule.condition(snapshot)
            except Exception as e:  # noqa: BLE001
                logger.warning("告警规则 %s 评估失败: %s", rule.name, e)
                continue

            current = self._alerts.get(rule.name)

            if message is not None:
                if current is None or current.state != "firing":
                    alert = Alert(rule.name, rule.severity, message, state="firing")
                    self._alerts[rule.name] = alert
                    self._record(alert)
                    transitions.append(alert)
                    logger.warning("[告警] %s(%s): %s", rule.name, rule.severity, message)
                else:
                    # 持续触发：刷新消息与时间，但不重复记历史
                    current.message = message
                    current.timestamp = time.time()
            else:
                if current is not None and current.state == "firing":
                    resolved = Alert(
                        rule.name, rule.severity, "已恢复", state="resolved"
                    )
                    self._alerts[rule.name] = resolved
                    self._record(resolved)
                    transitions.append(resolved)
                    logger.info("[告警恢复] %s 已恢复", rule.name)

        return transitions

    def active_alerts(self) -> list[Alert]:
        """当前处于 firing 状态的告警"""
        return [a for a in self._alerts.values() if a.state == "firing"]

    def recent_history(self, limit: Optional[int] = None) -> list[Alert]:
        """最近告警历史（含触发与恢复）"""
        n = limit or self.history_limit
        return list(self._history[-n:])

    def _record(self, alert: Alert) -> None:
        self._history.append(alert)
        if len(self._history) > self.history_limit:
            self._history = self._history[-self.history_limit:]


def build_default_alert_manager() -> AlertManager:
    """构建带默认规则的告警管理器"""
    return AlertManager(build_default_rules())
