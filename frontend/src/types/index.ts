// 任务状态
export type TaskStatus = 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled' | 'archived';

// 任务模式
export type TaskMode = 'asr' | 'hardsub';

// 输出格式
export type OutputFormat = 'srt' | 'vtt' | 'ass' | 'json';

// 任务记录（created_at / updated_at / completed_at 为后端返回的 ISO 字符串）
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
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  error_message: string | null;
  user_id?: string | null;
}

// GET /api/history 响应
export interface HistoryResponse {
  tasks: TaskRecord[];
  total: number;
}

// 术语记录（后端契约：source / translation / priority / category / usage_count）
export interface TerminologyRecord {
  source: string;
  translation: string;
  priority: 'high' | 'medium' | 'low';
  category: string;
  usage_count?: number;
  created_at?: string;
  user_id?: string | null;
}

// POST /api/terminology 请求体
export interface TerminologyInput {
  source_text: string;
  translation: string;
  priority?: 'high' | 'medium' | 'low';
  category?: string;
}

// GET /api/terminology 响应
export interface TerminologyListResponse {
  terms: TerminologyRecord[];
  total: number;
}

// 当前登录用户
export interface UserInfo {
  user_id: string;
  username: string;
  role: string;
  email: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

// POST /api/auth/login 响应
export interface LoginResult {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: UserInfo;
}

// GET /api/cache/stats 响应
export interface CacheStats {
  total_entries: number;
  max_entries: number;
  ttl_days: number;
  hit_rate: number;
  size_mb: number;
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
  priority?: 'high' | 'medium' | 'low';
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

// 翻译后端状态（GET /api/llm/status）
export interface LlmStatus {
  mode: string;
  modes: string[];
  effective: { url: string; model: string; has_key: boolean };
  local: { url: string; model: string; reachable: boolean; detail: string };
  cloud: {
    url: string;
    model: string;
    configured: boolean;
    has_key: boolean;
    reachable: boolean | null;
  };
}

// 单条字幕（在线编辑）
export interface SubtitleSegment {
  index?: number;
  start: number;
  end: number;
  source: string;
  translation: string;
}

// 任务字幕（GET /api/task/{id}/subtitles）
export interface TaskSubtitles {
  task_id: string;
  status: string;
  kind: 'json' | 'bilingual' | 'mono';
  file: string;
  segments: SubtitleSegment[];
}
