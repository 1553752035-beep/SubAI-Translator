import { useEffect, useRef, useState } from 'react';
import {
  getTaskStatus,
  openInExplorer,
  submitAlignTask,
  submitComposeTask,
  submitTranscodeTask,
  uploadVideoFile,
} from '../api';
import type { Theme } from '../theme';
import '../styles/wizard.css';

type Intent = 'translate' | 'subtitle' | 'script';
type Step = 'pick' | 'intent' | 'options' | 'running' | 'done';
type OutputVideo = 'soft' | 'hard' | 'both';

const IconFilm = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 15V4m0 0L8.5 7.5M12 4l3.5 3.5" />
    <path d="M3.5 14v3.5A2.5 2.5 0 0 0 6 20h12a2.5 2.5 0 0 0 2.5-2.5V14" />
  </svg>
);
const IconGlobe = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <circle cx="12" cy="12" r="8.5" />
    <path d="M3.5 12h17M12 3.5c2.4 2.6 2.4 14.4 0 17M12 3.5c-2.4 2.6-2.4 14.4 0 17" />
  </svg>
);
const IconChat = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round">
    <path d="M20.5 11.5a7.5 7.5 0 0 1-7.5 7.5H9l-4.5 2.5L5.6 17A7.5 7.5 0 1 1 20.5 11.5z" />
  </svg>
);
const IconPen = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round">
    <path d="M4 20h4L20.5 7.5 16.5 3.5 4 16v4z" />
    <path d="M14.5 5.5l4 4" />
  </svg>
);
const IconShield = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
    <path d="M12 3l7 2.8V12c0 4.4-2.9 7.9-7 9-4.1-1.1-7-4.6-7-9V5.8L12 3z" />
    <path d="M9 12.2l2 2 4-4" />
  </svg>
);

const LANGUAGES = ['中文', 'English', '日本語', '한국어', 'Русский', 'Français', 'Deutsch', 'Español'];

export function WizardPage({
  onEditTask,
  theme,
  onToggleTheme,
  onOpenAdvanced,
}: {
  onEditTask: (taskId: string) => void;
  theme: Theme;
  onToggleTheme: () => void;
  onOpenAdvanced: () => void;
}) {
  const [step, setStep] = useState<Step>('pick');
  const [file, setFile] = useState<File | null>(null);
  const [fileName, setFileName] = useState('');
  const [intent, setIntent] = useState<Intent>('translate');
  const [target, setTarget] = useState('中文');
  const [sourceFrom, setSourceFrom] = useState<'asr' | 'hardsub'>('asr');
  const [outputVideo, setOutputVideo] = useState<OutputVideo>('soft');
  const [subtitleMode, setSubtitleMode] = useState<'asr' | 'file'>('asr');
  const [subtitleFile, setSubtitleFile] = useState<File | null>(null);
  const [script, setScript] = useState('兄弟们这波看我操作\n别急，等他先动\n就是现在，压枪\n三杀，直接带走');
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [outputs, setOutputs] = useState<string[]>([]);
  const [taskId, setTaskId] = useState('');
  const [dragging, setDragging] = useState(false);
  const pollRef = useRef<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const taskRef = useRef('');

  useEffect(() => () => {
    if (pollRef.current) window.clearInterval(pollRef.current);
  }, []);

  const stopPoll = () => {
    if (pollRef.current) window.clearInterval(pollRef.current);
    pollRef.current = null;
  };

  const poll = () => {
    stopPoll();
    pollRef.current = window.setInterval(async () => {
      try {
        const t = await getTaskStatus(taskRef.current);
        setProgress(Math.round((t.progress || 0) * 100));
        setMessage(t.message || '处理中…');
        if (t.status === 'completed') {
          stopPoll();
          setOutputs(t.result_files || []);
          setStep('done');
        } else if (t.status === 'failed' || t.status === 'cancelled') {
          stopPoll();
          setError(t.error_message || '任务失败');
          setStep('options');
        }
      } catch {
        /* 单次轮询失败先忽略，下一轮再试 */
      }
    }, 1500);
  };

  const start = async () => {
    if (!file) {
      setError('请先选择视频');
      return;
    }
    setError('');
    setStep('running');
    setProgress(2);
    setMessage('正在上传视频…');
    try {
      let newTaskId = '';
      if (intent === 'script') {
        const r = await submitAlignTask(file, script, outputVideo);
        newTaskId = r.task_id;
      } else if (intent === 'subtitle' && subtitleMode === 'file') {
        if (!subtitleFile) throw new Error('请选择字幕文件');
        const r = await submitComposeTask(file, subtitleFile, outputVideo);
        newTaskId = r.task_id;
      } else {
        const up = await uploadVideoFile(file);
        const payload: any = {
          video_path: up.video_path,
          mode: intent === 'translate' ? sourceFrom : 'asr',
          target_lang: intent === 'translate' ? target : 'none',
          output_format: 'srt',
          output_video: outputVideo,
          defer_render: true,   // 五期：两段式——先出字幕草稿，确认后再出片
        };
        const r = await submitTranscodeTask(payload);
        newTaskId = r.task_id;
      }
      setTaskId(newTaskId);
      taskRef.current = newTaskId;
      setMessage('处理中…');
      poll();
    } catch (e: any) {
      setError(String(e?.response?.data?.detail || e?.message || '启动失败'));
      setStep('options');
    }
  };

  const pickFile = (f: File | null) => {
    if (!f) return;
    setFile(f);
    setFileName(f.name);
    setError('');
    setStep('intent');
  };

  const openFolder = async () => {
    const first = outputs[0];
    if (!first) return;
    try {
      await openInExplorer(first);
    } catch (e: any) {
      setError('打不开文件夹：' + String(e?.message || e));
    }
  };

  const reset = () => {
    stopPoll();
    setStep('pick');
    setFile(null);
    setFileName('');
    setOutputs([]);
    setError('');
    setProgress(0);
    setMessage('');
  };

  return (
    <div className="w-app">
      <div className="w-wrap">
        <div className="w-top">
          <div className="w-brand">SubAI <i>Translator</i></div>
          <div style={{ display: 'flex', gap: 9 }}>
            <button className="w-btn w-ghost" onClick={onToggleTheme}>
              {theme === 'light' ? '切换到深色' : '切换到浅色'}
            </button>
            <button className="w-btn w-ghost" onClick={onOpenAdvanced}>高级 ›</button>
          </div>
        </div>

        {step === 'pick' && (
          <div>
            <h1 className="w-h1">给视频加字幕</h1>
            <div
              className={'w-drop' + (dragging ? ' on' : '')}
              role="button"
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                pickFile(e.dataTransfer?.files?.[0] ?? null);
              }}
            >
              <IconFilm />
              <div className="t">把视频拖进来，或点击选择</div>
              <div className="d">支持 mp4 · mkv · mov · avi · flv · webm</div>
              <div className="w-promise"><IconShield /><span>原视频不会被改动，成品另存为新文件</span></div>
              <input
                ref={fileInputRef}
                type="file"
                accept="video/*"
                style={{ display: 'none' }}
                onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
              />
            </div>
          </div>
        )}

        {step === 'intent' && (
          <div>
            <button className="w-back" onClick={() => setStep('pick')}>← 换个视频</button>
            <h2 className="w-h2" style={{ marginTop: 10 }}>这个视频，你想怎么处理？</h2>
            <div className="w-sub">{fileName}　·　选一个就行，后面还能改</div>
            <div className="w-cards">
              <div className="w-card" onClick={() => { setIntent('translate'); setStep('options'); }}>
                <IconGlobe /><div className="t">翻译</div>
                <div className="d">识别说话或画面字幕，翻成别的语言，直接出成品</div>
              </div>
              <div className="w-card" onClick={() => { setIntent('subtitle'); setStep('options'); }}>
                <IconChat /><div className="t">只加字幕，不翻译</div>
                <div className="d">自动识别原文；或用我已有的字幕文件</div>
              </div>
              <div className="w-card" onClick={() => { setIntent('script'); setStep('options'); }}>
                <IconPen /><div className="t">我有文字稿</div>
                <div className="d">把台词粘进去，自动对齐时间轴</div>
              </div>
            </div>
          </div>
        )}

        {step === 'options' && (
          <div>
            <button className="w-back" onClick={() => setStep('intent')}>← 返回</button>
            <h2 className="w-h2" style={{ marginTop: 10 }}>
              {intent === 'translate' ? '翻译设置' : intent === 'subtitle' ? '只加字幕（不翻译）' : '我有文字稿'}
            </h2>
            <div className="w-sub">{fileName}</div>

            <div className="w-panel">
              {intent === 'translate' && (
                <>
                  <div className="w-row">
                    <div><div className="k">翻译成</div><div className="h">识别语言自动判断</div></div>
                    <select className="w-select" value={target} onChange={(e) => setTarget(e.target.value)}>
                      {LANGUAGES.map((l) => <option key={l} value={l}>{l}</option>)}
                    </select>
                  </div>
                  <div className="w-row">
                    <div><div className="k">识别来源</div><div className="h">说话声，还是画面里的字幕</div></div>
                    <div className="w-chips">
                      <span className={'w-chip' + (sourceFrom === 'asr' ? ' on' : '')} onClick={() => setSourceFrom('asr')}>说话声</span>
                      <span className={'w-chip' + (sourceFrom === 'hardsub' ? ' on' : '')} onClick={() => setSourceFrom('hardsub')}>画面字幕 OCR</span>
                    </div>
                  </div>
                </>
              )}

              {intent === 'subtitle' && (
                <div className="w-row">
                  <div><div className="k">字幕从哪来</div><div className="h">没有字幕文件就自动识别</div></div>
                  <div className="w-chips">
                    <span className={'w-chip' + (subtitleMode === 'asr' ? ' on' : '')} onClick={() => setSubtitleMode('asr')}>自动识别说话声</span>
                    <span className={'w-chip' + (subtitleMode === 'file' ? ' on' : '')} onClick={() => setSubtitleMode('file')}>我已有字幕文件</span>
                  </div>
                </div>
              )}

              {intent === 'script' && (
                <div style={{ padding: '16px 0' }}>
                  <div className="k" style={{ marginBottom: 8 }}>把台词粘进来（一行一句，自动对时间轴）</div>
                  <textarea className="w-area" value={script} onChange={(e) => setScript(e.target.value)} />
                </div>
              )}

              <div className="w-row">
                <div><div className="k">成品形式</div><div className="h">软字幕最快；要发手机看就选硬字幕</div></div>
                <div className="w-chips">
                  <span className={'w-chip' + (outputVideo === 'soft' ? ' on' : '')} onClick={() => setOutputVideo('soft')}>软字幕 MKV</span>
                  <span className={'w-chip' + (outputVideo === 'hard' ? ' on' : '')} onClick={() => setOutputVideo('hard')}>硬字幕（烧进画面）</span>
                  <span className={'w-chip' + (outputVideo === 'both' ? ' on' : '')} onClick={() => setOutputVideo('both')}>两个都要</span>
                </div>
              </div>
            </div>

            {intent === 'subtitle' && subtitleMode === 'file' && (
              <div style={{ marginTop: 14 }}>
                <input
                  type="file"
                  accept=".srt,.vtt,.ass,.ssa"
                  onChange={(e) => setSubtitleFile(e.target.files?.[0] ?? null)}
                />
                {subtitleFile && <span style={{ marginLeft: 10, color: 'var(--w-dim)' }}>{subtitleFile.name}</span>}
              </div>
            )}

            {error && <div className="w-err">{error}</div>}
            <div className="w-center">
              <button className="w-btn w-primary" onClick={() => void start()}>开始</button>
            </div>
          </div>
        )}

        {step === 'running' && (
          <div>
            <h2 className="w-h2">正在处理…</h2>
            <div className="w-sub">{fileName}</div>
            <div className="w-panel" style={{ padding: 22, textAlign: 'center' }}>
              <div className="w-bar"><i style={{ width: progress + '%' }} /></div>
              <div className="w-sub" style={{ margin: 0 }}>{message || '准备中…'}</div>
              <button className="w-btn w-ghost" style={{ marginTop: 18 }} onClick={reset}>取消</button>
            </div>
          </div>
        )}

        {step === 'done' && (
          <div>
            <h2 className="w-h2" style={{ textAlign: 'center' }}>好了！</h2>
            <div className="w-sub" style={{ textAlign: 'center' }}>原视频没动过，成品是另一个文件。</div>
            {message && <div className="w-sub" style={{ textAlign: 'center' }}>{message}</div>}
            <div className="w-out">
              {outputs.length === 0 && '（没有生成成品文件）'}
              {outputs.map((p) => <div key={p}>{p.split(/[\\/]/).pop()}</div>)}
            </div>
            <div className="w-actions">
              <button className="w-btn w-primary" onClick={() => void openFolder()}>打开文件夹</button>
              <button className="w-btn w-ghost" onClick={() => {
                onEditTask(taskId);
                setTimeout(() => document.getElementById('sub-editor')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 120);
              }}>改字幕</button>
              <button className="w-btn w-ghost" onClick={reset}>再做一个</button>
            </div>
            {error && <div className="w-err">{error}</div>}
          </div>
        )}
      </div>
    </div>
  );
}
