import { useState, useRef, useCallback } from 'react';
import { uploadVideoFile, submitTranscodeTask } from '../api/index';

interface VideoUploadProps {
  onUploadComplete?: (filePath: string) => void;
}

export function VideoUpload({ onUploadComplete }: VideoUploadProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const validateFile = (file: File): boolean => {
    // 按扩展名校验（部分浏览器对 MKV 等格式返回空 MIME type，扩展名更可靠）
    const allowedExts = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.ts'];
    const ext = '.' + (file.name.split('.').pop() ?? '').toLowerCase();
    const maxSize = 2 * 1024 * 1024 * 1024; // 2GB

    if (!allowedExts.includes(ext)) {
      alert('不支持的文件格式，请选择 MP4、MKV、AVI 等视频文件');
      return false;
    }

    if (file.size > maxSize) {
      alert('文件大小超过限制（2GB）');
      return false;
    }

    return true;
  };

  const handleFileSelect = async (file: File) => {
    if (!validateFile(file)) return;

    setUploading(true);

    try {
      // 1. 将文件字节上传到后端（multipart），拿到保存后的绝对路径
      const uploadResult = await uploadVideoFile(file);

      // 2. 提交转码/翻译任务
      const task = await submitTranscodeTask({
        video_path: uploadResult.video_path,
        mode: 'asr',
        target_lang: 'en',
        output_format: 'srt',
      });

      onUploadComplete?.(uploadResult.video_path);
      alert(`上传成功，任务已提交 (ID: ${task.task_id})`);
    } catch (error) {
      console.error('上传失败:', error);
      alert('上传失败，请确认后端服务已启动');
    } finally {
      setUploading(false);
    }
  };

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);

    const files = Array.from(e.dataTransfer.files);
    for (const file of files) {
      await handleFileSelect(file);
    }
  }, [onUploadComplete]);

  const handleClick = () => {
    fileInputRef.current?.click();
  };

  const handleInputChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files) {
      for (const file of Array.from(files)) {
        await handleFileSelect(file);
      }
    }
  };

  return (
    <div
      className={`dropzone ${isDragging ? 'dragging' : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onClick={handleClick}
      style={{
        borderColor: isDragging ? 'var(--accent)' : 'var(--border)',
        background: isDragging ? 'var(--accent-soft)' : 'var(--panel)',
      }}
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
          拖拽视频到此处，或 <em>{uploading ? '上传中...' : '点击选择文件'}</em>
        </div>
        <div className="d">
          识别模式：语音识别 (ASR) · 中 → 英 · 输出：SRT / VTT / ASS
        </div>
      </div>
      <div className="dz-meta">
        <span className="tag">支持格式：MP4, MKV, AVI, MOV, WMV, FLV, WEBM</span>
        <span className="tag">最大 2GB</span>
        <br />
        批量上传：支持拖入多个文件
      </div>
      <input
        ref={fileInputRef}
        type="file"
        accept="video/*,.mkv,.avi,.mov,.wmv,.flv,.webm,.m4v,.ts"
        multiple
        style={{ display: 'none' }}
        onChange={handleInputChange}
      />
    </div>
  );
}