# -*- coding: utf-8 -*-
"""免费免 Key 翻译渠道测试（src/translate_free.py）。

重点覆盖三件最容易出错的事：
1. **条数对齐**——字幕行与时间轴一一对应，错位比译不准严重得多。
2. **空行处理**——空行不能占配额，也不能让服务端返回不同条数。
3. **分块不丢不重**——超限切批时每一行都要落到正确位置。
"""
import pytest

from src import translate_free as tf


# ---------------- 语言映射 ----------------

@pytest.mark.parametrize("src,expect", [
    ("zh", "zh"), ("zh-CN", "zh"), ("ZH", "zh"),
    ("zh-TW", "zh-TW"), ("zh-Hant", "zh-TW"),
    ("en", "en"), ("EN", "en"), ("ja", "ja"), ("ko", "ko"),
])
def test_norm_lang(src, expect):
    assert tf._norm_lang(src) == expect


def test_norm_lang_unknown_passthrough():
    """未知语言原样小写透传，让服务端自己判，不要擅自映射成 en。"""
    assert tf._norm_lang("xx-YY") == "xx-yy"
    assert tf._norm_lang("") == ""


# ---------------- 请求构造 ----------------

def test_build_tencent_request():
    req = tf.build_tencent_request(["你好"], "zh", "en")
    assert req["header"]["fn"] == "auto_translation"
    assert req["source"] == {"lang": "zh", "text_list": ["你好"]}
    assert req["target"] == {"lang": "en"}
    assert req["type"] == "plain"


# ---------------- 响应解析：条数对齐是硬约束 ----------------

def test_parse_ok():
    data = {"header": {"ret_code": "succ"}, "auto_translation": ["a", "b"]}
    assert tf.parse_tencent_response(data, 2) == ["a", "b"]


def test_parse_count_mismatch_raises():
    """返回 2 条但期望 3 条 —— 必须报错，绝不能补空串凑数。

    补空串会让第 3 行字幕变成空白，而时间轴照常推进，
    成片里表现为「某句话凭空消失」，且极难定位。
    """
    data = {"header": {"ret_code": "succ"}, "auto_translation": ["a", "b"]}
    with pytest.raises(tf.FreeTranslateError) as ei:
        tf.parse_tencent_response(data, 3)
    assert "条数不符" in str(ei.value)


def test_parse_failure_code_raises():
    data = {"header": {"ret_code": "fail"}, "auto_translation": []}
    with pytest.raises(tf.FreeTranslateError):
        tf.parse_tencent_response(data, 0)


def test_parse_missing_field_raises():
    with pytest.raises(tf.FreeTranslateError) as ei:
        tf.parse_tencent_response({"header": {"ret_code": "succ"}}, 1)
    assert "auto_translation" in str(ei.value)


def test_parse_none_becomes_empty_string():
    """null 项转空串：字幕宁可空一行，也不能出现字面量 None。"""
    data = {"header": {"ret_code": "succ"}, "auto_translation": [None, "x"]}
    assert tf.parse_tencent_response(data, 2) == ["", "x"]


# ---------------- 分块 ----------------

def test_chunk_under_limit():
    assert tf._chunk(["x"] * 10) == [(0, 10)]


def test_chunk_splits_by_count():
    spans = tf._chunk(["x"] * (tf.MAX_LINES_PER_REQUEST + 1))
    assert len(spans) == 2
    assert spans[0] == (0, tf.MAX_LINES_PER_REQUEST)


def test_chunk_splits_by_chars():
    """按字数切批：单行很长时不能等到条数上限。"""
    long = "字" * (tf.MAX_CHARS_PER_REQUEST // 2 + 10)
    spans = tf._chunk([long, long, long])
    assert len(spans) >= 2
    # 每批总字数不超限（单行自身超限除外）
    for a, b in spans:
        if b - a > 1:
            assert sum(len(x) for x in [long] * (b - a)) <= tf.MAX_CHARS_PER_REQUEST


def test_chunk_single_oversized_line():
    """单行就超过总字数上限时，也必须前进，不能死循环。"""
    spans = tf._chunk(["字" * 99999])
    assert spans == [(0, 1)]


def test_chunk_empty():
    assert tf._chunk([]) == []


def test_chunk_covers_all_exactly():
    """所有区间必须首尾相接、完整覆盖，不丢不重。"""
    texts = ["x%d" % i for i in range(123)]
    spans = tf._chunk(texts)
    assert spans[0][0] == 0
    assert spans[-1][1] == len(texts)
    for i in range(len(spans) - 1):
        assert spans[i][1] == spans[i + 1][0]


# ---------------- 空行本地处理 ----------------

def test_blank_lines_local_only(monkeypatch):
    """空行/纯空格不参与请求，但必须原样回到原位置。"""
    sent = []

    def fake_post(url, json=None, **kw):
        sent.append(json["source"]["text_list"])
        class R:
            status_code = 200
            def json(self):
                return {"header": {"ret_code": "succ"},
                        "auto_translation": ["T%d" % i for i in range(len(json["source"]["text_list"]))]}
        return R()

    class FakeClient:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        post = staticmethod(fake_post)

    monkeypatch.setattr(tf.httpx, "Client", FakeClient)
    out = tf.tencent_translate_free(["a", "", "  ", "b"], "zh", "en")

    # 实际只发了 2 条
    assert sent == [["a", "b"]]
    # 空行原样保留在原位置
    assert out[1] == ""
    assert out[2] == "  "
    assert out[0] == "T0"
    assert out[3] == "T1"


def test_all_blank_no_request(monkeypatch):
    """全是空行时不该发请求。"""
    called = []
    monkeypatch.setattr(tf.httpx, "Client",
                        lambda **kw: called.append(1))
    out = tf.tencent_translate_free(["", "  ", "\n"], "zh", "en")
    assert called == []
    assert out == ["", "  ", "\n"]


def test_empty_input():
    assert tf.tencent_translate_free([], "zh", "en") == []


# ---------------- 错误处理 ----------------

def test_http_error_raises(monkeypatch):
    class FakeClient:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        @staticmethod
        def post(url, json=None, **kw):
            class R:
                status_code = 500
                text = "server error"
            return R()
    monkeypatch.setattr(tf.httpx, "Client", FakeClient)
    with pytest.raises(tf.FreeTranslateError) as ei:
        tf.tencent_translate_free(["a"], "zh", "en")
    assert "HTTP 500" in str(ei.value)


def test_unknown_engine_raises():
    with pytest.raises(tf.FreeTranslateError):
        tf.translate_free("no_such", ["a"], "zh", "en")


def test_engine_alias():
    """别名都要能路由到腾讯。"""
    assert set(tf.FREE_ENGINES) == {"tencent_free"}
    assert tf.FREE_ENGINES["tencent_free"]["needs_key"] is False


# ---------------- 真实网络（可跳过）----------------

@pytest.mark.network
def test_real_tencent_translate():
    out = tf.tencent_translate_free(["你好世界"], "zh", "en")
    assert len(out) == 1
    assert out[0].strip()


@pytest.mark.network
def test_real_multiline_alignment():
    """真实多条翻译：条数必须对得上，顺序不能乱。"""
    texts = ["第一句话", "第二句话", "第三句话"]
    out = tf.tencent_translate_free(texts, "zh", "en")
    assert len(out) == 3
    assert all(x.strip() for x in out)