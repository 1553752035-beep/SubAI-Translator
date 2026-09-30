import { useCallback, useEffect, useState } from 'react';
import { downloadOutput, getHistory, getTaskSubtitles, saveTaskSubtitles } from '../api';
import type { SubtitleSegment } from '../types';

interface SubtitleEditorProps {
  taskId?: string | null;
}

const SEP = String.fromCharCode(92);
const baseName = (p: string) => {
  const i = Math.max(p.lastIndexOf('/'), p.lastIndexOf(SEP));
  return i >= 0 ? p.slice(i + 1) : p;
};

const MAX_ROWS = 500;

function p2(n: number) { return n < 10 ? '0' + n : '' + n; }
function p3(n: number) { return n < 10 ? '00' + n : n < 100 ? '0' + n : '' + n; }

function fmtTs(sec: number): string {
  const ms = Math.max(0, Math.round(sec * 1000));
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  return p2(h) + ':' + p2(m) + ':' + p2(s) + ',' + p3(ms % 1000);
}

export function SubtitleEditor({ taskId }: SubtitleEditorProps) {
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(taskId ?? null);
  const [segments, setSegments] = useState<SubtitleSegment[]>([]);
  const [file, setFile] = useState<string | null>(null);
  const [kind, setKind] = useState('');
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState('');
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (taskId) {
      setCurrentTaskId(taskId);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const data = await getHistory({ status: 'completed', limit: 1 });
        if (!cancelled) setCurrentTaskId(data.tasks[0] ? data.tasks[0].task_id : null);
      } catch {
        if (!cancelled) setCurrentTaskId(null);
      }
    })();
    return () => { cancelled = true; };
  }, [taskId]);

  const load = useCallback(async () => {
    if (!currentTaskId) {
      setSegments([]);
      setFile(null);
      setKind('');
      return;
    }
    setLoading(true);
    setMsg('');
    try {
      const data = await getTaskSubtitles(currentTaskId);
      setSegments(data.segments);
      setFile(data.file);
      setKind(data.kind);
      setDirty(false);
    } catch (err: any) {
      setSegments([]);
      setFile(null);
      setKind('');
      const detail = err && err.response ? err.response.data.detail : null;
      setMsg(typeof detail === 'string' ? detail : '读取字幕失败');
    } finally {
      setLoading(false);
    }
  }, [currentTaskId]);

  useEffect(() => { void load(); }, [load]);

  const update = (index: number, field: 'source' | 'translation', value: string) => {
    setSegments((prev) => prev.map((s, i) => (i === index ? { ...s, [field]: value } : s)));
    setDirty(true);
  };

  const save = async () => {
    if (!currentTaskId) return;
    setMsg('保存中…');
    try {
      const r = await saveTaskSubtitles(currentTaskId, segments);
      setDirty(false);
      setMsg('已保存（' + String(r.kind).toUpperCase() + '，' + r.count + ' 条）');
    } catch (err: any) {
      const detail = err && err.response ? err.response.data.detail : null;
      setMsg(typeof detail === 'string' ? detail : '保存失败');
    }
  };

  const exportFile = async () => {
    if (!file) return;
    try {
      await downloadOutput(baseName(file));
    } catch {
      setMsg('导出失败');
    }
  };

  const rows = segments.slice(0, MAX_ROWS);

  return (
    <div className="table-card">
      <div className="table-head">
        <div className="t">字幕编辑器</div>
        <div className="cnt">
          {loading
            ? '加载中…'
            : segments.length > 0
              ? '共 ' + segments.length + ' 条 · ' + (kind ? kind.toUpperCase() : '') + ' · ' + (dirty ? '有未保存修改' : '已同步')
              : '暂无字幕'}
        </div>
        <div className="actions">
          <button className="btn" onClick={() => void load()} disabled={!currentTaskId || loading}>刷新</button>
          <button className="btn" onClick={() => void exportFile()} disabled={!file}>导出文件</button>
          <button className="btn primary" onClick={() => void save()} disabled={!dirty}>保存修改</button>
        </div>
      </div>

      {msg && <div className="subtitle-msg">{msg}</div>}

      {segments.length === 0 ? (
        <div className="subtitle-empty">
          {currentTaskId
            ? '该任务暂无可编辑的字幕文件（可能仍在处理中，或未输出字幕）。'
            : '还没有已完成的任务。上传视频并完成翻译后，这里会显示真实字幕内容。'}
        </div>
      ) : (
        <table>
          <thead>
            <tr>
              <th style={{ width: '52px' }}>#</th>
              <th style={{ width: '105px' }}>开始</th>
              <th style={{ width: '105px' }}>结束</th>
              <th>原文</th>
              <th>译文</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s, i) => (
              <tr key={i}>
                <td className="idx">{s.index ?? i + 1}</td>
                <td className="time">{fmtTs(s.start)}</td>
                <td className="time">{fmtTs(s.end)}</td>
                <td className="src">
                  <input className="cell-input" value={s.source} onChange={(e) => update(i, 'source', e.target.value)} />
                </td>
                <td className="tgt">
                  <input className="cell-input" value={s.translation} onChange={(e) => update(i, 'translation', e.target.value)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {segments.length > MAX_ROWS && (
        <div className="subtitle-note">仅显示前 {MAX_ROWS} 条，共 {segments.length} 条；保存会写回全部。</div>
      )}
    </div>
  );
}
