# -*- coding: utf-8 -*-
"""四期 4.4 多语言支持：语言清单、能力矩阵与语言检测。

设计要点
1. **一个清单管三件事**：每种语言声明是否支持 ASR（识别）/ 翻译目标 / TTS（配音），
   避免"配置文件里写着支持、实际跑不通"这种假承诺。
2. **检测分两层**：先做文字系统（Unicode script）判定——中文/日文/韩文/俄文/阿拉伯文等
   一击即中；拉丁字母语言再用功能词评分 + 变音符号特征打分。
   不引入任何新依赖（绿色版要能直接跑）。
3. 检测结果带 confidence 与 candidates，调用方可自行设定阈值。
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Optional

# 统计检测器（软依赖）：文字系统层判定不了的拉丁语系交给它。
# 未安装时自动退回内置的停用词+变音符号打分，功能不缺失。
try:  # pragma: no cover - 取决于运行环境
    from langdetect import DetectorFactory, detect_langs as _ld_detect_langs

    DetectorFactory.seed = 0          # 固定随机种子：检测结果必须可复现
    _HAS_LANGDETECT = True
except Exception:  # noqa: BLE001
    _HAS_LANGDETECT = False

#: langdetect 的语言码 -> 本清单的码（其余按原样尝试归一）
_LD_ALIASES = {
    "zh-cn": "zh", "zh-tw": "zh-TW", "zh": "zh",
    "jw": "jv", "fil": "tl", "nb": "no", "nn": "no",
}


@dataclass(frozen=True)
class Language:
    """一种语言及其能力。asr / translate / tts 表示本项目在该语言上的实际能力。"""

    code: str
    name_en: str
    name_zh: str
    native: str
    script: str
    asr: bool = False
    translate: bool = True
    tts: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# script 取值：latin / cjk / japanese / korean / cyrillic / arabic / hebrew / greek /
#              devanagari / thai / hangul(并入 korean) / other
LANGUAGES: list[Language] = [
    # ---- 中文与东亚 ----
    Language("zh", "Chinese", "中文", "中文", "cjk", asr=True, translate=True, tts=True),
    Language("zh-TW", "Chinese (Traditional)", "繁体中文", "繁體中文", "cjk", asr=True, translate=True, tts=True),
    Language("ja", "Japanese", "日语", "日本語", "japanese", asr=True, translate=True, tts=True),
    Language("ko", "Korean", "韩语", "한국어", "korean", asr=True, translate=True, tts=True),
    Language("yue", "Cantonese", "粤语", "粵語", "cjk", asr=True, translate=True, tts=True),
    # ---- 西欧 ----
    Language("en", "English", "英语", "English", "latin", asr=True, translate=True, tts=True),
    Language("fr", "French", "法语", "Français", "latin", asr=True, translate=True, tts=True),
    Language("de", "German", "德语", "Deutsch", "latin", asr=True, translate=True, tts=True),
    Language("es", "Spanish", "西班牙语", "Español", "latin", asr=True, translate=True, tts=True),
    Language("pt", "Portuguese", "葡萄牙语", "Português", "latin", asr=True, translate=True, tts=True),
    Language("it", "Italian", "意大利语", "Italiano", "latin", asr=True, translate=True, tts=True),
    Language("nl", "Dutch", "荷兰语", "Nederlands", "latin", asr=True, translate=True, tts=True),
    Language("ca", "Catalan", "加泰罗尼亚语", "Català", "latin", translate=True),
    Language("gl", "Galician", "加利西亚语", "Galego", "latin", translate=True),
    # ---- 北欧 ----
    Language("sv", "Swedish", "瑞典语", "Svenska", "latin", asr=True, translate=True, tts=True),
    Language("da", "Danish", "丹麦语", "Dansk", "latin", asr=True, translate=True, tts=True),
    Language("no", "Norwegian", "挪威语", "Norsk", "latin", asr=True, translate=True, tts=True),
    Language("fi", "Finnish", "芬兰语", "Suomi", "latin", asr=True, translate=True, tts=True),
    Language("is", "Icelandic", "冰岛语", "Íslenska", "latin", translate=True),
    # ---- 中欧 / 东欧 ----
    Language("pl", "Polish", "波兰语", "Polski", "latin", asr=True, translate=True, tts=True),
    Language("cs", "Czech", "捷克语", "Čeština", "latin", asr=True, translate=True, tts=True),
    Language("sk", "Slovak", "斯洛伐克语", "Slovenčina", "latin", translate=True, tts=True),
    Language("hu", "Hungarian", "匈牙利语", "Magyar", "latin", asr=True, translate=True, tts=True),
    Language("ro", "Romanian", "罗马尼亚语", "Română", "latin", asr=True, translate=True, tts=True),
    Language("sl", "Slovenian", "斯洛文尼亚语", "Slovenščina", "latin", translate=True),
    Language("hr", "Croatian", "克罗地亚语", "Hrvatski", "latin", translate=True),
    Language("sr", "Serbian", "塞尔维亚语", "Српски", "cyrillic", translate=True),
    Language("bg", "Bulgarian", "保加利亚语", "Български", "cyrillic", asr=True, translate=True, tts=True),
    Language("ru", "Russian", "俄语", "Русский", "cyrillic", asr=True, translate=True, tts=True),
    Language("uk", "Ukrainian", "乌克兰语", "Українська", "cyrillic", asr=True, translate=True, tts=True),
    Language("lt", "Lithuanian", "立陶宛语", "Lietuvių", "latin", translate=True),
    Language("lv", "Latvian", "拉脱维亚语", "Latviešu", "latin", translate=True),
    Language("et", "Estonian", "爱沙尼亚语", "Eesti", "latin", translate=True),
    Language("sq", "Albanian", "阿尔巴尼亚语", "Shqip", "latin", translate=True),
    Language("mk", "Macedonian", "马其顿语", "Македонски", "cyrillic", translate=True),
    # ---- 南欧 / 其他欧洲 ----
    Language("el", "Greek", "希腊语", "Ελληνικά", "greek", asr=True, translate=True, tts=True),
    Language("tr", "Turkish", "土耳其语", "Türkçe", "latin", asr=True, translate=True, tts=True),
    Language("az", "Azerbaijani", "阿塞拜疆语", "Azərbaycan", "latin", translate=True),
    Language("hy", "Armenian", "亚美尼亚语", "Հայերեն", "other", translate=True),
    Language("ka", "Georgian", "格鲁吉亚语", "ქართული", "other", translate=True),
    Language("he", "Hebrew", "希伯来语", "עברית", "hebrew", asr=True, translate=True, tts=True),
    Language("ar", "Arabic", "阿拉伯语", "العربية", "arabic", asr=True, translate=True, tts=True),
    Language("fa", "Persian", "波斯语", "فارسی", "arabic", asr=True, translate=True, tts=True),
    Language("ur", "Urdu", "乌尔都语", "اردو", "arabic", asr=True, translate=True),
    # ---- 南亚 / 东南亚 ----
    Language("hi", "Hindi", "印地语", "हिन्दी", "devanagari", asr=True, translate=True, tts=True),
    Language("bn", "Bengali", "孟加拉语", "বাংলা", "other", asr=True, translate=True, tts=True),
    Language("ta", "Tamil", "泰米尔语", "தமிழ்", "other", asr=True, translate=True),
    Language("te", "Telugu", "泰卢固语", "తెలుగు", "other", asr=True, translate=True),
    Language("mr", "Marathi", "马拉地语", "मराठी", "devanagari", asr=True, translate=True),
    Language("gu", "Gujarati", "古吉拉特语", "ગુજરાતી", "other", asr=True, translate=True),
    Language("kn", "Kannada", "卡纳达语", "ಕನ್ನಡ", "other", asr=True, translate=True),
    Language("ml", "Malayalam", "马拉雅拉姆语", "മലയാളം", "other", asr=True, translate=True),
    Language("pa", "Punjabi", "旁遮普语", "ਪੰਜਾਬੀ", "other", asr=True, translate=True),
    Language("si", "Sinhala", "僧伽罗语", "සිංහල", "other", translate=True),
    Language("ne", "Nepali", "尼泊尔语", "नेपाली", "devanagari", translate=True),
    Language("th", "Thai", "泰语", "ไทย", "thai", asr=True, translate=True, tts=True),
    Language("vi", "Vietnamese", "越南语", "Tiếng Việt", "latin", asr=True, translate=True, tts=True),
    Language("id", "Indonesian", "印尼语", "Bahasa Indonesia", "latin", asr=True, translate=True, tts=True),
    Language("ms", "Malay", "马来语", "Bahasa Melayu", "latin", asr=True, translate=True, tts=True),
    Language("tl", "Filipino", "菲律宾语", "Filipino", "latin", asr=True, translate=True),
    Language("km", "Khmer", "高棉语", "ខ្មែរ", "other", translate=True),
    Language("lo", "Lao", "老挝语", "ລາວ", "other", translate=True),
    Language("my", "Burmese", "缅甸语", "မြန်မာ", "other", translate=True),
    # ---- 非洲 / 其他 ----
    Language("sw", "Swahili", "斯瓦希里语", "Kiswahili", "latin", asr=True, translate=True),
    Language("am", "Amharic", "阿姆哈拉语", "አማርኛ", "other", translate=True),
    Language("af", "Afrikaans", "南非荷兰语", "Afrikaans", "latin", translate=True),
    Language("ha", "Hausa", "豪萨语", "Hausa", "latin", translate=True),
    Language("yo", "Yoruba", "约鲁巴语", "Yorùbá", "latin", translate=True),
    Language("zu", "Zulu", "祖鲁语", "isiZulu", "latin", translate=True),
    Language("kk", "Kazakh", "哈萨克语", "Қазақша", "cyrillic", translate=True),
    Language("uz", "Uzbek", "乌兹别克语", "Oʻzbek", "latin", translate=True),
    Language("mn", "Mongolian", "蒙古语", "Монгол", "cyrillic", translate=True),
]

_BY_CODE = {lang.code: lang for lang in LANGUAGES}

#: 常见别名 -> 标准码（用户输入 "cn"/"zh-CN"/"english" 都能识别）
ALIASES = {
    "cn": "zh", "zh-cn": "zh", "zh-hans": "zh", "chs": "zh", "chinese": "zh",
    "zh-tw": "zh-TW", "zh-hant": "zh-TW", "cht": "zh-TW",
    "jp": "ja", "jpn": "ja", "japanese": "ja",
    "kr": "ko", "kor": "ko", "korean": "ko",
    "en-us": "en", "en-gb": "en", "eng": "en", "english": "en",
    "fr-fr": "fr", "fre": "fr", "french": "fr",
    "de-de": "de", "ger": "de", "german": "de",
    "es-es": "es", "spa": "es", "spanish": "es",
    "pt-br": "pt", "pt-pt": "pt", "por": "pt", "portuguese": "pt",
    "it-it": "it", "ita": "it", "italian": "it",
    "ru-ru": "ru", "rus": "ru", "russian": "ru",
    "arabic": "ar", "hebrew": "he", "hindi": "hi", "thai": "th",
    "vietnamese": "vi", "indonesian": "id", "malay": "ms", "turkish": "tr",
    "yue": "yue", "cantonese": "yue",
}


def normalize(code: Optional[str]) -> str:
    """把各种写法归一成清单里的标准码（未知输入原样返回，便于上层报错）。"""
    if not code:
        return ""
    raw = str(code).strip()
    if not raw:
        return ""
    if raw in _BY_CODE:
        return raw
    low = raw.lower()
    if low in ALIASES:
        return ALIASES[low]
    for known in _BY_CODE:
        if known.lower() == low:
            return known
    base = low.split("-")[0].split("_")[0]
    if base in _BY_CODE:
        return base
    if base in ALIASES:
        return ALIASES[base]
    # 支持用语言名书写（"English" / "中文" / "日本語"）
    for lang in LANGUAGES:
        if low in (lang.name_en.lower(), lang.name_zh.lower(), lang.native.lower()):
            return lang.code
    return raw


def get(code: Optional[str]) -> Optional[Language]:
    return _BY_CODE.get(normalize(code))


def is_supported(code: Optional[str], capability: str = "translate") -> bool:
    lang = get(code)
    return bool(lang is not None and getattr(lang, capability, False))


def asr_languages() -> list:
    return [lang for lang in LANGUAGES if lang.asr]


def translate_languages() -> list:
    return [lang for lang in LANGUAGES if lang.translate]


def tts_languages() -> list:
    return [lang for lang in LANGUAGES if lang.tts]


def stats() -> dict:
    return {
        "total": len(LANGUAGES),
        "asr": len(asr_languages()),
        "translate": len(translate_languages()),
        "tts": len(tts_languages()),
        "scripts": sorted({lang.script for lang in LANGUAGES}),
    }


# --------------------------------------------------------------------------- #
# 语言检测
# --------------------------------------------------------------------------- #

#: Unicode 区段 -> 语言（脚本层判定，优先于拉丁词频）
_SCRIPT_RANGES = [
    ("cjk", 0x4E00, 0x9FFF), ("cjk", 0x3400, 0x4DBF),
    ("hiragana", 0x3040, 0x309F), ("katakana", 0x30A0, 0x30FF),
    ("hangul", 0xAC00, 0xD7AF), ("hangul", 0x1100, 0x11FF),
    ("cyrillic", 0x0400, 0x04FF),
    ("arabic", 0x0600, 0x06FF), ("arabic", 0x0750, 0x077F),
    ("hebrew", 0x0590, 0x05FF),
    ("greek", 0x0370, 0x03FF),
    ("devanagari", 0x0900, 0x097F),
    ("thai", 0x0E00, 0x0E7F),
    ("other", 0x0980, 0x09FF),   # 孟加拉
    ("other", 0x0B80, 0x0BFF),   # 泰米尔
    ("other", 0x0C00, 0x0C7F),   # 泰卢固
    ("other", 0x0C80, 0x0CFF),   # 卡纳达
    ("other", 0x0D00, 0x0D7F),   # 马拉雅拉姆
    ("other", 0x0A80, 0x0AFF),   # 古吉拉特
    ("other", 0x0A00, 0x0A7F),   # 旁遮普
    ("other", 0x1780, 0x17FF),   # 高棉
    ("other", 0x0E80, 0x0EFF),   # 老挝
    ("other", 0x1000, 0x109F),   # 缅甸
    ("other", 0x0530, 0x058F),   # 亚美尼亚
    ("other", 0x10A0, 0x10FF),   # 格鲁吉亚
    ("other", 0x1200, 0x137F),   # 阿姆哈拉
    ("other", 0x0D80, 0x0DFF),   # 僧伽罗
]

#: 拉丁字母语言的功能词（命中即加分；词短、区分度高）
_LATIN_STOPWORDS = {
    "en": ["the", "and", "of", "to", "is", "you", "that", "it", "for", "with", "this", "are", "be", "on"],
    "es": ["el", "la", "los", "las", "de", "que", "y", "en", "un", "una", "por", "con", "para", "es", "no"],
    "pt": ["o", "a", "os", "as", "de", "que", "e", "em", "um", "uma", "por", "com", "para", "não", "é"],
    "fr": ["le", "la", "les", "des", "de", "et", "un", "une", "est", "que", "pour", "dans", "avec", "pas", "vous"],
    "it": ["il", "la", "di", "che", "e", "un", "una", "per", "con", "non", "sono", "questo", "gli"],
    "de": ["der", "die", "das", "und", "ist", "nicht", "ein", "eine", "mit", "für", "auf", "sich", "wir", "auch"],
    "nl": ["de", "het", "een", "en", "van", "dat", "is", "niet", "met", "voor", "op", "zijn", "je"],
    "sv": ["och", "att", "det", "som", "på", "är", "för", "med", "inte", "jag", "den", "har"],
    "da": ["og", "at", "det", "er", "en", "et", "for", "med", "ikke", "jeg", "den", "på"],
    "no": ["og", "å", "det", "er", "en", "et", "for", "med", "ikke", "jeg", "den", "på", "som"],
    "fi": ["ja", "on", "ei", "se", "että", "kun", "niin", "mutta", "myös", "hän", "tämä"],
    "pl": ["nie", "się", "jest", "że", "na", "do", "to", "ale", "jak", "po", "tak", "oraz"],
    "cs": ["že", "se", "je", "na", "to", "ale", "jako", "pro", "tak", "není", "která"],
    "sk": ["že", "sa", "je", "na", "to", "ale", "ako", "pre", "tak", "nie", "ktorá"],
    "hu": ["és", "hogy", "nem", "az", "egy", "van", "meg", "csak", "mint", "vagy"],
    "ro": ["și", "de", "la", "în", "este", "nu", "cu", "care", "pentru", "un", "o"],
    "tr": ["ve", "bir", "bu", "için", "ile", "de", "da", "çok", "ama", "gibi", "olarak"],
    "id": ["dan", "yang", "di", "ke", "dari", "untuk", "dengan", "ini", "itu", "tidak", "adalah"],
    "ms": ["dan", "yang", "di", "ke", "dari", "untuk", "dengan", "ini", "itu", "tidak", "adalah"],
    "vi": ["và", "của", "là", "có", "không", "được", "trong", "cho", "với", "này", "một"],
    "tl": ["ang", "ng", "sa", "na", "at", "ay", "mga", "hindi", "ito", "para"],
    "sw": ["na", "ya", "kwa", "ni", "wa", "hii", "sana", "lakini", "kama"],
    "af": ["die", "en", "van", "is", "nie", "het", "met", "vir", "op"],
    "ha": ["da", "na", "ba", "ne", "ce", "wannan", "sun", "yana"],
    "yo": ["ati", "ti", "ni", "pe", "fun", "awọn", "kii"],
    "zu": ["futhi", "kanye", "ukuthi", "ngoba", "kubantu", "lesi"],
    "ca": ["que", "els", "les", "una", "amb", "per", "aquest", "són", "no"],
    "gl": ["que", "os", "as", "unha", "con", "para", "este", "non", "é"],
    "lt": ["ir", "yra", "kad", "su", "bet", "tai", "kaip", "ne"],
    "lv": ["un", "ir", "ka", "ar", "bet", "tas", "viņš", "nav"],
    "et": ["ja", "on", "ei", "see", "kui", "aga", "et", "ta"],
    "sq": ["dhe", "është", "një", "për", "me", "nuk", "kjo", "si"],
    "is": ["og", "er", "að", "það", "ekki", "sem", "með", "hann"],
    "hr": ["je", "na", "da", "se", "za", "nije", "koji", "ali"],
    "sl": ["je", "in", "da", "se", "za", "ni", "ki", "ali"],
    "uz": ["va", "bu", "bir", "uchun", "bilan", "ham", "emas"],
}

#: 变音/特殊字符 -> 语言（强特征，命中即加权）
_CHAR_HINTS = {
    "es": "¿¡ñ", "pt": "ãõç", "de": "ßäöü", "fr": "çèêëàâîïôùûœ", "it": "ìòù",
    "sv": "åäö", "da": "æøå", "no": "æøå", "fi": "äö", "is": "þðæ",
    "pl": "ąćęłńśźż", "cs": "ěščřžýáíéůú", "sk": "ľščťžýáíéô", "hu": "őűáéíóöü",
    "ro": "ăâîșț", "tr": "ğışçöü", "vi": "ăâđêôơư", "lv": "āēīūģķļņ", "lt": "ąčęėįšųūž",
    "et": "õäöü", "hr": "čćđšž", "sl": "čšž", "sq": "ëç", "az": "əğış",
    "tl": "ñ", "sw": "", "yo": "ẹọṣ", "ha": "ɓɗƙ",
}

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _script_of(ch: str) -> str:
    cp = ord(ch)
    for name, lo, hi in _SCRIPT_RANGES:
        if lo <= cp <= hi:
            return name
    return "latin" if ch.isascii() and ch.isalpha() else ("other" if ch.isalpha() else "")


def _script_scores(text: str) -> dict:
    scores: dict = {}
    letters = 0
    for ch in text:
        if not ch.isalpha():
            continue
        letters += 1
        name = _script_of(ch)
        if name:
            scores[name] = scores.get(name, 0) + 1
    if letters:
        scores = {k: v / letters for k, v in scores.items()}
    return scores


def detect(text: str) -> dict:
    """检测文本语言。

    返回 {"code", "confidence", "method", "candidates":[{code, score}...]}。
    无法判定时 code 为 ""、confidence 为 0。
    """
    raw = (text or "").strip()
    if not raw:
        return {"code": "", "confidence": 0.0, "method": "empty", "candidates": []}

    scripts = _script_scores(raw)
    if scripts:
        top_script, ratio = max(scripts.items(), key=lambda kv: kv[1])
    else:
        top_script, ratio = "", 0.0

    # 1) 假名出现即日语（中文文本里不会有假名）
    if scripts.get("hiragana", 0) + scripts.get("katakana", 0) > 0.05:
        return _result("ja", min(0.99, 0.85 + ratio), "script", [("ja", ratio)])
    if scripts.get("hangul", 0) > 0.3:
        return _result("ko", min(0.99, 0.85 + scripts["hangul"]), "script", [("ko", scripts["hangul"])])
    if scripts.get("cyrillic", 0) > 0.5:
        code = _cyrillic_variant(raw)
        return _result(code, 0.9, "script", [(code, scripts["cyrillic"])])
    for script, code, conf in (("arabic", "ar", 0.85), ("hebrew", "he", 0.9),
                               ("greek", "el", 0.9), ("devanagari", "hi", 0.85),
                               ("thai", "th", 0.95)):
        if scripts.get(script, 0) > 0.5:
            return _result(code, conf, "script", [(code, scripts[script])])
    if scripts.get("cjk", 0) > 0.3:
        return _result("zh", 0.9, "script", [("zh", scripts["cjk"])])

    # 2) 拉丁/其他：优先用统计检测器（比停用词表稳得多）
    if _HAS_LANGDETECT:
        guess = _detect_with_langdetect(raw)
        if guess is not None:
            return guess

    # 3) 兜底：功能词评分 + 变音字符加分（无 langdetect 时也能用）
    words = [w.lower() for w in _WORD_RE.findall(raw)]
    if not words:
        return {"code": "", "confidence": 0.0, "method": "none", "candidates": []}
    word_set = set(words)
    scores: dict = {}
    for code, stops in _LATIN_STOPWORDS.items():
        hits = sum(1 for w in words if w in stops)
        if hits:
            scores[code] = scores.get(code, 0) + hits
    lower = raw.lower()
    for code, chars in _CHAR_HINTS.items():
        if not chars:
            continue
        hits = sum(1 for ch in lower if ch in chars)
        if hits:
            scores[code] = scores.get(code, 0) + hits * 1.5
    if not scores:
        return {"code": "", "confidence": 0.0, "method": "no-signal", "candidates": []}

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_code, best_score = ranked[0]
    total = sum(v for _, v in ranked)
    # 区分度：领先第二名的比例；样本越长越可信
    second = ranked[1][1] if len(ranked) > 1 else 0
    coverage = min(1.0, len(word_set) / 8.0)
    margin = (best_score - second) / max(best_score, 1e-9)
    confidence = round(min(0.98, 0.35 + 0.4 * margin + 0.25 * coverage), 4)
    return _result(best_code, confidence, "stopwords", ranked[:5])


def _detect_with_langdetect(text: str):
    """用 langdetect 判定；结果不可映射到本清单时返回 None（交给兜底逻辑）。"""
    try:
        results = _ld_detect_langs(text)
    except Exception:  # noqa: BLE001 - 空串/纯符号会抛
        return None
    if not results:
        return None
    mapped = []
    for item in results[:5]:
        code = _LD_ALIASES.get(item.lang.lower(), item.lang)
        code = normalize(code)
        if code in _BY_CODE:
            mapped.append((code, float(item.prob)))
    if not mapped:
        return None
    best_code, best_prob = mapped[0]
    # langdetect 的 prob 在短文本上偏乐观，做一次温和收缩，避免给出虚高置信度
    confidence = round(min(0.98, 0.5 + 0.5 * best_prob), 4)
    return _result(best_code, confidence, "langdetect", mapped)


def _cyrillic_variant(text: str) -> str:
    """西里尔字母细分：靠几个独有字符区分俄/乌/保/塞/马其顿/哈萨克/蒙古。"""
    low = text.lower()
    if "ї" in low or "є" in low or "і" in low:
        return "uk"
    if "ў" in low:
        return "bg"
    if "ђ" in low or "ћ" in low or "џ" in low:
        return "sr"
    if "ѓ" in low or "ќ" in low or "ѕ" in low:
        return "mk"
    if "қ" in low or "ғ" in low or "ң" in low:
        return "kk"
    if "ө" in low or "ү" in low:
        return "mn"
    return "ru"


def _result(code: str, confidence: float, method: str, candidates) -> dict:
    return {
        "code": code,
        "confidence": round(float(confidence), 4),
        "method": method,
        "candidates": [{"code": c, "score": round(float(s), 4)} for c, s in candidates],
    }


def detect_batch(texts: list) -> list:
    """批量检测（取多数票，供"整段字幕属于哪种语言"这类场景）。"""
    votes: dict = {}
    details = [detect(t) for t in texts]
    for d in details:
        if d["code"]:
            votes[d["code"]] = votes.get(d["code"], 0) + 1
    if not votes:
        return {"code": "", "confidence": 0.0, "votes": {}, "details": details}
    code = max(votes.items(), key=lambda kv: kv[1])[0]
    return {
        "code": code,
        "confidence": round(votes[code] / max(len(details), 1), 4),
        "votes": votes,
        "details": details,
    }
