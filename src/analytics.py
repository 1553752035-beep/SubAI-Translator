# -*- coding: utf-8 -*-
"""四期 4.6 数据分析：使用统计、质量分析与报表导出。

数据来源是**任务表本身**（含 4.6 新增的 metrics 列），不额外维护一套统计，
因此"报表里的数字"和"任务列表里的数字"永远一致。

导出格式：
- XLSX：手写最小 OOXML（零依赖，Excel/WPS 可直接打开，文字可选中）
- PDF ：PIL 渲染（**支持中文**，因为标准 PDF 字体不含 CJK；见 docs 里的说明）
- HTML：可直接用浏览器打印成 PDF
"""
from __future__ import annotations

import io
import json
import os
import time
import zipfile
from datetime import datetime
from typing import Optional

import aiosqlite

logger = __import__("logging").getLogger(__name__)

#: 报表里用到的中文标题（导出时统一取这里，避免各处硬编码）
TITLES = {
    "summary": "SubAI Translator 使用统计报表",
    "quality": "SubAI Translator 质量分析报表",
}


def _day(ts: Optional[float]) -> str:
    if not ts:
        return ""
    return time.strftime("%Y-%m-%d", time.localtime(ts))


async def _rows(db_path: str, days: int, user_id: Optional[str] = None) -> list:
    since = time.time() - max(1, int(days)) * 86400
    if not os.path.isfile(db_path):
        return []
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        sql = "SELECT * FROM tasks WHERE created_at >= ?"
        args: list = [since]
        if user_id:
            sql += " AND user_id = ?"
            args.append(user_id)
        sql += " ORDER BY created_at DESC"
        async with db.execute(sql, args) as cur:
            return [dict(r) for r in await cur.fetchall()]


def _metrics_of(row: dict) -> dict:
    raw = row.get("metrics")
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


async def summary(db_path: str, days: int = 30, user_id: Optional[str] = None) -> dict:
    """使用统计：任务量、成功率、耗时、翻译量与命中率。"""
    rows = await _rows(db_path, days, user_id)
    total = len(rows)
    by_status: dict = {}
    by_mode: dict = {}
    by_lang: dict = {}
    daily: dict = {}
    lines_total = lines_failed = terms_hit = cache_hits = llm_requests = files_total = 0
    durations: list = []
    with_metrics = 0

    for row in rows:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
        by_mode[row["mode"]] = by_mode.get(row["mode"], 0) + 1
        lang = row.get("target_lang") or "?"
        by_lang[lang] = by_lang.get(lang, 0) + 1
        key = _day(row.get("created_at"))
        bucket = daily.setdefault(key, {"day": key, "total": 0, "completed": 0, "failed": 0})
        bucket["total"] += 1
        if row["status"] == "completed":
            bucket["completed"] += 1
        elif row["status"] == "failed":
            bucket["failed"] += 1
        if row.get("completed_at") and row.get("created_at"):
            durations.append(max(0.0, float(row["completed_at"]) - float(row["created_at"])))
        m = _metrics_of(row)
        if m:
            with_metrics += 1
        lines_total += int(m.get("lines_total", 0) or 0)
        lines_failed += int(m.get("lines_failed", 0) or 0)
        terms_hit += int(m.get("terms_hit", 0) or 0)
        cache_hits += int(m.get("cache_hits", 0) or 0)
        llm_requests += int(m.get("llm_requests", 0) or 0)
        files_total += int(m.get("files", 0) or 0)

    completed = by_status.get("completed", 0)
    failed = by_status.get("failed", 0)
    finished = completed + failed
    durations.sort()

    def percentile(pct: float) -> float:
        if not durations:
            return 0.0
        idx = min(len(durations) - 1, int(round((len(durations) - 1) * pct)))
        return round(durations[idx], 2)

    return {
        "range_days": days,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tasks": {
            "total": total,
            "by_status": by_status,
            "by_mode": by_mode,
            "by_target_lang": dict(sorted(by_lang.items(), key=lambda kv: kv[1], reverse=True)[:15]),
            "completed": completed,
            "failed": failed,
            "success_rate": round(completed / finished, 4) if finished else 1.0,
        },
        "volume": {
            "lines_total": lines_total,
            "lines_failed": lines_failed,
            "terms_hit": terms_hit,
            "cache_hits": cache_hits,
            "llm_requests": llm_requests,
            "output_files": files_total,
            "term_hit_rate": round(terms_hit / lines_total, 4) if lines_total else 0.0,
            "cache_hit_rate": round(cache_hits / lines_total, 4) if lines_total else 0.0,
            "line_failure_rate": round(lines_failed / lines_total, 4) if lines_total else 0.0,
        },
        "duration": {
            "avg_s": round(sum(durations) / len(durations), 2) if durations else 0.0,
            "p50_s": percentile(0.5),
            "p90_s": percentile(0.9),
            "max_s": round(durations[-1], 2) if durations else 0.0,
        },
        "daily": sorted(daily.values(), key=lambda d: d["day"]),
        "coverage": {
            "tasks_with_metrics": with_metrics,
            "tasks_without_metrics": total - with_metrics,
            "note": "metrics 从四期 4.6 起写入；更早的历史任务没有指标明细",
        },
    }


async def quality(db_path: str, days: int = 30, user_id: Optional[str] = None) -> dict:
    """质量分析：成功率、失败原因分布、耗时分布与已知的数据缺口。"""
    rows = await _rows(db_path, days, user_id)
    total = len(rows)
    reasons: dict = {}
    lines_total = lines_failed = 0
    partial = 0
    clean = 0
    for row in rows:
        if row["status"] == "failed" and row.get("error_message"):
            key = str(row["error_message"])[:120]
            reasons[key] = reasons.get(key, 0) + 1
        m = _metrics_of(row)
        lt = int(m.get("lines_total", 0) or 0)
        lf = int(m.get("lines_failed", 0) or 0)
        lines_total += lt
        lines_failed += lf
        if lt and 0 < lf < lt:
            partial += 1
        elif lt and lf == 0:
            clean += 1
    return {
        "range_days": days,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tasks": {
            "total": total,
            "clean": clean,
            "partial": partial,
            "failed": sum(1 for r in rows if r["status"] == "failed"),
            "success_rate": round(
                sum(1 for r in rows if r["status"] == "completed")
                / max(sum(1 for r in rows if r["status"] in ("completed", "failed")), 1), 4),
        },
        "lines": {
            "total": lines_total,
            "failed": lines_failed,
            "failure_rate": round(lines_failed / lines_total, 4) if lines_total else 0.0,
        },
        "top_failure_reasons": [{"reason": k, "count": v}
                                for k, v in sorted(reasons.items(), key=lambda kv: kv[1], reverse=True)[:10]],
        "unavailable_metrics": {
            "asr_confidence_avg": None,
            "translation_score": None,
            "note": "识别置信度目前只写在日志里、未随任务持久化，因此这里如实留空，不做推测",
        },
    }


# --------------------------------------------------------------------------- #
# 报表：把统计变成可交付的文件
# --------------------------------------------------------------------------- #

def _flatten(section: str, data: dict) -> list:
    """把嵌套统计压成 (分组, 指标, 值) 三元组列表，三种导出共用。"""
    rows: list = []

    def walk(prefix: str, value, depth: int = 0):
        if isinstance(value, dict):
            for k, v in value.items():
                walk(("%s / %s" % (prefix, k)) if prefix else k, v, depth + 1)
        elif isinstance(value, list):
            if value and isinstance(value[0], dict):
                for item in value:
                    label = str(item.get("day") or item.get("reason") or item.get("code") or "项")
                    for k, v in item.items():
                        if k in ("day", "reason", "code"):
                            continue
                        rows.append((prefix, "%s · %s" % (label, k), v))
            else:
                rows.append((prefix, "count", len(value)))
        else:
            rows.append((prefix.split(" / ")[0] if " / " in prefix else section, prefix, value))

    walk("", data)
    # 统一成 (分组, 指标, 值)
    out = []
    for group, metric, value in rows:
        out.append((group or section, metric, value))
    return out


def export_html(title: str, data: dict) -> str:
    """生成 HTML 报表（可直接用浏览器打印成 PDF）。"""
    rows = _flatten("数据", data)
    body = "\n".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (g, m, v) for g, m, v in rows
    )
    return (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<title>%s</title><style>"
        "body{font-family:\"Microsoft YaHei\",sans-serif;margin:32px;color:#222}"
        "h1{font-size:20px}table{border-collapse:collapse;width:100%%;font-size:13px}"
        "th,td{border:1px solid #ddd;padding:6px 8px;text-align:left}"
        "th{background:#f5f5f5}tr:nth-child(even) td{background:#fafafa}"
        "</style></head><body><h1>%s</h1><p>生成时间：%s</p>"
        "<table><thead><tr><th>分组</th><th>指标</th><th>值</th></tr></thead><tbody>"
        "%s</tbody></table></body></html>"
    ) % (title, title, data.get("generated_at", datetime.now().isoformat(timespec="seconds")), body)


def _col_name(idx: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA"""
    name = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        name = chr(65 + rem) + name
    return name


def _xml_escape(text) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def export_xlsx(title: str, data: dict) -> bytes:
    """手写最小 OOXML：零依赖，Excel/WPS 可直接打开，文字可选中。"""
    rows = [["分组", "指标", "值"], ["生成时间", "generated_at", data.get("generated_at", "")]]
    rows += [[g, m, v] for g, m, v in _flatten("数据", data)]

    sheet = ["<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>",
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
    for r_idx, row in enumerate(rows, start=1):
        sheet.append('<row r="%d">' % r_idx)
        for c_idx, value in enumerate(row):
            ref = "%s%d" % (_col_name(c_idx), r_idx)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                sheet.append('<c r="%s"><v>%s</v></c>' % (ref, value))
            else:
                sheet.append('<c r="%s" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>'
                             % (ref, _xml_escape(value)))
        sheet.append("</row>")
    sheet.append("</sheetData></worksheet>")
    sheet_xml = "".join(sheet)

    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                     '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                     "</Types>")
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                 "</Relationships>")
    workbook = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                "<sheets><sheet name=\"%s\" sheetId=\"1\" r:id=\"rId1\"/></sheets></workbook>" % _xml_escape(title[:28]))
    wb_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
               "</Relationships>")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buf.getvalue()


#: 中文字体候选（PDF 需要 CJK 字体，标准 PDF 字体不含中文）
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyh.ttf",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\Deng.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
]


def find_cjk_font() -> Optional[str]:
    for path in FONT_CANDIDATES:
        if os.path.isfile(path):
            return path
    root = None
    try:
        from src.config import config

        root = config.paths.root
    except Exception:  # noqa: BLE001
        root = None
    if root:
        for name in ("msyh.ttc", "msyh.ttf", "simhei.ttf", "font.ttf"):
            cand = os.path.join(root, "bin", name)
            if os.path.isfile(cand):
                return cand
    return None


def export_pdf(title: str, data: dict) -> bytes:
    """用 PIL 渲染 PDF：保证中文可读（标准 PDF 字体不含 CJK，这是务实取舍）。"""
    from PIL import Image, ImageDraw, ImageFont

    rows = [("分组", "指标", "值")] + [(g, m, str(v)) for g, m, v in _flatten("数据", data)]
    font_path = find_cjk_font()
    if font_path:
        font = ImageFont.truetype(font_path, 18)
        font_title = ImageFont.truetype(font_path, 30)
        font_head = ImageFont.truetype(font_path, 20)
    else:  # pragma: no cover - 无 CJK 字体的环境
        font = ImageFont.load_default()
        font_title = font
        font_head = font

    width, height = 1240, 1754   # A4 @150dpi
    margin, line_h = 60, 30
    pages = []
    page = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(page)
    y = margin
    draw.text((margin, y), title, fill="black", font=font_title)
    y += 50
    draw.text((margin, y), "生成时间: %s" % data.get("generated_at", ""), fill="#444", font=font)
    y += 50
    for g, m, v in rows:
        if y > height - margin - line_h:
            pages.append(page)
            page = Image.new("RGB", (width, height), "white")
            draw = ImageDraw.Draw(page)
            y = margin
        text = "%-28s %-40s %s" % (str(g)[:28], str(m)[:40], v)
        draw.text((margin, y), text, fill="black", font=font_head if g == "分组" else font)
        y += line_h
    pages.append(page)

    out = io.BytesIO()
    pages[0].save(out, format="PDF", save_all=True, append_images=pages[1:], resolution=150.0)
    return out.getvalue()


def build_report(kind: str, data: dict) -> dict:
    """生成报表标题与三种格式的内容（供 API 直接返回）。"""
    title = TITLES.get(kind, "SubAI Translator 报表")
    return {
        "title": title,
        "html": export_html(title, data),
        "xlsx": export_xlsx(title, data),
        "pdf": export_pdf(title, data),
    }
