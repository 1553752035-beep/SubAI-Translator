import { useEffect, useMemo, useState } from 'react';
import {
  burnHardsub,
  downloadOutput,
  dubSubtitles,
  getTaskSubtitles,
  getVoices,
  muxSoftsub,
  getEmbeddableFonts,
} from '../api';
import type { SubtitleStyleForm, TaskRecord, Voice } from '../types';

const SUB_EXTS = ['.srt', '.ass', '.vtt', '.lrc'];

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
  // [2026-10-25] 完整字幕样式（颜色/描边/阴影/位置/背景框）。
  // 与后端 SubtitleStyle 字段一一对应；空字符串表示「用后端默认值」。
  const [style, setStyle] = useState<SubtitleStyleForm>({});
  const [showStyle, setShowStyle] = useState(false);
  // [2026-10-25] 字体内嵌：ASS 只记录字体名，播放端没装就掉默认字体。
  // 存成字体族名，由后端解析成实际文件路径。
  const [embedFont, setEmbedFont] = useState('');
  const [fontChoices, setFontChoices] = useState<{ family: string; path: string; size: number }[]>([]);
  const [busy, setBusy] = useState<Busy>('');
  const [error, setError] = useState('');
  const [burnOut, setBurnOut] = useState('');
  const [muxOut, setMuxOut] = useState('');
  const [voices, setVoices] = useState<Voice[]>([]);
  const [voice, setVoice] = useState('');
  const [rate, setRate] = useState(0);
  const [textFrom, setTextFrom] = useState<'translation' | 'source'>('translation');
  const [dub, setDub] = useState<{
    filename: string;
    seconds: number;
    drift: number;
    voice: string;
    silent: number;
    matched: boolean;
  } | null>(null);

  useEffect(() => {
    setSubPath((prev) => (subs.includes(prev) ? prev : subs[0] ?? ''));
  }, [subs]);

  // 可内嵌字体：只在封装面板展开时拉一次，失败就静默留空（不影响封装主流程）
  useEffect(() => {
    let alive = true;
    getEmbeddableFonts()
      .then((r) => {
        if (alive) setFontChoices(r.available || []);
      })
      .catch(() => {
        if (alive) setFontChoices([]);
      });
    return () => {
      alive = false;
    };
  }, []);

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
        ...(Object.keys(style).length ? { style } : {}),
      });
      setBurnOut(r.filename);
      return r.filename;
    });

  const doMux = () =>
    run('mux', async () => {
      const r = await muxSoftsub({
        video_path: task.video_path,
        tracks: subs.map((p) => ({ path: p, title: baseName(p) })),
        // 只有勾了「内嵌字体」才传，否则请求体与改动前完全一致
        ...(embedFont ? { embed_fonts: [embedFont] } : {}),
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
      setDub({
        filename: r.filename,
        seconds: r.total_seconds,
        drift: r.max_drift_seconds,
        voice: r.voice,
        silent: r.silent_clips ?? 0,
        matched: r.voice_matched !== false,
      });
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
        <details
          open={showStyle}
          onToggle={(e) => setShowStyle((e.target as HTMLDetailsElement).open)}
          style={{ marginBottom: '8px', fontSize: '13px' }}
        >
          <summary style={{ cursor: 'pointer', color: 'var(--text-dim)' }}>
            字幕样式（颜色 / 描边 / 阴影 / 位置）
          </summary>
          <div style={{ marginTop: '8px', display: 'grid', gap: '8px', gridTemplateColumns: '1fr 1fr' }}>
            <div>
              <span style={{ ...label, minWidth: '60px' }}>字体</span>
              <input aria-label="样式字体" value={style.font_family ?? ''} placeholder="Microsoft YaHei"
                     onChange={(e) => setStyle({ ...style, font_family: e.target.value })}
                     style={{ width: '100%' }} />
            </div>
            <div>
              <span style={{ ...label, minWidth: '60px' }}>字号</span>
              <input aria-label="样式字号" type="number" min={8} max={200}
                     value={style.font_size ?? ''} placeholder="20"
                     onChange={(e) => setStyle({ ...style, font_size: e.target.value === '' ? undefined : Number(e.target.value) })}
                     style={{ width: '100%' }} />
            </div>
            <div>
              <span style={{ ...label, minWidth: '60px' }}>文字色</span>
              <input aria-label="文字颜色" type="color" value={style.primary_color ?? '#FFFFFF'}
                     onChange={(e) => setStyle({ ...style, primary_color: e.target.value })}
                     style={{ width: '100%', height: '28px' }} />
            </div>
            <div>
              <span style={{ ...label, minWidth: '60px' }}>描边色</span>
              <input aria-label="描边颜色" type="color" value={style.outline_color ?? '#000000'}
                     onChange={(e) => setStyle({ ...style, outline_color: e.target.value })}
                     style={{ width: '100%', height: '28px' }} />
            </div>
            <div>
              <span style={{ ...label, minWidth: '60px' }}>描边宽</span>
              <input aria-label="描边宽度" type="number" min={0} max={10} step={0.5}
                     value={style.outline ?? ''} placeholder="2"
                     onChange={(e) => setStyle({ ...style, outline: e.target.value === '' ? undefined : Number(e.target.value) })}
                     style={{ width: '100%' }} />
            </div>
            <div>
              <span style={{ ...label, minWidth: '60px' }}>阴影</span>
              <input aria-label="阴影" type="number" min={0} max={10} step={0.5}
                     value={style.shadow ?? ''} placeholder="0"
                     onChange={(e) => setStyle({ ...style, shadow: e.target.value === '' ? undefined : Number(e.target.value) })}
                     style={{ width: '100%' }} />
            </div>
            <div>
              <span style={{ ...label, minWidth: '60px' }}>位置</span>
              <select aria-label="字幕位置" value={style.alignment ?? 2}
                      onChange={(e) => setStyle({ ...style, alignment: Number(e.target.value) })}
                      style={{ width: '100%' }}>
                <option value={7}>顶部左</option>
                <option value={8}>顶部中</option>
                <option value={9}>顶部右</option>
                <option value={1}>底部左</option>
                <option value={2}>底部中</option>
                <option value={3}>底部右</option>
              </select>
            </div>
            <div>
              <span style={{ ...label, minWidth: '60px' }}>背景框</span>
              <select aria-label="背景框" value={style.border_style ?? 1}
                      onChange={(e) => setStyle({ ...style, border_style: Number(e.target.value) })}
                      style={{ width: '100%' }}>
                <option value={1}>仅描边</option>
                <option value={3}>半透明背景框</option>
              </select>
            </div>
            {style.border_style === 3 && (
              <div>
                <span style={{ ...label, minWidth: '60px' }}>不透明度</span>
                <input aria-label="背景不透明度" type="number" min={0} max={100}
                       value={style.back_opacity ?? 50}
                       onChange={(e) => setStyle({ ...style, back_opacity: Number(e.target.value) })}
                       style={{ width: '100%' }} />
              </div>
            )}
          </div>
        </details>
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
        {fontChoices.length > 0 && (
          <div style={{ marginBottom: '8px' }}>
            <span style={{ marginRight: '8px', fontSize: '13px' }}>内嵌字体</span>
            <select
              className="auth-input"
              style={{ display: 'inline-block', width: 'auto', minWidth: '190px' }}
              aria-label="内嵌字体"
              value={embedFont}
              onChange={(e) => setEmbedFont(e.target.value)}
            >
              <option value="">不内嵌</option>
              {fontChoices.map((f) => (
                <option key={f.family} value={f.family}>{f.family}</option>
              ))}
            </select>
            <div style={{ fontSize: '12px', color: 'var(--text-dim)', marginTop: '4px' }}>
              把字体打进 MKV。ASS 只记录字体名，对方没装就会掉成默认字体或方框。
            </div>
          </div>
        )}
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
        {dub && dub.silent > 0 && (
          <div style={{ marginTop: '6px', fontSize: '13px', color: '#ff9800' }}>
            ⚠️ 有 {dub.silent} 段没有合成出声音——通常是所选音色不支持字幕语言。请换一个音色后重试。
          </div>
        )}
        {dub && dub.silent === 0 && !dub.matched && (
          <div style={{ marginTop: '6px', fontSize: '13px', color: '#ff9800' }}>
            ⚠️ 未找到与目标语言（{task.target_lang}）匹配的音色，已回落到默认音色，可能出现静音。
          </div>
        )}
      </div>
    </div>
  );
};
