# -*- coding: utf-8 -*-
"""翻译引擎适配层测试（src/translate_engines.py）。

为什么不测「翻译得好不好」
--------------------------
那需要真实 Key 和人工评估，不适合进单测。这里固定的是**工程契约**，
而这几条恰恰是最容易出错、出错又最难发现的：

1. **返回条数必须等于输入条数**。不等时若继续用，字幕会整体错位 ——
   比「译得不准」严重得多，用户几乎无法察觉错在哪。
2. **语言代码映射**。DeepL 要 ZH-HANS/EN-US，Google 要 zh-CN；
   传内部代码 zh/en 会被拒或译错语言。
3. **HTML 实体还原**。Google 返回 It&#39;s，不还原字幕里就是乱码。
4. **空白输入不发请求**。空列表直接返回，避免打无意义的 API 调用。
"""
import pytest

from src import translate_engines as te


# ---------------- 语言代码映射 ----------------

@pytest.mark.parametrize("internal,deepl", [
    ("zh", "ZH-HANS"),
    ("zh-cn", "ZH-HANS"),
    ("zh-tw", "ZH-HANT"),
    ("en", "EN-US"),
    ("ja", "JA"),
    ("pt", "PT-PT"),
])
def test_deepl_lang_mapping(internal, deepl):
    """DeepL 的语言代码和内部代码不同，映射错就是译错语言。"""
    req = te.build_deepl_request(["x"], internal, "en", "K")
    assert req["json"]["source_lang"] == deepl


@pytest.mark.parametrize("internal,google", [
    ("zh", "zh-CN"),
    ("zh-tw", "zh-TW"),
    ("ja", "ja"),
])
def test_google_lang_mapping(internal, google):
    req = te.build_google_request(["x"], internal, "en", "K")
    assert req["json"]["source"] == google


def test_target_lang_mapping():
    assert te.build_deepl_request(["x"], None, "zh", "K")["json"]["target_lang"] == "ZH-HANS"
    assert te.build_google_request(["x"], None, "zh", "K")["json"]["target"] == "zh-CN"


def test_unknown_lang_passed_through_uppercased():
    """未知代码保留原值（大写）让服务端报错，不悄悄替换成默认语言。

    理由：悄悄替换会让用户拿着「译成了英文」的字幕而不知道哪里错了。
    """
    req = te.build_deepl_request(["x"], "xx", "en", "K")
    assert req["json"]["source_lang"] == "XX"


def test_auto_source_omitted():
    """source=auto 时不传 source_lang，让服务端自动检测。"""
    assert "source_lang" not in te.build_deepl_request(["x"], "auto", "en", "K")["json"]
    assert "source" not in te.build_google_request(["x"], "auto", "en", "K")["json"]


# ---------------- 请求构造 ----------------

def test_deepl_free_vs_pro_endpoint():
    assert "api-free" in te.build_deepl_request(["x"], None, "en", "K", tier="free")["url"]
    assert "api-free" not in te.build_deepl_request(["x"], None, "en", "K", tier="pro")["url"]


def test_deepl_auth_header_format():
    """DeepL 用 "DeepL-Auth-Key <key>"，不是 Bearer。"""
    h = te.build_deepl_request(["x"], None, "en", "KEY")["headers"]
    assert h["Authorization"] == "DeepL-Auth-Key KEY"


def test_batch_preserves_order_and_count():
    texts = ["一", "二", "三"]
    assert te.build_deepl_request(texts, None, "en", "K")["json"]["text"] == texts
    assert te.build_google_request(texts, None, "en", "K")["json"]["q"] == texts


def test_glossary_id_included():
    req = te.build_deepl_request(["x"], None, "en", "K", glossary_id="G1")
    assert req["json"]["glossary_id"] == "G1"


# ---------------- 响应解析 ----------------

def test_parse_deepl_ok():
    data = {"translations": [{"text": "Hello"}, {"text": "World"}]}
    assert te.parse_deepl_response(data, 2) == ["Hello", "World"]


def test_parse_deepl_count_mismatch_raises():
    """条数不一致必须报错 —— 继续用会让字幕和时间轴整体错位。"""
    data = {"translations": [{"text": "Hello"}]}
    with pytest.raises(te.TranslateError) as ei:
        te.parse_deepl_response(data, 3)
    assert "不一致" in str(ei.value)
    assert "错位" in str(ei.value)


def test_parse_google_ok():
    data = {"data": {"translations": [{"translatedText": "你好"},
                                        {"translatedText": "世界"}]}}
    assert te.parse_google_response(data, 2) == ["你好", "世界"]


def test_parse_google_unescapes_html_entities():
    """Google 返回 It&#39;s，不还原字幕里就是乱码。"""
    data = {"data": {"translations": [{"translatedText": "It&#39;s &amp; ok"}]}}
    assert te.parse_google_response(data, 1) == ["It's & ok"]


def test_parse_google_count_mismatch_raises():
    data = {"data": {"translations": [{"translatedText": "one"}]}}
    with pytest.raises(te.TranslateError):
        te.parse_google_response(data, 2)


def test_parse_empty_response_is_mismatch():
    with pytest.raises(te.TranslateError):
        te.parse_deepl_response({}, 1)


# ---------------- 统一入口 ----------------

def test_empty_texts_returns_empty_without_request():
    """空输入不发请求（避免无意义的 API 调用与计费）。"""
    assert te.translate_batch("deepl", [], None, "en", api_key="K") == []
    assert te.translate_batch("google", [], None, "en", api_key="K") == []


def test_missing_key_raises_actionable():
    with pytest.raises(te.TranslateError) as ei:
        te.translate_batch("deepl", ["x"], None, "en", api_key="")
    assert "API Key" in str(ei.value)


def test_unknown_engine_raises():
    with pytest.raises(te.TranslateError) as ei:
        te.translate_batch("nope", ["x"], None, "en", api_key="K")
    assert "未知翻译引擎" in str(ei.value)


def test_engines_registry_has_both():
    assert set(te.ENGINES) == {"deepl", "google"}
    for v in te.ENGINES.values():
        assert v["name"] and v["doc"]