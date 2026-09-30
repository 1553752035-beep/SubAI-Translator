# -*- coding: utf-8 -*-
"""
SubAI Translator —— 术语库与 Pipeline 单元测试
================================================

测试范围：
1. 术语库管理器（增删改查、导入导出、统计、优先级）
2. Pipeline 核心函数（时间戳格式化、文本规范化、断句）

说明：
- API 接口测试统一由 tests/test_api_server.py 覆盖（使用临时 DB + lifespan），
  避免真实 DB 状态泄漏与字段名（source_text/source）不一致问题。
- 本文件仅保留对 TerminologyManager 与 Pipeline 纯函数的单元测试。

运行方式：
    pytest tests/test_terminology.py -v
"""
import json
import os
import sys
import pytest

# 添加项目根目录到路径
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.db.terminology import TerminologyManager


# --------------------------------------------------------------------------- #
# 术语库测试
# --------------------------------------------------------------------------- #
class TestTerminologyManager:
    """术语库管理器测试"""

    @pytest.fixture
    def tm(self, tmp_path):
        """创建临时术语库"""
        db_path = str(tmp_path / "test_terminology.db")
        return TerminologyManager(db_path)

    def test_add_term(self, tm):
        """测试添加术语"""
        result = tm.add_term("这是测试", "This is a test", priority="high")
        assert result is True

    def test_match_exact(self, tm):
        """测试精确匹配"""
        tm.add_term("这是测试", "This is a test")
        result = tm.match("这是测试")
        assert result == "This is a test"

    def test_match_not_found(self, tm):
        """测试未匹配返回None"""
        result = tm.match("不存在的术语")
        assert result is None

    def test_update_existing_term(self, tm):
        """测试更新现有术语"""
        tm.add_term("这是测试", "Original translation")
        tm.add_term("这是测试", "Updated translation")

        result = tm.match("这是测试")
        assert result == "Updated translation"

    def test_delete_term(self, tm):
        """测试删除术语"""
        tm.add_term("这是测试", "This is a test")
        result = tm.delete_term("这是测试")
        assert result is True

        # 删除后应匹配不到
        result = tm.match("这是测试")
        assert result is None

    def test_delete_nonexistent(self, tm):
        """测试删除不存在的术语"""
        result = tm.delete_term("不存在的术语")
        assert result is False

    def test_list_terms(self, tm):
        """测试查询术语列表"""
        tm.add_term("术语1", "Translation 1", category="custom")
        tm.add_term("术语2", "Translation 2", category="domain")

        all_terms = tm.list_terms()
        assert len(all_terms) == 2

        # 按分类过滤
        custom_terms = tm.list_terms(category="custom")
        assert len(custom_terms) == 1
        assert custom_terms[0]["source"] == "术语1"

    def test_list_terms_with_keyword(self, tm):
        """测试关键词搜索"""
        tm.add_term("测试术语", "Test term")
        tm.add_term("另一个术语", "Another term")

        results = tm.list_terms(keyword="测试")
        assert len(results) == 1
        assert results[0]["source"] == "测试术语"

    def test_import_export_json(self, tm, tmp_path):
        """测试JSON导入导出"""
        # 添加一些术语
        tm.add_term("术语A", "Translation A", priority="high")
        tm.add_term("术语B", "Translation B", priority="medium")

        # 导出
        json_path = str(tmp_path / "terms.json")
        tm.export_to_json(json_path)

        # 验证文件存在且格式正确
        assert os.path.exists(json_path)
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 2

        # 创建新术语库并导入
        tm2 = TerminologyManager(str(tmp_path / "test2.db"))
        count = tm2.import_from_json(json_path)
        assert count == 2

        # 验证导入成功
        result = tm2.match("术语A")
        assert result == "Translation A"

    def test_get_stats(self, tm):
        """测试统计信息"""
        tm.add_term("术语1", "Translation 1")
        tm.add_term("术语2", "Translation 2")
        tm.add_term("术语3", "Translation 3", priority="high")

        # 模拟使用
        tm.match("术语1")
        tm.match("术语1")
        tm.match("术语2")

        stats = tm.get_stats()
        assert stats["total_terms"] == 3
        assert stats["total_usage"] == 3
        assert stats["by_priority"].get("medium", 0) == 2
        assert stats["by_priority"].get("high", 0) == 1

    def test_priority_levels(self, tm):
        """测试不同优先级"""
        tm.add_term("术语", "High priority", priority="high")
        tm.add_term("术语2", "Medium priority", priority="medium")
        tm.add_term("术语3", "Low priority", priority="low")

        terms = tm.list_terms()
        priorities = {t["source"]: t["priority"] for t in terms}
        assert priorities["术语"] == "high"
        assert priorities["术语2"] == "medium"
        assert priorities["术语3"] == "low"


# --------------------------------------------------------------------------- #
# 数据隔离测试（三期）
# --------------------------------------------------------------------------- #
class TestTerminologyIsolation:
    """多用户术语隔离与优先级测试"""

    @pytest.fixture
    def tm(self, tmp_path):
        return TerminologyManager(str(tmp_path / "iso_terminology.db"))

    def test_user_term_priority_over_system(self, tm):
        """用户术语优先于系统术语"""
        tm.add_term("术语", "系统翻译", user_id=None)
        tm.add_term("术语", "用户翻译", user_id="user1")

        # 用户匹配到自己的术语
        assert tm.match("术语", user_id="user1") == "用户翻译"
        # 其他用户匹配到系统术语
        assert tm.match("术语", user_id="user2") == "系统翻译"

    def test_list_terms_include_system(self, tm):
        """list_terms 支持系统术语 + 用户术语联合查询"""
        tm.add_term("系统", "sys", user_id=None)
        tm.add_term("用户", "usr", user_id="user1")

        # 仅用户自己的术语
        own = tm.list_terms(user_id="user1")
        assert len(own) == 1
        assert own[0]["source"] == "用户"

        # 系统术语 + 用户术语
        both = tm.list_terms(user_id="user1", include_system=True)
        assert len(both) == 2
        assert {t["source"] for t in both} == {"系统", "用户"}

    def test_delete_only_own_term(self, tm):
        """用户只能删除自己的术语，不影响系统术语"""
        tm.add_term("术语", "系统翻译", user_id=None)
        tm.add_term("术语", "用户翻译", user_id="user1")

        # 删除 user1 的术语
        assert tm.delete_term("术语", user_id="user1") is True
        # 系统术语仍存在
        assert tm.match("术语", user_id="user1") == "系统翻译"


# --------------------------------------------------------------------------- #
# Pipeline核心函数测试
# --------------------------------------------------------------------------- #
class TestPipelineFunctions:
    """Pipeline核心函数测试"""

    def test_fmt_ts(self):
        """测试时间戳格式化"""
        from src.pipeline import fmt_ts

        assert fmt_ts(0.0) == "00:00:00,000"
        assert fmt_ts(1.5) == "00:00:01,500"
        assert fmt_ts(60.0) == "00:01:00,000"
        assert fmt_ts(3661.5) == "01:01:01,500"

    def test_norm(self):
        """测试文本规范化"""
        from src.pipeline import _norm

        assert _norm("你好，世界") == "你好世界"
        assert _norm("Hello, World!") == "HelloWorld"
        assert _norm("测试  术语") == "测试术语"

    def test_regroup_short_text(self):
        """测试短文本合并"""
        from src.pipeline import _regroup

        # 模拟Whisper返回的短段落
        class MockSegment:
            def __init__(self, start, end, text):
                self.start = start
                self.end = end
                self.text = text

        segments = [
            MockSegment(0, 1, "这是"),
            MockSegment(1, 2, "测试"),
            MockSegment(2, 3, "文本"),
        ]

        result = _regroup(segments)
        # 短文本应该被合并
        assert len(result) <= 3


# --------------------------------------------------------------------------- #
# 运行入口
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
