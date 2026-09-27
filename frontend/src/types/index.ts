// 任务状态
export type TaskStatus = 'pending' | 'processing' | 'completed' | 'failed';

// 任务模式
export type TaskMode = 'asr' | 'hardsub';

// 输出格式
export type OutputFormat = 'srt' | 'vtt' | 'ass' | 'json';

// 任务记录
export interface TaskRecord {
  task_id: string;
  video_path: string;
  mode: TaskMode;
  source_lang: string | null;
  target_lang: string;
  output_format: OutputFormat;
  status: TaskStatus;
  progress: number;
  message: string;
  result_files: string[];
  created_at: number;
  updated_at: number;
  completed_at: number | null;
  error_message: string | null;
}

// 术语记录
export interface TerminologyRecord {
  id?: number;
  source_text: string;
  target_text: string;
  source_lang: string;
  target_lang: string;
  priority: 'high' | 'medium' | 'low';
  created_at?: number;
}

// 缓存统计
export interface CacheStats {
  total_entries: number;
  hit_rate: number;
  expired_count: number;
}

// 队列统计
export interface QueueStats {
  max_concurrent: number;
  max_queue_size: number;
  queue_size: number;
  running_count: number;
  is_idle: boolean;
}

// 转码请求参数
export interface TranscodeRequest {
  video_path: string;
  mode: TaskMode;
  source_lang?: string;
  target_lang: string;
  output_format: OutputFormat;
  terms_file?: string;
}

// 文件上传结果
export interface UploadResult {
  filename: string;
  video_path: string;
  size_bytes: number;
}

// 转码任务提交结果
export interface TranscodeResult {
  task_id: string;
  status: string;
  message: string;
}