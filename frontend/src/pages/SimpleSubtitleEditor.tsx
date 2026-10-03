import { useEffect, useRef, useState } from 'react';
import { getTaskStatus, getTaskSubtitles, renderTaskVideo, saveTaskSubtitles } from '../api';
import type { SubtitleSegment } from '../types';
import '../styles/wizard.css';

type Row = { id: string; start: number; end: number; source: string; translation: string; words?: number[] };

/** 撤销动作：只记动作与稳定 id，不记行号索引——用户先拆后删再撤销也不会错位 */
type Act =
  | { kind: 'edit'; id: string; before: string; after: string }
  | { kind: 'merge'; ids: string[]; before: [Row, Row]; after: Row }
  | { kind: 'split'; id: string; before: Row; after: [Row, Row] };

const mmss = (t: number): string => {
  const s = Math.max(0, Math.floor(t || 0));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return (m < 10 ? '0' : '') + m + ':' + (r < 10 ? '0' : '') + r;
};

let seq = 0;
const newId = (): string => 'r' + (++seq).toString(36) + Date.now().toString(36).slice(-4);

export function SimpleSubtitleEditor({ taskId, onClose }: { taskId: string; onClose?: () => void }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [cur, setCur] = useState(0);
  const [editing, setEditing] = useState(-1);
  const [draft, setDraft] = useState('');
  const [dirty, setDirty] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [msg, setMsg] = useState('');
  const [splitting, setSplitting] = useState<{ id: string; pos: number; at: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [videoUrl, setVideoUrl] = useState('');
  const stackRef = useRef<Act[]>([]);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const t = await getTaskStatus(taskId);
        const vp = (t as unknown as { video_path?: string }).video_path || "";
        if (!vp) return;
        const { convertFileSrc } = await import("@tauri-apps/api/core");
        setVideoUrl(convertFileSrc(vp));
      } catch { /* 预览不可用不影响编辑 */ }
    })();
  }, [taskId]);

  useEffect(() => {
    let cancelled = false;
    setMsg('正在读取字幕…');
    (async () => {
      try {
        const data = await getTaskSubtitles(taskId);
        if (cancelled) return;
        const list: Row[] = (data.segments || []).map((s: SubtitleSegment) => ({
          id: newId(),
          start: s.start,
          end: s.end,
          source: s.source || '',
          translation: s.translation || '',
          words: (s as SubtitleSegment & { words?: number[] }).words,
        }));
        setRows(list);
        setDirty({});
        stackRef.current = [];
        setCur(0);
        setMsg('');
      } catch {
        if (!cancelled) setMsg('读取字幕失败（任务可能还没产出字幕）');
      }
    })();
    return () => { cancelled = true; };
  }, [taskId]);

  useEffect(() => { if (editing >= 0 && inputRef.current) { inputRef.current.focus(); inputRef.current.select(); } }, [editing]);

  const textOf = (r: Row): string => r.translation || r.source || '';
  const dirtyCount = Object.values(dirty).filter(Boolean).length;

  const suspectOf = (r: Row): string => {
    const t = textOf(r).trim();
    if (!t) return '空';
    const dur = Math.max(0, (r.end || 0) - (r.start || 0));
    const cjk = (t.match(/[\u4e00-\u9fff]/g) || []).length;
    if (cjk > 0 && cjk <= 2 && dur >= 1.5) return '可能漏字';
    if (cjk >= 1 && dur / cjk >= 1.2) return '语速异常';
    if (!/[\u4e00-\u9fff]/.test(t) && /[A-Za-z]{3,}/.test(t)) return '疑似外文';
    if (/^\d{1,3}$/.test(t)) return '疑似数字';
    return '';
  };
  const suspectCount = rows.filter((r) => !!suspectOf(r)).length;

  const pushAct = (a: Act) => { stackRef.current.push(a); };

  const startEdit = (i: number) => {
    if (i < 0 || i >= rows.length) return;
    setCur(i);
    setDraft(textOf(rows[i]));
    setEditing(i);
  };

  const commit = () => {
    if (editing < 0) return;
    const r = rows[editing];
    const before = textOf(r);
    if (draft !== before) {
      pushAct({ kind: 'edit', id: r.id, before, after: draft });
      setRows((prev) => prev.map((x) => (x.id === r.id ? { ...x, translation: draft } : x)));
      setDirty((d) => ({ ...d, [r.id]: true }));
    }
    setEditing(-1);
  };

  const mergeRows = (i: number, dir: 'up' | 'down') => {
    const j = dir === 'up' ? i - 1 : i + 1;
    if (j < 0 || j >= rows.length) { setMsg('已经到头了'); return; }
    const a = dir === 'up' ? rows[j] : rows[i];
    const b = dir === 'up' ? rows[i] : rows[j];
    const merged: Row = {
      id: a.id,
      start: a.start,
      end: b.end,
      source: (a.source || '') + (b.source || ''),
      translation: textOf(a) + textOf(b),
      words: [...(a.words || [a.start]), ...(b.words || [b.end])],
    };
    pushAct({ kind: 'merge', ids: [a.id, b.id], before: [a, b], after: merged });
    setRows((prev) => { const next = [...prev]; next.splice(j, 2, merged); return next; });
    setDirty((d) => { const n = { ...d }; delete n[a.id]; delete n[b.id]; n[merged.id] = true; return n; });
    setCur(j);
    setMsg('已合并两行（Ctrl+Z 可撤销）');
  };

  /** 找离时间 t 最近的词边界（拿不到词边界时退化为起止点） */
  const nearestWord = (r: Row, t: number): { at: number; dist: number } => {
    const ws = (r.words && r.words.length >= 2) ? r.words : [r.start, r.end];
    let best = ws[0];
    let d = Infinity;
    for (const w of ws) { const dd = Math.abs(w - t); if (dd < d) { d = dd; best = w; } }
    return { at: best, dist: d };
  };

  /** 把鼠标横坐标换算成时间（含词边界吸附） */
  const moveAt = (el: HTMLDivElement, clientX: number, r: Row) => {
    const box = el.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (clientX - box.left) / box.width));
    const raw = r.start + ratio * Math.max(0.01, r.end - r.start);
    const w = nearestWord(r, raw);
    setSplitting((prev) => (prev ? { ...prev, at: w.dist < 0.18 ? w.at : raw } : prev));
  };

  /** 在编辑态按 Ctrl+Enter：以光标处为意图，切点默认吸附到最近的词边界 */
  const openSplit = () => {
    if (editing < 0) return;
    const r = rows[editing];
    const pos = Math.max(1, Math.min(textOf(r).length - 1, inputRef.current?.selectionStart ?? Math.floor(textOf(r).length / 2)));
    const mid = r.start + (r.end - r.start) * (pos / Math.max(1, textOf(r).length));
    const w = nearestWord(r, mid);
    setSplitting({ id: r.id, pos, at: w.at });
    setMsg('切点已默认吸附到最近的词边界，可拖动微调');
  };

  const doSplit = () => {
    if (!splitting) return;
    const r = rows.find((x) => x.id === splitting.id);
    if (!r) { setSplitting(null); return; }
    const at = splitting.at;
    const pos = splitting.pos;
    const t = textOf(r);
    const ws = (r.words && r.words.length >= 2) ? r.words : [r.start, r.end];
    const a: Row = { ...r, end: at, translation: t.slice(0, pos), source: (r.source || '').slice(0, pos), words: ws.filter((w) => w <= at).concat([at]) };
    const b: Row = { ...r, id: newId(), start: at, translation: t.slice(pos), source: (r.source || '').slice(pos), words: [at].concat(ws.filter((w) => w > at)) };
    pushAct({ kind: 'split', id: r.id, before: r, after: [a, b] });
    setRows((prev) => {
      const k = prev.findIndex((x) => x.id === r.id);
      const next = [...prev];
      if (k >= 0) next.splice(k, 1, a, b);
      return next;
    });
    setDirty((d) => ({ ...d, [a.id]: true, [b.id]: true }));
    setSplitting(null);
    setEditing(-1);
    setMsg('已拆分为两行（Ctrl+Z 可撤销）');
  };

  const undo = () => {
    const a = stackRef.current.pop();
    if (!a) { setMsg('没有可撤销的操作'); return; }
    if (a.kind === 'edit') {
      setRows((prev) => prev.map((x) => (x.id === a.id ? { ...x, translation: a.before } : x)));
      setDirty((d) => ({ ...d, [a.id]: false }));
      setMsg('已撤销修改');
    } else if (a.kind === 'merge') {
      setRows((prev) => {
        const k = prev.findIndex((x) => x.id === a.after.id);
        const next = [...prev];
        if (k >= 0) next.splice(k, 1, a.before[0], a.before[1]); else next.push(a.before[0], a.before[1]);
        return next;
      });
      setMsg('已撤销合并');
    } else {
      setRows((prev) => {
        const k = prev.findIndex((x) => x.id === a.after[0].id || x.id === a.after[1].id);
        const next = [...prev];
        if (k >= 0) next.splice(k, Math.min(k + 2, next.length) - k, a.before); else next.push(a.before);
        return next;
      });
      setMsg('已撤销拆分');
    }
    setTimeout(() => setMsg(''), 2000);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (document.activeElement && document.activeElement.tagName) || '';
      const inInput = tag === 'INPUT' || tag === 'TEXTAREA';
      if (editing >= 0) {
        if (e.key === 'Enter' && e.ctrlKey) { e.preventDefault(); openSplit(); return; }
        if (e.key === 'Enter') { e.preventDefault(); commit(); }
        else if (e.key === 'Escape') { e.preventDefault(); setEditing(-1); }
        return;
      }
      if (inInput) return;
      if (e.ctrlKey && (e.key === 'z' || e.key === 'Z')) { e.preventDefault(); undo(); return; }
      if (e.key === 'ArrowDown') { e.preventDefault(); setCur((c) => (rows.length ? (c + 1) % rows.length : 0)); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); setCur((c) => (rows.length ? (c - 1 + rows.length) % rows.length : 0)); }
      else if (e.key === 'Enter') { e.preventDefault(); startEdit(cur); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  useEffect(() => {
    const r = rows[cur];
    if (!r) return;
    const el = document.getElementById('subrow-' + r.id);
    if (el) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [cur, rows]);

  const save = async (silent = false) => {
    setBusy(true);
    if (!silent) setMsg('');
    try {
      const segs: SubtitleSegment[] = rows.map((r) => ({ start: r.start, end: r.end, source: r.source, translation: r.translation }));
      await saveTaskSubtitles(taskId, segs);
      setMsg('已保存，字幕文件已更新');
      return true;
    } catch (e: any) {
      setMsg('保存失败：' + String(e?.response?.data?.detail || e?.message || e));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const confirmAndRender = async () => {
    if (suspectCount > 0 && !window.confirm('还有 ' + suspectCount + ' 处可疑字幕没确认，继续生成可能把错字放进视频。\n\n仍然继续吗？')) return;
    setRendering(true);
    setMsg('');
    try {
      const ok = await save(true);
      if (!ok) return;
      await renderTaskVideo(taskId);
      setMsg('已开始生成视频，进度请看任务列表');
    } catch (e: any) {
      setMsg('生成失败：' + String(e?.response?.data?.detail || e?.message || e));
    } finally {
      setRendering(false);
    }
  };

  if (rows.length === 0) {
    return <div className="w-sub" style={{ marginTop: 18 }}>{msg || '没有可编辑的字幕'}</div>;
  }

  return (
    <div className="w-conf">
      <div className="w-conf-top">
        <div>
          <h2 className="w-h2">确认字幕（这一步还不出片）</h2>
          <div className="w-conf-stat">共 {rows.length} 行　·　<b style={{ color: '#8a5a00' }}>可疑 {suspectCount} 处</b>　·　已改 {dirtyCount} 处</div>
          <div className="w-sub" style={{ marginTop: 6 }}><span className="w-kbd">↑</span><span className="w-kbd">↓</span> 切换行 · <span className="w-kbd">Enter</span> 编辑 · <span className="w-kbd">Esc</span> 退出 · <span className="w-kbd">Ctrl</span>+<span className="w-kbd">Z</span> 撤销 · 编辑时 <span className="w-kbd">Ctrl</span>+<span className="w-kbd">Enter</span> 拆分</div>
        </div>
        {onClose && <button className="w-btn w-ghost" onClick={onClose}>← 返回主界面</button>}
      </div>
      <div className="w-conf-grid">
        <div>
          <div className="w-conf-card" style={{ padding: 14 }}>
            <div className="w-player">
              {videoUrl ? <video src={videoUrl} controls preload="metadata" /> : <div className="ph">原视频预览（当前环境不可播放，可直接打开原文件）</div>}
            </div>
            <div className="w-bar">
              {rows.map((r2) => (
                <span key={r2.id} className="seg" style={{ left: ((r2.start / Math.max(0.01, rows[rows.length - 1]?.end || 1)) * 100) + '%', width: ((Math.max(0.05, r2.end - r2.start) / Math.max(0.01, rows[rows.length - 1]?.end || 1)) * 100) + '%' }} />
              ))}
              {rows.map((r2, k) => (suspectOf(r2) ? <span key={'d' + r2.id} className="dot" style={{ left: ((r2.start / Math.max(0.01, rows[rows.length - 1]?.end || 1)) * 100) + '%' }} title={'可疑：' + textOf(r2)} onClick={() => setCur(k)} /> : null))}
              <span className="head" style={{ left: (((rows[cur] ? rows[cur].start : 0) / Math.max(0.01, rows[rows.length - 1]?.end || 1)) * 100) + '%' }} />
            </div>
            <div className="w-legend">
              <span><s />有字幕</span>
              <span><i />可疑（点黄点跳过去）</span>
              <span style={{ color: 'var(--w-accent)' }}>▶ 当前行</span>
              <span style={{ marginLeft: 'auto' }}>第 {cur + 1} / {rows.length} 行</span>
            </div>
          </div>
        </div>
        <div className="w-conf-card">
          <div className="w-conflist">
            <div className="w-subs" style={{ marginTop: 0, border: 0, boxShadow: 'none', background: 'transparent', padding: 0 }}>
      <div className="w-subs">
        {rows.map((r, i) => {
          const isCur = i === cur;
          const isEd = i === editing;
          const sus = suspectOf(r);
          return (
            <div
              key={r.id}
              id={'subrow-' + r.id}
              className={'w-subrow' + (isCur ? ' cur' : '') + (sus ? ' suspect' : '')}
              onClick={() => { if (!isEd) { setCur(i); setMenuFor(null); } }}
              onDoubleClick={() => startEdit(i)}
            >
              <div className="w-time">{isCur ? '▶ ' : ''}{mmss(r.start) + ' → ' + mmss(r.end)}</div>
              <div className="w-text">
                {isEd && splitting && splitting.id === r.id && (
                  <span className="w-split-hint">光标处按 Ctrl+Enter 拆分</span>
                )}
                {isEd ? (
                  <input ref={inputRef} value={draft} onChange={(e) => setDraft(e.target.value)} onClick={(e) => e.stopPropagation()} />
                ) : (
                  <span>{textOf(r)}{sus && <span className="w-suspect">{sus}</span>}</span>
                )}
                {!isEd && (
                  <span className="w-rowacts">
                    <span className="w-merge" title="断句修正" onClick={(e) => { e.stopPropagation(); setMenuFor(menuFor === r.id ? null : r.id); }}>断句</span>
                  </span>
                )}
                {menuFor === r.id && (
                  <span className="w-menu" onClick={(e) => e.stopPropagation()}>
                    {i > 0 && <span className="w-menu-item" onClick={() => { mergeRows(i, 'up'); setMenuFor(null); }}>⇧ 并入上行</span>}
                    {i < rows.length - 1 && <span className="w-menu-item" onClick={() => { mergeRows(i, 'down'); setMenuFor(null); }}>⇩ 并入下行</span>}
                    <span className="w-menu-tip">拆分：双击进编辑后按 Ctrl+Enter</span>
                  </span>
                )}
                {dirty[r.id] && !isEd && <span className="w-changed">已改</span>}
              </div>
                {splitting && splitting.id === r.id && (
                  <div className="w-splitpanel">
                    <div className="w-sp-bar">
                      <div className="w-sp-chip"><b>{textOf(r).slice(0, splitting.pos) || '（空）'}</b><em>{(splitting.at - r.start).toFixed(1)}s</em></div>
                      <div className="w-sp-chip"><b>{textOf(r).slice(splitting.pos) || '（空）'}</b><em>{(r.end - splitting.at).toFixed(1)}s</em></div>
                    </div>
                    <div
                      className="w-sp-track"
                      onPointerDown={(e) => {
                        e.stopPropagation();
                        (e.currentTarget as HTMLDivElement).setPointerCapture(e.pointerId);
                        setDragging(true);
                        moveAt(e.currentTarget as HTMLDivElement, e.clientX, r);
                      }}
                      onPointerMove={(e) => {
                        if (!dragging) return;
                        moveAt(e.currentTarget as HTMLDivElement, e.clientX, r);
                      }}
                      onPointerUp={(e) => {
                        setDragging(false);
                        try { (e.currentTarget as HTMLDivElement).releasePointerCapture(e.pointerId); } catch { /* 忽略 */ }
                      }}
                    >
                      <div className="w-sp-base" />
                      <div className="w-sp-fill" style={{ width: (((splitting.at - r.start) / Math.max(0.01, r.end - r.start)) * 100) + '%' }} />
                      {((r.words && r.words.length >= 2) ? r.words : [r.start, r.end]).map((w, k) => (
                        <span key={k} className={'w-sp-tick' + (nearestWord(r, splitting.at).dist < 0.18 && Math.abs(w - nearestWord(r, splitting.at).at) < 1e-6 ? ' hit' : '')} style={{ left: (((w - r.start) / Math.max(0.01, r.end - r.start)) * 100) + '%' }} />
                      ))}
                      <span className={'w-sp-cursor' + (nearestWord(r, splitting.at).dist < 0.18 ? ' snapped' : '')} style={{ left: (((splitting.at - r.start) / Math.max(0.01, r.end - r.start)) * 100) + '%' }} />
                      {nearestWord(r, splitting.at).dist < 0.18 && <span className="w-sp-snap" style={{ left: (((splitting.at - r.start) / Math.max(0.01, r.end - r.start)) * 100) + '%' }}>已吸附: {splitting.at.toFixed(1)}s</span>}
                    </div>
                    <div className="w-sp-hint">
                      <span>拖动可微调 · 虚线圆点是词边界，靠近会自动吸附</span>
                      <span>{nearestWord(r, splitting.at).dist < 0.18 ? '已吸附到词边界 ✓' : '自由位置（未吸附）'}</span>
                    </div>
                    {r.end - splitting.at < 0.5 && <div className="w-sp-warn">⚠ 第二句只有 {(r.end - splitting.at).toFixed(1)}s，不足 0.5 秒，可能听不清</div>}
                    <div className="w-sp-acts">
                      <button className="w-btn w-ghost" onClick={(ev) => { ev.stopPropagation(); setSplitting(null); setMsg('已取消拆分'); }}>取消</button>
                      <button
                        className="w-btn w-primary"
                        onClick={(ev) => {
                          ev.stopPropagation();
                          const right = r.end - splitting.at;
                          if (right < 0.5 && !window.confirm('第二句只有 ' + right.toFixed(1) + 's，不足 0.5 秒，烧录后可能一闪而过。\n\n仍然拆分吗？')) return;
                          doSplit();
                        }}
                      >确认拆分</button>
                    </div>
                  </div>
                )}
            </div>
          );
        })}
      </div>
            </div>
          </div>
        </div>
      </div>
      <div className="w-conf-foot">
        <span className="stat">{dirtyCount > 0 ? '本次改动 ' + dirtyCount + ' 处，将记入「待确认纠错」' : '还没有改动'}</span>
        <button className="w-btn w-ghost" disabled={busy || rendering} onClick={() => void save()}>{busy ? '保存中…' : '保存草稿'}</button>
        <button className="w-btn w-primary" disabled={busy || rendering} onClick={() => void confirmAndRender()}>{rendering ? '正在生成视频…' : '确认无误，生成视频'}</button>
      </div>
      <div className="w-msg">{msg}{dirtyCount > 0 && !msg ? ('已改 ' + dirtyCount + ' 处（点「确认无误，生成视频」才会出片）') : ''}</div>
    </div>
  );
}
