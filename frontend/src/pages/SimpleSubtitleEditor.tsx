import { useEffect, useRef, useState } from 'react';
import { getTaskSubtitles, renderTaskVideo, saveTaskSubtitles } from '../api';
import type { SubtitleSegment } from '../types';
import '../styles/wizard.css';

const mmss = (t: number): string => {
  const s = Math.max(0, Math.floor(t || 0));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return (m < 10 ? '0' : '') + m + ':' + (r < 10 ? '0' : '') + r;
};

type Snap = { i: number; text: string; dirty: boolean };

export function SimpleSubtitleEditor({ taskId }: { taskId: string }) {
  const [segments, setSegments] = useState<SubtitleSegment[]>([]);
  const [cur, setCur] = useState(0);
  const [editing, setEditing] = useState(-1);
  const [draft, setDraft] = useState('');
  const [dirty, setDirty] = useState<Record<number, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [msg, setMsg] = useState('');
  const historyRef = useRef<Snap[]>([]);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    setMsg('正在读取字幕…');
    (async () => {
      try {
        const data = await getTaskSubtitles(taskId);
        if (!cancelled) { setSegments(data.segments || []); setMsg(''); setDirty({}); historyRef.current = []; setCur(0); }
      } catch {
        if (!cancelled) setMsg('读取字幕失败（任务可能还没产出字幕）');
      }
    })();
    return () => { cancelled = true; };
  }, [taskId]);

  useEffect(() => { if (editing >= 0 && inputRef.current) { inputRef.current.focus(); inputRef.current.select(); } }, [editing]);

  const textOf = (s: SubtitleSegment): string => s.translation || s.source || '';
  const dirtyCount = Object.values(dirty).filter(Boolean).length;

  const startEdit = (i: number) => {
    if (i < 0 || i >= segments.length) return;
    setCur(i);
    setDraft(textOf(segments[i]));
    setEditing(i);
  };

  const commit = () => {
    if (editing < 0) return;
    const i = editing;
    const before = textOf(segments[i]);
    const v = draft;
    if (v !== before) {
      historyRef.current.push({ i, text: before, dirty: !!dirty[i] });
      setSegments((prev) => prev.map((s, idx) => (idx === i ? { ...s, translation: v } : s)));
      setDirty((d) => ({ ...d, [i]: true }));
    }
    setEditing(-1);
  };

  const cancel = () => { setEditing(-1); };

  const undo = () => {
    const last = historyRef.current.pop();
    if (!last) { setMsg('没有可撤销的修改'); return; }
    setSegments((prev) => prev.map((s, idx) => (idx === last.i ? { ...s, translation: last.text } : s)));
    setDirty((d) => ({ ...d, [last.i]: last.dirty }));
    setCur(last.i);
    setMsg('已撤销第 ' + (last.i + 1) + ' 行的修改');
    setTimeout(() => setMsg(''), 2000);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (document.activeElement && document.activeElement.tagName) || '';
      const inInput = tag === 'INPUT' || tag === 'TEXTAREA';
      if (editing >= 0) {
        if (e.key === 'Enter') { e.preventDefault(); commit(); }
        else if (e.key === 'Escape') { e.preventDefault(); cancel(); }
        return;
      }
      if (inInput) return;
      if (e.ctrlKey && (e.key === 'z' || e.key === 'Z')) { e.preventDefault(); undo(); return; }
      if (e.key === 'ArrowDown') { e.preventDefault(); setCur((c) => (segments.length ? (c + 1) % segments.length : 0)); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); setCur((c) => (segments.length ? (c - 1 + segments.length) % segments.length : 0)); }
      else if (e.key === 'Enter') { e.preventDefault(); startEdit(cur); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  useEffect(() => {
    const el = document.getElementById('subrow-' + cur);
    if (el) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [cur]);

  const save = async (silent = false) => {
    setBusy(true);
    if (!silent) setMsg('');
    try {
      await saveTaskSubtitles(taskId, segments);
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
    setRendering(true);
    setMsg('');
    try {
      const okSave = await save(true);
      if (!okSave) return;
      await renderTaskVideo(taskId);
      setMsg('已开始生成视频，进度请看任务列表');
    } catch (e: any) {
      setMsg('生成失败：' + String(e?.response?.data?.detail || e?.message || e));
    } finally {
      setRendering(false);
    }
  };

  if (segments.length === 0) {
    return <div className="w-sub" style={{ marginTop: 18 }}>{msg || '没有可编辑的字幕'}</div>;
  }

  return (
    <div style={{ marginTop: 26 }}>
      <h2 className="w-h2">确认字幕（这一步还不出片）</h2>
      <div className="w-sub">点哪行改哪行；只改文字，时间不用管。<span className="w-kbd">↑</span><span className="w-kbd">↓</span> 切换行 · <span className="w-kbd">Enter</span> 编辑 · <span className="w-kbd">Esc</span> 退出 · <span className="w-kbd">Ctrl</span>+<span className="w-kbd">Z</span> 撤销</div>
      <div className="w-subs">
        {segments.map((s, i) => {
          const isCur = i === cur;
          const isEd = i === editing;
          return (
            <div
              key={i}
              id={'subrow-' + i}
              className={'w-subrow' + (isCur ? ' cur' : '')}
              onClick={() => (isEd ? undefined : setCur(i))}
              onDoubleClick={() => startEdit(i)}
            >
              <div className="w-time">{isCur ? '▶ ' : ''}{mmss(s.start) + ' → ' + mmss(s.end)}</div>
              <div className="w-text">
                {isEd ? (
                  <input
                    ref={inputRef}
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onClick={(e) => e.stopPropagation()}
                  />
                ) : (
                  <span>{textOf(s)}</span>
                )}
                {dirty[i] && !isEd && <span className="w-changed">已改</span>}
                {dirty[i] && !isEd && (
                  <span
                    className="w-undo"
                    title="撤销这一行的修改"
                    onClick={(e) => {
                      e.stopPropagation();
                      const before = historyRef.current.filter((h) => h.i === i).pop();
                      if (!before) { setMsg('这一行没有可撤销的修改'); return; }
                      setSegments((prev) => prev.map((x, idx) => (idx === i ? { ...x, translation: before.text } : x)));
                      historyRef.current = historyRef.current.filter((h) => h !== before);
                      setDirty((d) => ({ ...d, [i]: before.dirty }));
                      setMsg('已撤销第 ' + (i + 1) + ' 行的修改');
                    }}
                  >
                    ↩ 撤销
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <div className="w-center">
        <button className="w-btn w-primary" disabled={busy || rendering} onClick={() => void confirmAndRender()}>
          {rendering ? '正在生成视频…' : '确认无误，生成视频'}</button>
        <button className="w-btn w-ghost" disabled={busy || rendering} onClick={() => void save()}>
          {busy ? '保存中…' : '只保存字幕'}</button>
      </div>
      <div className="w-msg">{msg}{dirtyCount > 0 && !msg ? ('已改 ' + dirtyCount + ' 处（点「确认无误，生成视频」才会出片）') : ''}</div>
    </div>
  );
}
