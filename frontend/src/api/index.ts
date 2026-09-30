import axios from 'axios';
import type {
  TranscodeRequest,
  TranscodeResult,
  UploadResult,
  TaskRecord,
  HistoryResponse,
  TerminologyListResponse,
  TerminologyInput,
  CacheStats,
  QueueStats,
  LoginResult,
  UserInfo,
  LlmStatus,
  TaskSubtitles,
  SubtitleSegment,
  AsrDeviceInfo,
  VoicesResponse,
  MediaOutput,
  DubResult,
  TranslationSettings,
} from '../types';

const API_BASE_URL = 'http://localhost:8000/api';
const TOKEN_KEY = 'subai_access_token';

// --------------------------------------------------------------------------- //
// 令牌存取（登录页与拦截器共用；后端所有业务接口都需要它）
// --------------------------------------------------------------------------- //

export const getToken = (): string | null => localStorage.getItem(TOKEN_KEY);

export const setToken = (token: string): void => localStorage.setItem(TOKEN_KEY, token);

export const clearToken = (): void => localStorage.removeItem(TOKEN_KEY);

export const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
});

// 附加 Bearer 令牌；未登录时不附加，由后端返回 401
api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 401 统一清理令牌并广播，由 App 切回登录页
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      clearToken();
      window.dispatchEvent(new Event('subai:unauthorized'));
    }
    return Promise.reject(error);
  },
);

// --------------------------------------------------------------------------- //
// 认证
// --------------------------------------------------------------------------- //

export const login = async (username: string, password: string): Promise<LoginResult> => {
  const response = await api.post('/auth/login', { username, password });
  const data = response.data as LoginResult;
  setToken(data.access_token);
  return data;
};

export const register = async (
  username: string,
  password: string,
  email?: string,
): Promise<UserInfo> => {
  const response = await api.post('/auth/register', { username, password, email });
  return response.data.user as UserInfo;
};

export const getCurrentUser = async (): Promise<UserInfo> => {
  const response = await api.get('/auth/me');
  return response.data as UserInfo;
};

export const changePassword = async (oldPassword: string, newPassword: string) => {
  const response = await api.post('/auth/change-password', {
    old_password: oldPassword,
    new_password: newPassword,
  });
  return response.data;
};

export const logout = (): void => clearToken();

// --------------------------------------------------------------------------- //
// 健康检查与任务
// --------------------------------------------------------------------------- //

export const checkHealth = async () => {
  const response = await api.get('/health');
  return response.data;
};

export const submitTranscodeTask = async (requestData: TranscodeRequest): Promise<TranscodeResult> => {
  const response = await api.post('/transcode', requestData);
  return response.data as TranscodeResult;
};

export const uploadVideoFile = async (file: File): Promise<UploadResult> => {
  const formData = new FormData();
  formData.append('file', file);
  const response = await api.post('/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 0, // 大文件上传不设超时
  });
  return response.data as UploadResult;
};

export const getTaskStatus = async (taskId: string): Promise<TaskRecord> => {
  const response = await api.get(`/task/${taskId}`);
  return response.data as TaskRecord;
};

export const cancelTask = async (taskId: string) => {
  const response = await api.delete(`/task/${taskId}`);
  return response.data;
};

// 后端返回 { tasks, total }，不是数组
export const getHistory = async (params?: {
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<HistoryResponse> => {
  const response = await api.get('/history', { params });
  return response.data as HistoryResponse;
};

export const getTerminologyList = async (params?: {
  category?: string;
  priority?: string;
  keyword?: string;
  limit?: number;
}): Promise<TerminologyListResponse> => {
  const response = await api.get('/terminology', { params });
  return response.data as TerminologyListResponse;
};

export const addTerminology = async (term: TerminologyInput) => {
  const response = await api.post('/terminology', term);
  return response.data;
};

export const deleteTerminology = async (source: string) => {
  const response = await api.delete(`/terminology/${encodeURIComponent(source)}`);
  return response.data;
};

export const importTerminology = async (file: File) => {
  const formData = new FormData();
  formData.append('file', file);
  const response = await api.post('/terminology/import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
};

// --------------------------------------------------------------------------- //
// 缓存 / 队列 / 配置（管理员）
// --------------------------------------------------------------------------- //

export const getCacheStats = async (): Promise<CacheStats> => {
  const response = await api.get('/cache/stats');
  return response.data as CacheStats;
};

export const clearCache = async () => {
  const response = await api.post('/cache/clear');
  return response.data;
};

export const getQueueStats = async (): Promise<QueueStats> => {
  const response = await api.get('/queue/stats');
  return response.data as QueueStats;
};

export const reloadConfig = async () => {
  const response = await api.post('/config/reload');
  return response.data;
};

// --------------------------------------------------------------------------- //
// 翻译后端状态与切换
// --------------------------------------------------------------------------- //

export const getLlmStatus = async (): Promise<LlmStatus> => {
  const response = await api.get('/llm/status');
  return response.data as LlmStatus;
};

export const getAsrDevice = async (): Promise<AsrDeviceInfo> => {
  const response = await api.get('/system/asr-device');
  return response.data as AsrDeviceInfo;
};

export const testLlm = async (mode?: string) => {
  const response = await api.post('/llm/test', { mode }, { timeout: 40000 });
  return response.data;
};

export const setLlmMode = async (
  mode: string,
  opts?: { cloud_url?: string; cloud_model?: string; cloud_api_key?: string },
): Promise<LlmStatus> => {
  const response = await api.post('/llm/mode', { mode, ...opts });
  return response.data as LlmStatus;
};

// --------------------------------------------------------------------------- //
// 字幕读取 / 写回
// --------------------------------------------------------------------------- //

export const getTaskSubtitles = async (taskId: string): Promise<TaskSubtitles> => {
  const response = await api.get('/task/' + taskId + '/subtitles');
  return response.data as TaskSubtitles;
};

export const saveTaskSubtitles = async (taskId: string, segments: SubtitleSegment[]) => {
  const response = await api.post('/task/' + taskId + '/subtitles', { segments });
  return response.data;
};

// 用 axios 带令牌下载输出文件（直接 a[href] 不会带 Authorization）
export const downloadOutput = async (filename: string): Promise<void> => {
  const response = await api.get('/output/' + encodeURIComponent(filename), { responseType: 'blob' });
  const url = URL.createObjectURL(response.data as Blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
};

export default api;

// --------------------------------------------------------------------------- //
// 四期：媒体处理（压制 / 封装 / 配音）
// --------------------------------------------------------------------------- //

export const getVoices = async (): Promise<VoicesResponse> => {
  const response = await api.get('/tts/voices');
  return response.data as VoicesResponse;
};

// 压制/封装/配音都是长任务（FFmpeg 重编码、逐段语音合成），
// 用 timeout: 0 关闭 30s 默认超时，否则大视频必然中断。
export const burnHardsub = async (payload: {
  video_path: string;
  subtitle_path: string;
  crf?: number;
  preset?: string;
  font_size?: number;
}): Promise<MediaOutput> => {
  const response = await api.post('/video/burn', payload, { timeout: 0 });
  return response.data as MediaOutput;
};

export const muxSoftsub = async (payload: {
  video_path: string;
  tracks: { path: string; language?: string; title?: string }[];
}): Promise<MediaOutput> => {
  const response = await api.post('/video/mux', payload, { timeout: 0 });
  return response.data as MediaOutput;
};

export const dubSubtitles = async (payload: {
  segments: { start: number; end: number; text: string }[];
  language?: string;
  voice?: string;
  rate?: number;
}): Promise<DubResult> => {
  const response = await api.post('/tts/dub', payload, { timeout: 0 });
  return response.data as DubResult;
};

// --------------------------------------------------------------------------- //
// 翻译设置（术语模式）
// --------------------------------------------------------------------------- //

export const getTranslationSettings = async (): Promise<TranslationSettings> => {
  const response = await api.get('/translation/settings');
  return response.data as TranslationSettings;
};

export const setTermMode = async (mode: string): Promise<{ term_mode: string }> => {
  const response = await api.post('/translation/term-mode', { mode });
  return response.data as { term_mode: string };
};
