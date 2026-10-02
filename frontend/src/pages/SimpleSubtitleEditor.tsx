import { useEffect, useState } from 'react';
import { getTaskSubtitles, renderTaskVideo, saveTaskSubtitles } from '../api';
import type { SubtitleSegment } from '../types';
import '../styles/wizard.css';

const mmss = (t: number): string => {
  const s = Math.max(0, Math.floor(t || 0));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return (m < 10 ? '0' : '') + m + ':' + (r < 10 ? '0' : '') + r;
};

export function SimpleSubtitleEditor({ taskId }: { taskId: string }) {
  const [segments, setSegments] = useState<SubtitleSegment[]>([]);
  const [editing, setEditing] = useState<number>(-1);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [rendering, setRendering] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setMsg('正在读取字幕…');
    (async () => {
      try {
        const data = await getTaskSubtitles(taskId);
        if (!cancelled) {
          setSegments(data.segments || []);
          setMsg('');
        }
      } catch {
        if (!cancelled) setMsg('读取字幕失败（任务可能还没产出字幕）');
      }
    })();
    return () => { cancelled = true; };
  }, [taskId]);

  const textOf = (s: SubtitleSegment): string => s.translation || s.source || '';

  const change = (i: number, v: string) => {
    setSegments((prev) => prev.map((s, idx) => (idx === i ? { ...s, translation: v } : s)));
  };

  const confirmAndRender = async () => {
    setRendering(true);
    setMsg('');
    try {
      await saveTaskSubtitles(taskId, segments);          // 先存字幕
      await renderTaskVideo(taskId);                       // 再出片（这一步才生成视频）
      setMsg('已开始生成视频，进度请看任务列表');
    } catch (e: any) {
      setMsg('生成失败：' + String(e?.response?.data?.detail || e?.message || e));
    } finally {
      setRendering(false);
    }
  };

  const save = async () => {
    setBusy(true);
    setMsg('');
    try {
      await saveTaskSubtitles(taskId, segments);
      setMsg('已保存，字幕文件已更新');
    } catch (e: any) {
      setMsg('保存失败：' + String(e?.response?.data?.detail || e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  if (segments.length === 0) {
    return <div className="w-sub" style={{ marginTop: 18 }}>{msg || '没有可编辑的字幕'}</div>;
  }

  return (
    <div style={{ marginTop: 26 }}>
      <h2 className="w-h2">改字幕</h2>
      <div className="w-sub">点哪一行就改哪一行；只改文字，时间不用管。</div>
      <div className="w-subs">
        {segments.map((s, i) => (
          <div className="w-subrow" key={i} onClick={() => setEditing(i)}>
            <div className="w-time">{mmss(s.start) + ' → ' + mmss(s.end)}</div>
            <div className="w-text">
              {editing === i ? (
                <input
                  autoFocus
                  value={textOf(s)}
                  onChange={(e) => change(i, e.target.value)}
                  onBlur={() => setEditing(-1)}
                  onKeyDown={(e) => { if (e.key === 'Enter') setEditing(-1); }}
                />
              ) : (
                <span>{textOf(s)}</span>
              )}
            </div>
          </div>
        ))}
      </div>
      <div className="w-center">
        <button className="w-btn w-primary" disabled={busy || rendering} onClick={() => void confirmAndRender()}>
          {rendering ? '正在生成视频…' : '确认无误，生成视频'}</button>
        <button className="w-btn w-ghost" disabled={busy || rendering} onClick={() => void save()}>
          {busy ? '保存中…' : '只保存字幕'}</button>
      </div>
      {msg && <div className="w-msg">{msg}</div>}
    </div>
  );
}
