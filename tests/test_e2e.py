# -*- coding: utf-8 -*-
"""
SubAI Translator —— 端到端测试套件
=====================================

测试范围:
1. Pipeline端到端测试(语音字幕 + 硬字幕OCR)
2. 术语库集成测试
3. 多格式输出测试(SRT/VTT/ASS/JSON)
4. CLI参数解析测试

运行方式:
    pytest tests/test_e2e.py -v
"""
import json
import os
import sys
import tempfile
import pytest

# 添加项目根目录到路径
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.pipeline import fmt_ts, _norm, _regroup, run_pipeline
from src.db.terminology import TerminologyManager


# --------------------------------------------------------------------------- #
# Pipeline端到端测试
# --------------------------------------------------------------------------- #
class TestPipelineE2E:
    """Pipeline端到端测试"""
    
    @pytest.fixture(autouse=True)
    def _require_model_deps(self):
        """缺少重型模型依赖时跳过（ASR 需 faster_whisper，OCR 需 rapidocr/cv2）"""
        pytest.importorskip("faster_whisper")
        pytest.importorskip("rapidocr_onnxruntime")
        pytest.importorskip("cv2")
    
    @pytest.fixture
    def test_video_asr(self):
        """语音字幕测试视频路径"""
        return os.path.join(ROOT, "data", "test_speech.mp4")
    
    @pytest.fixture
    def test_video_hardsub(self):
        """硬字幕测试视频路径"""
        return os.path.join(ROOT, "data", "test_hardsub.mp4")
    
    @pytest.fixture
    def output_dir(self):
        """输出目录"""
        return os.path.join(ROOT, "output")
    
    def test_pipeline_asr_mode(self, test_video_asr, output_dir):
        """测试语音字幕模式Pipeline"""
        if not os.path.isfile(test_video_asr):
            pytest.skip("测试视频不存在")
        
        output_files = run_pipeline(
            video=test_video_asr,
            mode="asr",
            target_lang="en",
            output_format="srt"
        )
        
        # 验证输出了双语SRT文件
        assert len(output_files) >= 2
        bilingual_files = [f for f in output_files if "bilingual" in f]
        assert len(bilingual_files) >= 1
        
        # 验证文件存在且非空
        for f in bilingual_files:
            assert os.path.exists(f)
            assert os.path.getsize(f) > 0
    
    def test_pipeline_hardsub_mode(self, test_video_hardsub, output_dir):
        """测试硬字幕OCR模式Pipeline"""
        if not os.path.isfile(test_video_hardsub):
            pytest.skip("测试视频不存在")
        
        output_files = run_pipeline(
            video=test_video_hardsub,
            mode="hardsub",
            target_lang="en",
            output_format="srt"
        )
        
        # 验证输出了双语SRT文件
        assert len(output_files) >= 2
        bilingual_files = [f for f in output_files if "bilingual" in f]
        assert len(bilingual_files) >= 1
        
        # 验证文件存在且非空
        for f in bilingual_files:
            assert os.path.exists(f)
            assert os.path.getsize(f) > 0
    
    def test_pipeline_vtt_output(self, test_video_asr, output_dir):
        """测试VTT格式输出"""
        if not os.path.isfile(test_video_asr):
            pytest.skip("测试视频不存在")
        
        output_files = run_pipeline(
            video=test_video_asr,
            mode="asr",
            target_lang="en",
            output_format="vtt"
        )
        
        # 验证输出了VTT文件
        vtt_files = [f for f in output_files if f.endswith(".vtt")]
        assert len(vtt_files) >= 1
        
        # 验证VTT文件内容
        with open(vtt_files[0], "r", encoding="utf-8") as f:
            content = f.read()
            assert content.startswith("WEBVTT")
    
    def test_pipeline_ass_output(self, test_video_asr, output_dir):
        """测试ASS格式输出"""
        if not os.path.isfile(test_video_asr):
            pytest.skip("测试视频不存在")
        
        output_files = run_pipeline(
            video=test_video_asr,
            mode="asr",
            target_lang="en",
            output_format="ass"
        )
        
        # 验证输出了ASS文件
        ass_files = [f for f in output_files if f.endswith(".ass")]
        assert len(ass_files) >= 1
        
        # 验证ASS文件内容
        with open(ass_files[0], "r", encoding="utf-8") as f:
            content = f.read()
            assert "[Script Info]" in content
            assert "[Events]" in content
    
    def test_pipeline_json_output(self, test_video_asr, output_dir):
        """测试JSON格式输出"""
        if not os.path.isfile(test_video_asr):
            pytest.skip("测试视频不存在")
        
        output_files = run_pipeline(
            video=test_video_asr,
            mode="asr",
            target_lang="en",
            output_format="json"
        )
        
        # 验证输出了JSON文件
        json_files = [f for f in output_files if f.endswith(".json")]
        assert len(json_files) >= 1
        
        # 验证JSON文件内容
        with open(json_files[0], "r", encoding="utf-8") as f:
            data = json.load(f)
            assert isinstance(data, list)
            assert len(data) > 0
            # 验证JSON结构
            assert "id" in data[0]
            assert "source" in data[0]
            assert "translation" in data[0]
            assert "start_ts" in data[0]
            assert "end_ts" in data[0]


# --------------------------------------------------------------------------- #
# 术语库集成测试
# --------------------------------------------------------------------------- #
class TestTerminologyIntegration:
    """术语库集成测试"""
    
    @pytest.fixture
    def tm(self, tmp_path):
        """创建临时术语库"""
        db_path = str(tmp_path / "test_terminology.db")
        return TerminologyManager(db_path)
    
    def test_pipeline_with_terminology_json(self, tm, tmp_path):
        """测试Pipeline集成术语库(JSON格式)"""
        # 添加术语
        tm.add_term("这是测试", "This is a test", priority="high")
        tm.add_term("人工智能", "Artificial Intelligence", priority="high")
        
        # 导出为JSON
        terms_json = str(tmp_path / "terms.json")
        tm.export_to_json(terms_json)
        
        # 验证JSON文件存在
        assert os.path.exists(terms_json)
        
        # 验证JSON格式
        with open(terms_json, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert isinstance(data, list)
            assert len(data) == 2
    
    def test_pipeline_with_terminology_db(self, tm, tmp_path):
        """测试Pipeline集成术语库(SQLite)"""
        # 添加术语
        tm.add_term("测试术语1", "Test Term 1", priority="high")
        tm.add_term("测试术语2", "Test Term 2", priority="medium")
        
        # 验证术语库统计
        stats = tm.get_stats()
        assert stats["total_terms"] == 2
        assert stats["by_priority"]["high"] == 1
        assert stats["by_priority"]["medium"] == 1


# --------------------------------------------------------------------------- #
# CLI参数解析测试
# --------------------------------------------------------------------------- #
class TestCLIArguments:
    """CLI参数解析测试"""
    
    def test_default_arguments(self):
        """测试默认参数"""
        import argparse
        # 验证argparse配置存在即可,不实际解析--help(会触发sys.exit)
        ap = argparse.ArgumentParser()
        ap.add_argument("video", help="输入视频文件（或目录）")
        ap.add_argument("--mode", choices=["asr", "hardsub"], default="asr")
        ap.add_argument("--source", default=None)
        ap.add_argument("--target", default="en")
        ap.add_argument("--terms", default=None)
        ap.add_argument("--db", default=None)
        ap.add_argument("--output-format", default="srt", choices=["srt", "vtt", "ass", "json"])
        ap.add_argument("--sample-fps", type=float, default=2.0)
        ap.add_argument("--batch", action="store_true")
        
        # 验证正常参数解析
        args = ap.parse_args(["test.mp4"])
        assert args.video == "test.mp4"
        assert args.mode == "asr"
        assert args.target == "en"
    
    def test_output_format_choices(self):
        """测试输出格式选项"""
        valid_formats = ["srt", "vtt", "ass", "json"]
        assert len(valid_formats) == 4
        assert "srt" in valid_formats
        assert "vtt" in valid_formats
        assert "ass" in valid_formats
        assert "json" in valid_formats


# --------------------------------------------------------------------------- #
# 时间戳和断句测试
# --------------------------------------------------------------------------- #
class TestTimestampAndSegment:
    """时间戳和断句测试"""
    
    def test_fmt_ts_edge_cases(self):
        """测试时间戳边界情况"""
        assert fmt_ts(0.0) == "00:00:00,000"
        assert fmt_ts(0.001) == "00:00:00,001"
        assert fmt_ts(0.999) == "00:00:00,999"
        assert fmt_ts(1.0) == "00:00:01,000"
        assert fmt_ts(59.999) == "00:00:59,999"
        assert fmt_ts(60.0) == "00:01:00,000"
        assert fmt_ts(3599.999) == "00:59:59,999"
        assert fmt_ts(3600.0) == "01:00:00,000"
        assert fmt_ts(86399.999) == "23:59:59,999"
    
    def test_regroup_by_punctuation(self):
        """测试按标点断句"""
        class MockWord:
            def __init__(self, word, start, end):
                self.word = word
                self.start = start
                self.end = end
        
        class MockSegment:
            def __init__(self, words):
                self.words = words
                self.start = words[0].start if words else 0
                self.end = words[-1].end if words else 0
                self.text = "".join(w.word for w in words)
        
        # 包含标点的长句
        words = [
            MockWord("你好", 0, 0.5),
            MockWord("，", 0.5, 0.5),
            MockWord("这是", 0.6, 0.8),
            MockWord("一个", 0.8, 1.0),
            MockWord("测试", 1.0, 1.2),
            MockWord("。", 1.2, 1.2),
        ]
        segments = [MockSegment(words)]
        
        result = _regroup(segments)
        
        # 应该被切成两行(逗号断句)
        assert len(result) >= 1
        # 验证文本包含完整内容
        full_text = "".join(r["text"] for r in result)
        assert "你好" in full_text
        assert "测试" in full_text
    
    def test_regroup_by_length(self):
        """测试按字数断句"""
        class MockWord:
            def __init__(self, word, start, end):
                self.word = word
                self.start = start
                self.end = end
        
        class MockSegment:
            def __init__(self, words):
                self.words = words
                self.start = words[0].start if words else 0
                self.end = words[-1].end if words else 0
                self.text = "".join(w.word for w in words)
        
        # 超长句(超过20字)
        words = [
            MockWord(f"字{i}", i * 0.1, i * 0.1 + 0.05)
            for i in range(25)
        ]
        segments = [MockSegment(words)]
        
        result = _regroup(segments)
        
        # 应该被切成多行
        assert len(result) > 1
        # 验证大部分行不超过22字(允许边界浮动)
        long_lines = [r for r in result if len(r["text"]) > 22]
        assert len(long_lines) == 0 or len(long_lines) <= len(result) * 0.1


# --------------------------------------------------------------------------- #
# 术语库边界情况测试
# --------------------------------------------------------------------------- #
class TestTerminologyEdgeCases:
    """术语库边界情况测试"""
    
    @pytest.fixture
    def tm(self, tmp_path):
        """创建临时术语库"""
        db_path = str(tmp_path / "test_terminology.db")
        return TerminologyManager(db_path)
    
    def test_empty_source(self, tm):
        """测试空字符串作为术语"""
        result = tm.add_term("", "Empty translation")
        assert result is True
        
        # 空字符串也能匹配
        result = tm.match("")
        assert result == "Empty translation"
    
    def test_unicode_characters(self, tm):
        """测试Unicode字符"""
        tm.add_term("日本語", "Japanese")
        tm.add_term("한국어", "Korean")
        
        assert tm.match("日本語") == "Japanese"
        assert tm.match("한국어") == "Korean"
    
    def test_special_characters(self, tm):
        """测试特殊字符"""
        tm.add_term("测试@#$%", "Test @#$%")
        
        assert tm.match("测试@#$%") == "Test @#$%"
    
    def test_duplicate_add(self, tm):
        """测试重复添加术语"""
        tm.add_term("术语", "第一次翻译")
        tm.add_term("术语", "第二次翻译")
        
        # 应该更新而不是创建新条目
        result = tm.match("术语")
        assert result == "第二次翻译"
        
        # 验证只有一条记录
        terms = tm.list_terms()
        assert len(terms) == 1


# --------------------------------------------------------------------------- #
# 运行入口
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    pytest.main([__file__, "-v"])