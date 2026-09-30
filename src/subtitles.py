# -*- coding: utf-8 -*-
"""
SubAI Translator —— 字幕文件解析与写回（在线字幕编辑）
=======================================================

供 API 读取任务产出的字幕并支持编辑后写回：
- 优先 JSON（pipeline 的 --output-format json：含 source/translation）
- 其次双语 SRT（<stem>.bilingual.srt：一条字幕内两行 = 原文 + 译文）
- 最后单语 SRT（仅译文）
"""
from __future__ import annotations

import json
import os


def _ts_to_seconds(ts: str) -> float:
    t = (ts or "").strip().replace(",", ".")
    parts = t.split(":")
    if len(parts) != 3:
        return 0.0
    try:
        h = int(parts[0])
        m = int(parts[1])
        s = float(parts[2])
    except ValueError:
        return 0.0
    return h * 3600 + m * 60 + s


def _seconds_to_ts(sec: float) -> str:
    ms = int(round(float(sec) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def parse_srt(path: str) -> list[dict]:
    """解析 SRT，返回 [{start, end, lines}]。"""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        raw = f.read().replace("\r\n", "\n").replace("\r", "\n")

    out: list[dict] = []
    for block in raw.split("\n\n"):
        block = block.strip("\n")
        if not block.strip():
            continue
        lines = block.split("\n")
        if lines and lines[0].strip().isdigit():
            lines = lines[1:]
        if not lines or "-->" not in lines[0]:
            continue
        left, _, right = lines[0].partition("-->")
        end_token = right.split()[0] if right.split() else right
        out.append({
            "start": _ts_to_seconds(left),
            "end": _ts_to_seconds(end_token),
            "lines": lines[1:],
        })
    return out


def _segments_bilingual(path: str) -> list[dict]:
    segs = []
    for i, s in enumerate(parse_srt(path), 1):
        lines = s["lines"]
        source = lines[0].strip() if lines else ""
        translation = " ".join(x.strip() for x in lines[1:]).strip() if len(lines) > 1 else ""
        segs.append({"index": i, "start": s["start"], "end": s["end"],
                     "source": source, "translation": translation})
    return segs


def _segments_mono(path: str) -> list[dict]:
    segs = []
    for i, s in enumerate(parse_srt(path), 1):
        segs.append({"index": i, "start": s["start"], "end": s["end"],
                     "source": "", "translation": " ".join(x.strip() for x in s["lines"]).strip()})
    return segs


def load_task_segments(result_files: list[str]) -> dict:
    """从任务输出文件中装载字幕段，返回 {kind, file, segments}。"""
    files = [f for f in (result_files or []) if f and os.path.isfile(f)]

    for f in files:
        if f.lower().endswith(".json"):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                segs = [{
                    "index": int(d.get("id", i + 1)),
                    "start": float(d.get("start", 0.0)),
                    "end": float(d.get("end", 0.0)),
                    "source": d.get("source", "") or "",
                    "translation": d.get("translation", "") or "",
                } for i, d in enumerate(data)]
            except Exception:  # noqa: BLE001
                segs = []
            if segs:
                return {"kind": "json", "file": f, "segments": segs}

    for f in files:
        if f.lower().endswith(".bilingual.srt"):
            segs = _segments_bilingual(f)
            if segs:
                return {"kind": "bilingual", "file": f, "segments": segs}

    for f in files:
        if f.lower().endswith(".srt"):
            segs = _segments_mono(f)
            if segs:
                return {"kind": "mono", "file": f, "segments": segs}

    return {"kind": None, "file": None, "segments": []}


def save_task_segments(file_path: str, kind: str, segments: list[dict]) -> str:
    """把字幕段写回原文件。"""
    if not file_path:
        raise ValueError("缺少目标文件")

    if kind == "json":
        data = [{
            "id": int(s.get("index") or i + 1),
            "start": float(s["start"]),
            "end": float(s["end"]),
            "start_ts": _seconds_to_ts(s["start"]),
            "end_ts": _seconds_to_ts(s["end"]),
            "source": s.get("source", "") or "",
            "translation": s.get("translation", "") or "",
        } for i, s in enumerate(segments)]
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return file_path

    lines: list[str] = []
    for i, s in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(_seconds_to_ts(s["start"]) + " --> " + _seconds_to_ts(s["end"]))
        if kind == "bilingual":
            lines.append(s.get("source", "") or "")
            if (s.get("translation", "") or "").strip():
                lines.append(s["translation"])
        else:
            lines.append((s.get("translation") or s.get("source") or "").strip())
        lines.append("")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return file_path
