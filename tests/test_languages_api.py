# -*- coding: utf-8 -*-
"""四期 4.4 语言支持 —— API 测试。"""
from __future__ import annotations


class TestLanguagesApi:
    def test_list_requires_auth(self, client):
        assert client.get("/api/languages").status_code in (401, 403)

    def test_list_all(self, client, auth_headers):
        r = client.get("/api/languages", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        codes = {item["code"] for item in body["languages"]}
        assert {"zh", "en", "ja", "ru", "ar"} <= codes
        assert body["stats"]["asr"] >= 20
        assert body["stats"]["translate"] >= 30
        assert body["stats"]["total"] == len(body["languages"])

    def test_list_filter_by_capability(self, client, auth_headers):
        r = client.get("/api/languages?capability=tts", headers=auth_headers)
        assert r.status_code == 200, r.text
        items = r.json()["languages"]
        assert items and all(i["tts"] for i in items)
        assert len(items) < len(client.get("/api/languages", headers=auth_headers).json()["languages"])

    def test_detect_single(self, client, auth_headers):
        r = client.post("/api/languages/detect", headers=auth_headers,
                        json={"text": "The weather is nice today, let us go for a walk."})
        assert r.status_code == 200, r.text
        assert r.json()["code"] == "en"
        r2 = client.post("/api/languages/detect", headers=auth_headers, json={"text": "你好世界"})
        assert r2.json()["code"] == "zh"

    def test_detect_batch(self, client, auth_headers):
        r = client.post("/api/languages/detect", headers=auth_headers,
                        json={"texts": ["Hello there, how are you?", "This is a system test.", "你好"]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["code"] == "en" and body["votes"]["en"] >= 2

    def test_detect_empty(self, client, auth_headers):
        r = client.post("/api/languages/detect", headers=auth_headers, json={})
        assert r.status_code == 200 and r.json()["code"] == ""

