# -*- coding: utf-8 -*-
"""四期 4.6 数据分析 —— 统计准确性 + 报表导出测试。"""
from __future__ import annotations

import asyncio
import io
import json
import time
import zipfile

from src.analytics import build_report, export_pdf, export_xlsx, quality, summary
from src.db.tasks import TaskManager


def run(coro):
    return asyncio.run(coro)


def seed(tmp_path):
    """造 4 个任务：2 成功（其一有失败行）、1 失败、1 待处理。"""
    db = str(tmp_path / "tasks.db")
    manager = TaskManager(db)

    async def build():
        await manager.initialize()
        now = time.time()
        await manager.create_task("t1", "a.mp4", target_lang="en", user_id="u1")
        await manager.update_task("t1", status="completed", progress=1.0,
                                  metrics={"lines_total": 100, "lines_failed": 0, "terms_hit": 5,
                                           "cache_hits": 20, "llm_requests": 8, "files": 1})
        await manager.create_task("t2", "b.mp4", target_lang="zh", user_id="u1")
        await manager.update_task("t2", status="completed", progress=1.0,
                                  metrics={"lines_total": 50, "lines_failed": 5, "terms_hit": 0,
                                           "cache_hits": 0, "llm_requests": 5, "files": 2})
        await manager.create_task("t3", "c.mp4", target_lang="en", user_id="u1")
        await manager.update_task("t3", status="failed", error_message="翻译后端不可用",
                                  metrics={"lines_total": 10, "lines_failed": 10, "terms_hit": 0,
                                           "cache_hits": 0, "llm_requests": 1, "files": 1})
        await manager.create_task("t4", "d.mp4", target_lang="ja", user_id="u1")
        await manager.close()

    run(build())
    return db


class TestSummary:
    def test_counts_and_rates(self, tmp_path):
        db = seed(tmp_path)
        data = run(summary(db, days=30))
        t = data["tasks"]
        assert t["total"] == 4
        assert t["by_status"]["completed"] == 2 and t["by_status"]["failed"] == 1
        assert t["by_status"]["pending"] == 1
        assert t["success_rate"] == round(2 / 3, 4)
        assert t["by_target_lang"]["en"] == 2
        v = data["volume"]
        assert v["lines_total"] == 160          # 100 + 50 + 10
        assert v["lines_failed"] == 15          # 0 + 5 + 10
        assert v["terms_hit"] == 5
        assert v["cache_hits"] == 20
        assert v["llm_requests"] == 14
        assert v["output_files"] == 4
        assert v["cache_hit_rate"] == round(20 / 160, 4)
        assert v["line_failure_rate"] == round(15 / 160, 4)
        cov = data["coverage"]
        assert cov["tasks_with_metrics"] == 3 and cov["tasks_without_metrics"] == 1
        assert data["daily"] and sum(d["total"] for d in data["daily"]) == 4

    def test_empty_db_is_safe(self, tmp_path):
        data = run(summary(str(tmp_path / "missing.db"), days=30))
        assert data["tasks"]["total"] == 0
        assert data["volume"]["lines_total"] == 0
        assert data["tasks"]["success_rate"] == 1.0


class TestQuality:
    def test_failure_reasons_and_partial(self, tmp_path):
        db = seed(tmp_path)
        data = run(quality(db, days=30))
        assert data["tasks"]["total"] == 4
        assert data["tasks"]["clean"] == 1        # t1 全部成功
        assert data["tasks"]["partial"] == 1      # t2 部分失败
        assert data["tasks"]["failed"] == 1
        assert data["lines"]["failure_rate"] == round(15 / 160, 4)
        assert data["top_failure_reasons"][0]["reason"] == "翻译后端不可用"
        # 拿不到的数据如实留空，不推测
        assert data["unavailable_metrics"]["asr_confidence_avg"] is None


class TestExports:
    def test_xlsx_is_valid_and_contains_values(self, tmp_path):
        db = seed(tmp_path)
        data = run(summary(db, days=30))
        blob = export_xlsx("使用统计报表", data)
        assert blob[:2] == b"PK"                      # zip 容器
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            names = set(z.namelist())
            assert "[Content_Types].xml" in names
            assert "xl/workbook.xml" in names
            assert "xl/worksheets/sheet1.xml" in names
            sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
            assert "使用统计报表" in z.read("xl/workbook.xml").decode("utf-8")
            assert "lines_total" in sheet
            assert ">160<" in sheet                   # 数值以数字单元格写入

    def test_pdf_header(self, tmp_path):
        db = seed(tmp_path)
        data = run(summary(db, days=30))
        blob = export_pdf("使用统计报表", data)
        assert blob[:5] == b"%PDF-"
        assert len(blob) > 2000                     # 至少是一页真内容

    def test_html_contains_numbers(self, tmp_path):
        db = seed(tmp_path)
        data = run(summary(db, days=30))
        report = build_report("summary", data)
        assert "使用统计报表" in report["html"]
        assert "lines_total" in report["html"]
        assert report["pdf"][:5] == b"%PDF-"
        assert report["xlsx"][:2] == b"PK"

