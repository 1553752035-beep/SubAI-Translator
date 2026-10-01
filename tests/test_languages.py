# -*- coding: utf-8 -*-
"""四期 4.4 多语言支持 —— 单元测试。

含**语言检测准确率**实测（验收要求 ≥95%）：语料为 27 种语言 × 3 句真实句子，
逐句检测统计准确率。语料写死在测试里，避免"改语料刷指标"。

注：打印一律用 ASCII（测试可能跑在 GBK 控制台，直接打印 CJK 会 UnicodeEncodeError）。
"""
from __future__ import annotations

from src import languages as L

#: (期望语言, [句子...])
DETECT_CORPUS = [
    ("zh", [
        "今天天气不错，我们出去走走吧。",
        "人工智能正在改变世界。",
        "请稍等，我马上回来。",
    ]),
    ("en", [
        "The weather is nice today, let us go for a walk.",
        "Artificial intelligence is changing the world.",
        "Please keep your seatbelt fastened during takeoff.",
    ]),
    ("ja", [
        "今日はいい天気ですね、散歩に行きましょう。",
        "人工知能は世界を変えつつあります。",
        "少々お待ちください、すぐ戻ります。",
    ]),
    ("ko", [
        "오늘 날씨가 좋네요, 산책하러 갑시다.",
        "인공지능이 세상을 바꾸고 있습니다.",
        "잠시만 기다려 주세요, 곧 돌아옵니다.",
    ]),
    ("fr", [
        "Il fait beau aujourd'hui, allons faire un tour.",
        "L'intelligence artificielle change le monde.",
        "Veuillez attacher votre ceinture pendant le décollage de cet avion.",
    ]),
    ("de", [
        "Das Wetter ist heute schön, gehen wir spazieren und trinken Kaffee.",
        "Künstliche Intelligenz verändert die Welt und unser Leben.",
        "Bitte legen Sie während des Starts den Sicherheitsgurt an.",
    ]),
    ("es", [
        "Hace buen tiempo hoy, vamos a dar un paseo por el parque.",
        "La inteligencia artificial está cambiando el mundo entero.",
        "Por favor, abróchese el cinturón durante el despegue del avión.",
    ]),
    ("pt", [
        "O tempo está bom hoje, vamos dar um passeio pela cidade.",
        "A inteligência artificial está mudando o mundo inteiro.",
        "Por favor, aperte o cinto durante a decolagem do avião.",
    ]),
    ("it", [
        "Oggi il tempo è bello, andiamo a fare una passeggiata insieme.",
        "L'intelligenza artificiale sta cambiando il mondo intero.",
        "Per favore, allacciate le cinture durante il decollo.",
    ]),
    ("ru", [
        "Сегодня хорошая погода, пойдём гулять в парк.",
        "Искусственный интеллект меняет мир вокруг нас.",
        "Пожалуйста, пристегните ремень во время взлёта.",
    ]),
    ("uk", [
        "Сьогодні гарна погода, ходімо гуляти в парк.",
        "Штучний інтелект змінює світ навколо нас.",
        "Будь ласка, пристебніть ремінь під час зльоту.",
    ]),
    ("ar", [
        "الطقس جميل اليوم، لنذهب في نزهة إلى الحديقة.",
        "الذكاء الاصطناعي يغير العالم من حولنا.",
        "يرجى ربط حزام الأمان أثناء الإقلاع.",
    ]),
    ("he", [
        "מזג האוויר יפה היום, בוא נצא לטיול בפארק.",
        "הבינה המלאכותית משנה את העולם סביבנו.",
        "אנא הדק את החגורה בזמן ההמראה.",
    ]),
    ("el", [
        "Ο καιρός είναι ωραίος σήμερα, ας πάμε μια βόλτα.",
        "Η τεχνητή νοημοσύνη αλλάζει τον κόσμο γύρω μας.",
        "Παρακαλώ δέστε τη ζώνη κατά την απογείωση.",
    ]),
    ("hi", [
        "आज मौसम अच्छा है, चलो पार्क में टहलने चलें।",
        "कृत्रिम बुद्धिमत्ता दुनिया को बदल रही है।",
        "कृपया उड़ान के दौरान सीट बेल्ट बांधें।",
    ]),
    ("th", [
        "วันนี้อากาศดี เราไปเดินเล่นที่สวนกันเถอะ",
        "ปัญญาประดิษฐ์กำลังเปลี่ยนโลกของเรา",
        "กรุณารัดเข็มขัดนิรภัยระหว่างการขึ้นบิน",
    ]),
    ("vi", [
        "Hôm nay thời tiết đẹp, chúng ta đi dạo trong công viên nhé.",
        "Trí tuệ nhân tạo đang thay đổi thế giới của chúng ta.",
        "Vui lòng thắt dây an toàn trong khi cất cánh.",
    ]),
    ("tr", [
        "Bugün hava güzel, hadi parkta yürüyüşe çıkalım.",
        "Yapay zeka dünyamızı değiştiriyor ve geliştiriyor.",
        "Lütfen kalkış sırasında emniyet kemerini bağlayın.",
    ]),
    ("id", [
        "Hari ini cuacanya bagus, ayo kita jalan-jalan di taman.",
        "Kecerdasan buatan sedang mengubah dunia kita.",
        "Mohon kenakan sabuk pengaman saat lepas landas.",
    ]),
    ("nl", [
        "Het weer is vandaag mooi, laten we een wandeling maken.",
        "Kunstmatige intelligentie verandert onze wereld.",
        "Gelieve de veiligheidsgordel vast te maken tijdens het opstijgen.",
    ]),
    ("pl", [
        "Dziś jest ładna pogoda, chodźmy na spacer do parku.",
        "Sztuczna inteligencja zmienia nasz świat.",
        "Proszę zapiąć pasy podczas startu samolotu.",
    ]),
    ("sv", [
        "Vädret är fint idag, låt oss ta en promenad i parken.",
        "Artificiell intelligens förändrar vår värld.",
        "Vänligen fäst säkerhetsbältet under starten.",
    ]),
    ("da", [
        "Vejret er godt i dag, lad os gå en tur i parken.",
        "Kunstig intelligens forandrer vores verden.",
        "Fastgør venligst sikkerhedsbæltet under starten.",
    ]),
    ("fi", [
        "Sää on tänään kaunis, mennään kävelylle puistoon.",
        "Tekoäly muuttaa maailmaamme.",
        "Kiinnitä turvavyö nousun aikana.",
    ]),
    ("cs", [
        "Dnes je hezké počasí, pojďme se projít do parku.",
        "Umělá inteligence mění náš svět.",
        "Prosím připoutejte se během vzletu.",
    ]),
    ("hu", [
        "Ma szép az idő, menjünk sétálni a parkba.",
        "A mesterséges intelligencia megváltoztatja a világot.",
        "Kérjük, kapcsolja be a biztonsági övet felszálláskor.",
    ]),
    ("ro", [
        "Vremea este frumoasă astăzi, hai să ne plimbăm în parc.",
        "Inteligența artificială schimbă lumea noastră.",
        "Vă rugăm să vă prindeți centura în timpul decolării.",
    ]),
]


class TestRegistry:
    def test_capability_counts(self):
        """验收：识别 >=20 种、翻译 >=30 种。"""
        s = L.stats()
        assert s["asr"] >= 20, s
        assert s["translate"] >= 30, s
        assert s["tts"] >= 5, s
        assert s["total"] == len(L.LANGUAGES)

    def test_codes_unique_and_shaped(self):
        codes = [lang.code for lang in L.LANGUAGES]
        assert len(codes) == len(set(codes)), "语言码不允许重复"
        for lang in L.LANGUAGES:
            assert lang.name_zh and lang.name_en and lang.native and lang.script

    def test_normalize_aliases(self):
        assert L.normalize("cn") == "zh"
        assert L.normalize("zh-CN") == "zh"
        assert L.normalize("EN-US") == "en"
        assert L.normalize("english") == "en"
        assert L.normalize("jp") == "ja"
        assert L.normalize("") == ""
        assert L.normalize(None) == ""
        assert L.normalize("qqq") == "qqq"   # 未知语言原样返回，交上层报错

    def test_get_and_is_supported(self):
        assert L.get("zh").name_zh == "中文"
        assert L.get("cn").code == "zh"
        assert L.get("nope") is None
        assert L.is_supported("en", "asr") is True
        assert L.is_supported("yue", "tts") is True
        assert L.is_supported("gl", "asr") is False


class TestDetect:
    def test_empty_and_noise(self):
        assert L.detect("")["code"] == ""
        assert L.detect("   ")["code"] == ""
        assert L.detect("12345 !!! ...")["code"] == ""

    def test_script_shortcuts(self):
        assert L.detect("你好世界")["code"] == "zh"
        assert L.detect("こんにちは")["code"] == "ja"
        assert L.detect("안녕하세요")["code"] == "ko"
        assert L.detect("Привет, как дела?")["code"] == "ru"
        assert L.detect("مرحبا بالعالم")["code"] == "ar"
        assert L.detect("Γειά σου κόσμε")["code"] == "el"
        assert L.detect("नमस्ते दुनिया")["code"] == "hi"
        assert L.detect("สวัสดีชาวโลก")["code"] == "th"

    def test_cyrillic_variants(self):
        assert L.detect("Сьогодні гарна погода, ходімо гуляти.")["code"] == "uk"
        assert L.detect("Пожалуйста, пристегните ремень.")["code"] == "ru"

    def test_stopword_detection_returns_candidates(self):
        r = L.detect("The weather is nice today and we can go for a walk.")
        assert r["code"] == "en"
        assert r["candidates"] and r["candidates"][0]["code"] == "en"
        assert 0 < r["confidence"] <= 1

    def test_batch_vote(self):
        r = L.detect_batch(["Hello there, how are you?", "This is a test of the system.", "你好"])
        assert r["code"] == "en"
        assert r["votes"]["en"] >= 2

    def test_accuracy_on_corpus(self):
        """语言检测准确率（验收 >=95%）。"""
        total = 0
        correct = 0
        misses = []
        for expected, sentences in DETECT_CORPUS:
            for idx, s in enumerate(sentences):
                total += 1
                got = L.detect(s)["code"]
                if got == expected:
                    correct += 1
                else:
                    misses.append("%s->%s(#%d)" % (expected, got, idx))
        accuracy = correct / total
        print("[lang-detect] %d/%d = %.2f%%" % (correct, total, accuracy * 100))
        if misses:
            print("[lang-detect] misses: " + ", ".join(misses))
        assert accuracy >= 0.95, "accuracy %.2f%% < 95%%, misses=%s" % (accuracy * 100, misses)
