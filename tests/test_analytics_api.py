# -*- coding: utf-8 -*-
"""四期 4.6 数据分析 —— API 测试。"""
from __future__ import annotations


class TestAnalyticsApi:
    def test_summary_requires_auth(self, client):
        assert client.get("/api/analytics/summary").status_code in (401, 403)

    def test_summary_empty_db(self, client, auth_headers):
        r = client.get("/api/analytics/summary?days=7", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tasks"]["total"] == 0
        assert body["volume"]["lines_total"] == 0
        assert body["range_days"] == 7

    def test_quality_empty_db(self, client, auth_headers):
        r = client.get("/api/analytics/quality", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tasks"]["total"] == 0
        assert body["unavailable_metrics"]["asr_confidence_avg"] is None

    def test_export_xlsx(self, client, auth_headers):
        r = client.get("/api/analytics/export?format=xlsx", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.content[:2] == b"PK"
        assert "spreadsheetml" in r.headers["content-type"]
        assert "attachment" in r.headers.get("content-disposition", "")

    def test_export_pdf(self, client, auth_headers):
        r = client.get("/api/analytics/export?format=pdf&kind=quality", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.content[:5] == b"%PDF-"
        assert r.headers["content-type"] == "application/pdf"

    def test_export_html(self, client, auth_headers):
        r = client.get("/api/analytics/export?format=html", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert "text/html" in r.headers["content-type"]
        assert "使用统计报表" in r.text

    def test_export_rejects_bad_params(self, client, auth_headers):
        assert client.get("/api/analytics/export?format=docx", headers=auth_headers).status_code == 400
        assert client.get("/api/analytics/export?kind=nope", headers=auth_headers).status_code == 400

