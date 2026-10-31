# -*- coding: utf-8 -*-
"""`/api/compose` 路由：target_lang 表单参数必须落到 TaskItem 上。

[P1 2026-10-24] `_run_compose_task` 早就支持翻译已有字幕，但这条路由一直硬编码
`target_lang="none"`，于是界面只能「直接套用」。这里钉住：表单传什么，item 就带什么。
否则很容易退化成「前端加了选项、后端还是写死 none」，而用户只会看到『怎么没翻译』。
"""
from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from fastapi import UploadFile

from src.api import server


def _upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(data))


@pytest.fixture
def captured(monkeypatch, tmp_path):
    """拦下 _submit_one_transcode，只看它收到的 item。"""
    seen: dict = {}

    async def fake_submit(item, user):
        seen["item"] = item
        return {"task_id": "t1", "status": "pending"}

    monkeypatch.setattr(server, "_submit_one_transcode", fake_submit)
    # uploads_dir 由 conftest 的 autouse fixture 统一指到 tmp_path，这里不用再动
    # （它是 SubAIConfig 的只读 property，直接 setattr 会报 no setter）
    return seen


def _run(coro):
    import asyncio
    return asyncio.run(coro)


def test_target_lang_passed_through(captured, tmp_path):
    video = _upload("a.mp4", b"fakevideo")
    sub = _upload("a.srt", b"1\n00:00:01,000 --> 00:00:02,000\nhi\n")
    _run(server.compose_from_subtitle(
        file=video, subtitle=sub, output_video="soft", target_lang="English",
        current_user=SimpleNamespace(id=1, username="t", role="user"),
    ))
    assert captured["item"].target_lang == "English", "表单里的目标语言必须传到任务上"


def test_default_is_none(captured, tmp_path):
    # 注意：直接调用函数时传显式 "none"，对应 FastAPI 在 HTTP 层的默认值。
    # 不传参数拿到的是 Form 对象本身（默认值只在请求解析时求值），那不是真实运行路径。
    video = _upload("b.mp4", b"fakevideo")
    sub = _upload("b.srt", b"1\n00:00:01,000 --> 00:00:02,000\nhi\n")
    _run(server.compose_from_subtitle(
        file=video, subtitle=sub, output_video="soft", target_lang="none",
        current_user=SimpleNamespace(id=1, username="t", role="user"),
    ))
    assert captured["item"].target_lang == "none", "不翻译时保持老行为：只套用"


def test_blank_target_lang_falls_back_to_none(captured, tmp_path):
    video = _upload("c.mp4", b"fakevideo")
    sub = _upload("c.srt", b"1\n00:00:01,000 --> 00:00:02,000\nhi\n")
    _run(server.compose_from_subtitle(
        file=video, subtitle=sub, output_video="soft", target_lang="   ",
        current_user=SimpleNamespace(id=1, username="t", role="user"),
    ))
    assert captured["item"].target_lang == "none", "空串/空白要归一成 none，不能把空语言传给翻译器"