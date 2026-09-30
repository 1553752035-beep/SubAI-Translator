import { useEffect, useMemo, useState } from 'react';
import {
  burnHardsub,
  downloadOutput,
  dubSubtitles,
  getTaskSubtitles,
  getVoices,
  muxSoftsub,
} from '../api';
import type { TaskRecord, Voice } from '../types';

const SUB_EXTS = ['.srt', '.ass', '.vtt'];

const baseName = (p: string): string => p.split(/[\\/]/).pop() || p;

const errText = (e: any): string => {
  const detail = e?.response?.data?.detail;
  if (typeof detail === 'string' && detail) return detail;
  if (Array.isArray(detail)) return detail.map((d: any) => d?.msg || JSON.stringify(d)).join('；');
  return e?.message || '操作失败';
};

interface Props {
  task: TaskRecord;
}

type Busy = '' | 'burn' | 'mux' | 'dub';

/**
 * 四期媒体工具：硬字幕压制（4.2）/ 软字幕封装（4.2）/ 配音（4.1）。
 * 这三个后端接口此前已实现并有测试，但界面缺失，用户无法使用。
 */
export const MediaTools = ({ task }: Props) => {
  const subs = useMemo(
    () => (task.result_files || []).filter((f) => SUB_EXTS.includes(f.slice(f.lastIndexOf('.')).toLowerCase())),
    [task.result_files],
  );

  const [subPath, setSubPath] = useState('');
  const [crf, setCrf] = useState(18);
  const [fontSize, setFontSize] = useState('');
  const [busy, setBusy] = useState<Busy>('');
  const [error, setError] = useState('');
  const [burnOut, setBurnOut] = useState('');
  const [muxOut, setMuxOut] = useState('');
  const [voices, setVoices] = useState<Voice[]>([]);
  const [voice, setVoice] = useState('');
  const [rate, setRate] = useState(0);
  const [textFrom, setTextFrom] = useState<'translation' | 'source'>('translation');
  const [dub, setDub] = useState<{ filename: string; seconds: number; drift: number; voice: string } | null>(null);

  useEffect(() => {
    setSubPath((prev) => (subs.includes(prev) ? prev : subs[0] ?? ''));
  }, [subs]);

  useEffect(() => {
    let alive = true;
    getVoices()
      .then((r) => {
        if (!alive) return;
        const list = r.voices || [];
        setVoices(list);
        setVoice(list[0]?.name ?? '');
      })
      .catch(() => {
        if (alive) setVoices([]);
      });
    return () => {
      alive = false;
    };
  }, []);

  const run = async (kind: Busy, fn: () => Promise<string>): Promise<string> => {
    setBusy(kind);
    setError('');
    try {
      return await fn();
    } catch (e: any) {
      setError(errText(e));
      return '';
    } finally {
      setBusy('');
    }
  };

  const doBurn = () =>
    run('burn', async () => {
      const r = await burnHardsub({
        video_path: task.video_path,
        subtitle_path: subPath,
        crf,
        ...(fontSize ? { font_size: Number(fontSize) } : {}),
      });
      setBurnOut(r.filename);
      return r.filename;
    });

  const doMux = () =>
    run('mux', async () => {
      const r = await muxSoftsub({
        video_path: task.video_path,
        tracks: subs.map((p) => ({ path: p, title: baseName(p) })),
      });
      setMuxOut(r.filename);
      return r.filename;
    });

  const doDub = () =>
    run('dub', async () => {
      const data = await getTaskSubtitles(task.task_id);
      const segments = (data.segments || [])
        .map((s) => ({
          start: Number(s.start),
          end: Number(s.end),
          text: String(textFrom === 'translation' ? s.translation || s.source : s.source || ''),
        }))
        .filter((s) => s.text.trim() && s.end > s.start);
      if (!segments.length) throw new Error('该任务没有可用于配音的字幕文本');

      const r = await dubSubtitles({
        segments,
        voice: voice || undefined,
        rate,
        language: task.target_lang || undefined,
      });
      setDub({ filename: r.filename, seconds: r.total_seconds, drift: r.max_drift_seconds, voice: r.voice });
      return r.filename;
    });

  const label: React.CSSProperties = { display: 'inline-block', minWidth: '86px', color: 'var(--text-dim)', fontSize: '13px' };
  const block: React.CSSProperties = { marginBottom: '14px', paddingBottom: '12px', borderBottom: '1px dashed var(--border)' };

  if (!subs.length) {
    return (
      <div style={{ color: 'var(--text-dim)', fontSize: '13px' }}>
        该任务没有字幕文件，无法进行压制或配音。
      </div>
    );
  }

  return (
    <div data-testid="media-tools">
      {error && <div style={{ color: '#f44336', fontSize: '13px', marginBottom: '10px' }}>{error}</div>}

      <div style={block}>
        <div style={{ fontWeight: 600, marginBottom: '8px' }}>硬字幕压制</div>
        <div style={{ marginBottom: '8px' }}>
          <span style={label}>字幕文件</span>
          <select aria-label="压制字幕文件" value={subPath} onChange={(e) => setSubPath(e.target.value)}>
            {subs.map((s) => (
              <option key={s} value={s}>{baseName(s)}</option>
            ))}
          </select>
        </div>
        <div style={{ marginBottom: '8px' }}>
          <span style={label}>质量 CRF</span>
          <input aria-label="CRF" type="number" min={0} max={51} value={crf}
                 onChange={(e) => setCrf(Number(e.target.value))} style={{ width: '70px' }} />
          <span style={{ marginLeft: '16px', ...label, minWidth: '40px' }}>字号</span>
          <input aria-label="字号" type="number" min={8} max={200} value={fontSize}
                 onChange={(e) => setFontSize(e.target.value)} placeholder="默认"
                 style={{ width: '80px' }} />
        </div>
        <button className="btn" disabled={busy !== '' || !subPath} onClick={() => void doBurn()}>
          {busy === 'burn' ? '压制中…' : '开始压制'}
        </button>
        {burnOut && (
          <span style={{ marginLeft: '12px', fontSize: '13px' }}>
            已生成 {burnOut}
            <button className="btn" style={{ marginLeft: '8px' }} onClick={() => void downloadOutput(burnOut)}>下载</button>
          </span>
        )}
      </div>

      <div style={block}>
        <div style={{ fontWeight: 600, marginBottom: '8px' }}>软字幕封装（MKV，可开关字幕轨）</div>
        <div style={{ fontSize: '13px', color: 'var(--text-dim)', marginBottom: '8px' }}>
          将封装 {subs.length} 条字幕轨：{subs.map(baseName).join('、')}
        </div>
        <button className="btn" disabled={busy !== ''} onClick={() => void doMux()}>
          {busy === 'mux' ? '封装中…' : '开始封装'}
        </button>
        {muxOut && (
          <span style={{ marginLeft: '12px', fontSize: '13px' }}>
            已生成 {muxOut}
            <button className="btn" style={{ marginLeft: '8px' }} onClick={() => void downloadOutput(muxOut)}>下载</button>
          </span>
        )}
      </div>

      <div>
        <div style={{ fontWeight: 600, marginBottom: '8px' }}>生成配音</div>
        <div style={{ marginBottom: '8px' }}>
          <span style={label}>音色</span>
          {voices.length ? (
            <select aria-label="音色" value={voice} onChange={(e) => setVoice(e.target.value)}>
              {voices.map((v) => (
                <option key={v.name} value={v.name}>{v.name}{v.culture ? ' / ' + v.culture : ''}</option>
              ))}
            </select>
          ) : (
            <span style={{ fontSize: '13px', color: 'var(--text-dim)' }}>未检测到可用音色（系统语音合成不可用）</span>
          )}
        </div>
        <div style={{ marginBottom: '8px' }}>
          <span style={label}>文本来源</span>
          <select aria-label="文本来源" value={textFrom} onChange={(e) => setTextFrom(e.target.value as 'translation' | 'source')}>
            <option value="translation">译文</option>
            <option value="source">原文</option>
          </select>
          <span style={{ marginLeft: '16px', ...label, minWidth: '40px' }}>语速</span>
          <input aria-label="语速" type="number" min={-10} max={10} value={rate}
                 onChange={(e) => setRate(Number(e.target.value))} style={{ width: '70px' }} />
        </div>
        <button className="btn" disabled={busy !== ''} onClick={() => void doDub()}>
          {busy === 'dub' ? '合成中…' : '开始配音'}
        </button>
        {dub && (
          <div style={{ marginTop: '10px', fontSize: '13px' }}>
            已生成 {dub.filename}（音色 {dub.voice || '默认'}，总时长 {dub.seconds}s，最大同步偏差 {dub.drift}s）
            <button className="btn" style={{ marginLeft: '8px' }} onClick={() => void downloadOutput(dub.filename)}>下载</button>
          </div>
        )}
      </div>
    </div>
  );
};
