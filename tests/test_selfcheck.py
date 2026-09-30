# -*- coding: utf-8 -*-
"""
SubAI Translator —— 环境自检测试
==================================

自检工具本身也要有保障：结构稳定、失败项必须给出可执行的修复建议、
退出码与 --json 输出可用于 CI。
"""
from __future__ import annotations

import json

from src import selfcheck


class TestSchema:
    def test_run_checks_returns_wellformed_items(self):
        results = selfcheck.run_checks(full=False)
        assert results
        for r in results:
            assert set(r) == {"section", "name", "status", "detail", "fix"}, r
            assert r["status"] in ("pass", "warn", "fail")
            assert r["section"] and r["name"] and r["detail"]

    def test_every_failure_has_actionable_fix(self):
        """不变式：任何 FAIL 都必须带上可执行的修复建议。"""
        for r in selfcheck.run_checks(full=False):
            if r["status"] == "fail":
                assert r["fix"], "失败项缺少修复建议: %s" % r["name"]


class TestReport:
    def test_exit_code_zero_when_no_failure(self, capsys):
        results = [
            {"section": "A", "name": "x", "status": "pass", "detail": "ok", "fix": ""},
            {"section": "A", "name": "y", "status": "warn", "detail": "meh", "fix": "可选"},
        ]
        assert selfcheck.report(results) == 0
        assert "关键项全部通过" in capsys.readouterr().out

    def test_exit_code_one_when_failure(self, capsys):
        results = [{"section": "A", "name": "x", "status": "fail", "detail": "bad", "fix": "修它"}]
        assert selfcheck.report(results) == 1
        assert "存在失败项" in capsys.readouterr().out


class TestMissingFfmpeg:
    def test_missing_ffmpeg_reports_fail_with_fix(self, monkeypatch):
        monkeypatch.setattr(selfcheck, "find_ffmpeg", lambda: "")
        out: list = []
        selfcheck.check_ffmpeg(out)
        assert out and out[0]["status"] == "fail"
        assert out[0]["fix"], "缺少修复建议"


class TestJsonMode:
    def test_json_output_parsable_and_exit_code_matches(self, capsys):
        code = selfcheck.main(["--json"])
        payload = json.loads(capsys.readouterr().out)
        assert isinstance(payload, list) and payload
        has_fail = any(r["status"] == "fail" for r in payload)
        assert code == (1 if has_fail else 0)
