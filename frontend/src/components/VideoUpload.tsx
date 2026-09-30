import { useRef, useState } from 'react';
import { submitTranscodeTask, uploadVideoFile } from '../api/index';
import type { OutputFormat, TaskMode } from '../types';

interface VideoUploadProps {
  onTaskSubmitted?: (taskId: string, filePath: string) => void;
  llmReady?: boolean;
  llmHint?: string;
}

const TARGET_LANGS = [
  { v: 'en', label: '英语' },
  { v: 'zh', label: '中文' },
  { v: 'ja', label: '日语' },
  { v: 'ko', label: '韩语' },
  { v: 'fr', label: '法语' },
  { v: 'de', label: '德语' },
  { v: 'es', label: '西班牙语' },
];

export function VideoUpload({ onTaskSubmitted, llmReady = true, llmHint = '' }: VideoUploadProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState('');
  const [mode, setMode] = useState<TaskMode>('asr');
  const [target, setTarget] = useState('en');
  const [format, setFormat] = useState<OutputFormat>('srt');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const validateFile = (file: File): string | null => {
    const allowedExts = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.ts'];
    const ext = '.' + (file.name.split('.').pop() ?? '').toLowerCase();
    const maxSize = 2 * 1024 * 1024 * 1024;
    if (!allowedExts.includes(ext)) return '不支持的文件格式，请选择 MP4、MKV、AVI 等视频文件';
    if (file.size > maxSize) return '文件大小超过限制（2GB）';
    return null;
  };

  const handleFileSelect = async (file: File) => {
    const bad = validateFile(file);
    if (bad) { setStatus(bad); return; }
    if (!llmReady) {
      setStatus('翻译后端不可用：' + llmHint + '。请先在“设置”里启用本地模型或配置云端 API Key，再提交任务。');
      return;
    }

    setUploading(true);
    setStatus('正在上传 ' + file.name + ' …');
    try {
      const uploadResult = await uploadVideoFile(file);
      setStatus('正在提交任务…');
      const task = await submitTranscodeTask({
        video_path: uploadResult.video_path,
        mode,
        target_lang: target,
        output_format: format,
      });
      onTaskSubmitted?.(task.task_id, uploadResult.video_path);
      setStatus('任务已提交：' + task.task_id);
    } catch (err: any) {
      const detail = err && err.response ? err.response.data.detail : null;
      setStatus('提交失败：' + (typeof detail === 'string' ? detail : (err?.message || '请确认后端已启动')));
    } finally {
      setUploading(false);
    }
  };

  const pick = async (files: FileList | null) => {
    if (!files) return;
    for (const file of Array.from(files)) {
      await handleFileSelect(file);
    }
  };

  return (
    <div className="upload-card">
      <div
        className={'dropzone' + (isDragging ? ' dragging' : '')}
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={(e) => { e.preventDefault(); setIsDragging(false); }}
        onDrop={(e) => { e.preventDefault(); setIsDragging(false); void pick(e.dataTransfer.files); }}
        onClick={() => fileInputRef.current?.click()}
      >
        <div className="dz-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <path d="M17 8l-5-5-5 5" />
            <path d="M12 3v12" />
          </svg>
        </div>
        <div className="dz-text">
          <div className="t">
            拖拽视频到此处，或 <em>{uploading ? '上传中…' : '点击选择文件'}</em>
          </div>
          <div className="d">支持 mp4 / mkv / avi / mov / webm 等，单文件 ≤ 2GB，可批量</div>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept="video/*,.mkv,.avi,.mov,.wmv,.flv,.webm,.m4v,.ts"
          multiple
          style={{ display: 'none' }}
          onChange={(e) => { void pick(e.target.files); e.target.value = ''; }}
        />
      </div>

      <div className="upload-params">
        <label className="field">
          <span>识别模式</span>
          <select value={mode} onChange={(e) => setMode(e.target.value as TaskMode)}>
            <option value="asr">语音识别 (ASR)</option>
            <option value="hardsub">硬字幕 OCR</option>
          </select>
        </label>
        <label className="field">
          <span>目标语言</span>
          <select value={target} onChange={(e) => setTarget(e.target.value)}>
            {TARGET_LANGS.map((l) => <option key={l.v} value={l.v}>{l.label}</option>)}
          </select>
        </label>
        <label className="field">
          <span>输出格式</span>
          <select value={format} onChange={(e) => setFormat(e.target.value as OutputFormat)}>
            <option value="srt">SRT</option>
            <option value="vtt">VTT</option>
            <option value="ass">ASS</option>
            <option value="json">JSON</option>
          </select>
        </label>
      </div>

      {status && <div className={llmReady ? 'upload-status' : 'upload-status error'}>{status}</div>}
    </div>
  );
}
