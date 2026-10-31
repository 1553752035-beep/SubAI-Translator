// 任务状态
export type TaskStatus = 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled' | 'archived';

// 任务模式
export type TaskMode = 'asr' | 'hardsub';

// 输出格式
/**
 * 输出字幕格式。
 * [2026-10-25] 新增 lrc（只有起始时间，点歌词用）与 txt（无时间轴，纯文本分发）。
 * 对齐同类项目 SmartSub 的格式覆盖（其支持 srt/vtt/ass/lrc/txt 五种）。
 */
export type OutputFormat = 'srt' | 'vtt' | 'ass' | 'json' | 'lrc' | 'txt';

/**
 * 硬字幕样式表单。
 *
 * 与后端 src/subtitle_style.py::SubtitleStyle 字段对应，但**全部可选**：
 * 未填的项由后端回落默认值（对齐 ffmpeg 的 SRT 隐式样式，保证观感零回归）。
 * 这样「只改个颜色」的用户不必被迫填一堆字段。
 */
export interface SubtitleStyleForm {
  font_family?: string;
  font_size?: number;
  primary_color?: string;
  outline_color?: string;
  back_color?: string;
  outline?: number;
  shadow?: number;
  /** numpad 对齐：7/8/9 上排，1/2/3 下排，2 = 底部居中 */
  alignment?: number;
  margin_v?: number;
  bold?: boolean;
  italic?: boolean;
  /** 1 = 仅描边，3 = 半透明背景框 */
  border_style?: number;
  back_opacity?: number;
}

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
  /** 任务指标。coverage 为 [2026-10-25] 新增：语音覆盖率与未覆盖区间。 */
  metrics?: TaskMetrics;
}

/** 未覆盖区间（有人说话但没出字幕，或确实静默）。 */
export interface CoverageGap {
  start: number;
  end: number;
  sec: number;
}

/**
 * 语音覆盖率统计。
 *
 * 口径注意：`coverage_pct` 是「字幕覆盖时长 / 音频总时长」，
 * 能反映漏识别，但**不等于** VAD 检出段的保留比例。
 * `gaps` 里的区间既可能是「真没人说话」，也可能是「有人说话但没识别出来」，
 * 现有信息无法区分，所以界面文案必须写「未覆盖」而不是「漏识别」。
 */
export interface CoverageStats {
  duration: number;
  covered: number;
  coverage_pct: number;
  blank: number;
  gaps: CoverageGap[];
  gap_min_sec: number;
  warn: boolean;
}

export interface TaskMetrics {
  lines_total?: number;
  lines_failed?: number;
  terms_hit?: number;
  cache_hits?: number;
  llm_requests?: number;
  files?: number;
  coverage?: CoverageStats;
  /** 说话人分离统计（开启分离且有模型时才有） */
  diarization?: DiarizationStats;
}

/**
 * 说话人分离统计。
 *
 * 注意 speaker_count 与 speakers_in_rows 的差别：
 * - speaker_count  = 模型认为这个视频里有几个人（看分离结果）
 * - speakers_in_rows = 实际上有多少人「分到了字幕行」
 * 某个说话人整段都是背景音时，后者会小于前者 —— 这是正常现象。
 */
export interface DiarizationStats {
  speaker_count: number;
  speakers_in_rows?: number;
  labeled: number;
  unlabeled: number;
  segments: number;
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

// ASR 设备信息（GET /api/system/asr-device）
export interface AsrDeviceInfo {
  configured: string;
  effective_device: 'cuda' | 'cpu';
  compute_type: string;
  ct2_cuda_supported: boolean;
  cuda_dll_dirs: string[];
  free_vram_gb: number | null;
}

// 四期：媒体处理（硬字幕压制 / 软字幕封装 / 配音）
export interface Voice {
  name: string;
  culture: string;
  engine: string;
}

export interface VoicesResponse {
  engine: string;
  voices: Voice[];
}

export interface MediaOutput {
  output_path: string;
  filename: string;
}

export interface DubResult {
  merged: string;
  clips: string[];
  max_drift_seconds: number;
  total_seconds: number;
  voice: string;
  engine: string;
  filename: string;
  /** 合成出来是 0 采样的段落数（>0 表示音色可能不支持字幕语言） */
  silent_clips?: number;
  silent_indices?: number[];
  /** 目标语言是否有匹配音色；false 表示回落到默认音色 */
  voice_matched?: boolean;
}

// 翻译设置（术语模式）
export interface TranslationOption {
  value: string;
  label: string;
  description: string;
}

export interface TranslationSettings {
  term_mode: string;
  available: TranslationOption[];
}

// --------------------------------------------------------------------------- //
// 插件系统（四期 4.3）
// --------------------------------------------------------------------------- //

export interface PluginInfo {
  id: string;
  name: string;
  kind: string;
  version: string;
  description: string;
  author: string;
  builtin: boolean;
  external: boolean;
  enabled: boolean;
  loaded: boolean;
  /** enabled | pending | disabled | error */
  state: string;
  error: string;
  priority?: number;
  capabilities?: string[];
  available?: boolean;
}

export interface PluginStats {
  total: number;
  enabled: number;
  errors: number;
  by_kind: Record<string, { total: number; enabled: number }>;
}

export interface PluginListResponse {
  plugins: PluginInfo[];
  stats: PluginStats;
  kinds: string[];
}

export interface PluginMarketplaceEntry {
  id: string;
  name: string;
  kind: string;
  version: string;
  description: string;
  author: string;
  rating: number | null;
  installed: boolean;
  builtin?: boolean;
}

export interface LanguageStats {
  total: number;
  asr: number;
  translate: number;
  tts: number;
}

export interface LanguageDetectResult {
  code: string;
  confidence: number;
  method: string;
  candidates: { code: string; score: number }[];
}

export interface ApiKeyInfo {
  key_id: string;
  name: string;
  prefix: string;
  scopes: string[];
  enabled: boolean;
  revoked: boolean;
  rate_limit: number | null;
  call_count: number;
  error_count: number;
  success_rate: number;
  last_used_at: number | null;
}

export interface WebhookInfo {
  webhook_id: string;
  url: string;
  events: string[];
  enabled: boolean;
  secret: string;
  created_at: number;
}

export interface DeliveryInfo {
  delivery_id: string;
  webhook_id: string;
  event: string;
  status: string;
  attempts: number;
  status_code: number;
  error: string;
  created_at: number;
}
