# -*- coding: utf-8 -*-
"""五期：「我有文字稿」端点测试（只验参数校验与建任务，不跑真实识别）。"""
from __future__ import annotations


def post_align(client, headers, script="第一句\n第二句", filename="demo.mp4"):
    return client.post(
        "/api/align",
        headers=headers,
        files={"file": (filename, b"fake-video", "video/mp4")},
        data={"script": script, "output_format": "srt", "output_video": "none"},
    )


class TestAlignApi:
    def test_requires_auth(self, client):
        r = post_align(client, {})
        assert r.status_code == 401

    def test_empty_script_rejected(self, client, auth_headers):
        r = post_align(client, auth_headers, script="   \n  \n")
        assert r.status_code == 400
        assert "文字稿" in r.json()["detail"]

    def test_bad_extension_rejected(self, client, auth_headers):
        r = post_align(client, auth_headers, filename="notes.txt")
        assert r.status_code == 400
        assert "不支持的文件类型" in r.json()["detail"]

    def test_creates_task(self, client, auth_headers):
        r = post_align(client, auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["task_id"] and body["lines"] == 2
        assert body["size_bytes"] == len(b"fake-video")
