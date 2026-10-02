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
  PluginInfo,
  PluginListResponse,
  PluginMarketplaceEntry,
  LanguageStats,
  LanguageDetectResult,
  ApiKeyInfo,
  WebhookInfo,
  DeliveryInfo,
} from '../types';

const API_BASE_URL = 'http://localhost:8000/api';
const TOKEN_KEY = 'subai_access_token';

// --------------------------------------------------------------------------- //
// 令牌存取（登录页与拦截器共用；后端所有业务接口都需要它）
// --------------------------------------------------------------------------- //

// 五期：免登录模式 —— 本机令牌（由 Tauri 读取后端生成的 data/local_token.txt）
let _localToken: string | null = null;
let _localTokenResolved = false;

export const ensureLocalToken = async (): Promise<string | null> => {
  if (_localTokenResolved) return _localToken;
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    const token = await invoke<string>('get_local_token');
    _localToken = token || null;
  } catch {
    _localToken = null;   // 非 Tauri 环境（纯浏览器打开）没有本机令牌
  }
  _localTokenResolved = true;
  return _localToken;
};

export const resetLocalToken = (): void => {
  _localToken = null;
  _localTokenResolved = false;
};

export const getLocalToken = (): string | null => _localToken;

export const getToken = (): string | null => localStorage.getItem(TOKEN_KEY);

export const setToken = (token: string): void => localStorage.setItem(TOKEN_KEY, token);

export const clearToken = (): void => localStorage.removeItem(TOKEN_KEY);

export const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
});

// 附加 Bearer 令牌；未登录时不附加，由后端返回 401
api.interceptors.request.use(async (config) => {
  const token = getToken();
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
    return config;
  }
  // 免登录模式：带上本机令牌
  const local = await ensureLocalToken();
  if (local) {
    config.headers = config.headers ?? {};
    config.headers['X-Local-Token'] = local;
  }
  return config;
});

// 401 统一清理令牌并广播，由 App 切回登录页
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      // 只有"账号登录"模式才回登录页；免登录模式不要因为一次 401 就跳走
      if (getToken()) {
        clearToken();
        window.dispatchEvent(new Event('subai:unauthorized'));
      }
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
// --------------------------------------------------------------------------- //
// 插件系统（四期 4.3）
// --------------------------------------------------------------------------- //

export const listPlugins = async (detail = false): Promise<PluginListResponse> => {
  const response = await api.get("/plugins", { params: { detail } });
  return response.data as PluginListResponse;
};

export const setPluginEnabled = async (pluginId: string, enabled: boolean): Promise<PluginInfo> => {
  const action = enabled ? "enable" : "disable";
  const response = await api.post("/plugins/" + pluginId + "/" + action);
  return response.data as PluginInfo;
};

export const reloadPlugins = async (): Promise<{ discovered: number }> => {
  const response = await api.post("/plugins/reload");
  return response.data as { discovered: number };
};

export const probePlugin = async (pluginId: string) => {
  const response = await api.post("/plugins/" + pluginId + "/probe", undefined, { timeout: 40000 });
  return response.data;
};

export const getPluginMarketplace = async (
  query?: string,
  kind?: string,
): Promise<{ entries: PluginMarketplaceEntry[]; note: string }> => {
  const response = await api.get("/plugins/marketplace", { params: { query, kind } });
  return response.data as { entries: PluginMarketplaceEntry[]; note: string };
};

// --------------------------------------------------------------------------- //
// 四期 4.4 / 4.5 / 4.6：语言、开放平台、报表
// --------------------------------------------------------------------------- //

export const getLanguages = async (): Promise<{ languages: any[]; stats: LanguageStats }> => {
  const response = await api.get("/languages");
  return response.data as { languages: any[]; stats: LanguageStats };
};

export const detectLanguage = async (text: string): Promise<LanguageDetectResult> => {
  const response = await api.post("/languages/detect", { text });
  return response.data as LanguageDetectResult;
};

export const getOpenApiStats = async (): Promise<any> => {
  const response = await api.get("/openapi/stats");
  return response.data;
};

export const downloadReport = async (format: string, kind = "summary"): Promise<void> => {
  const response = await api.get("/analytics/export", { params: { format, kind }, responseType: "blob" });
  const url = URL.createObjectURL(response.data as Blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "subai-" + kind + "." + format;
  link.click();
  URL.revokeObjectURL(url);
};

// --------------------------------------------------------------------------- //
// 四期深化：开放平台（密钥 / Webhook 管理）
// --------------------------------------------------------------------------- //

export const getOpenApiKeys = async (): Promise<{ keys: ApiKeyInfo[]; stats: any }> => {
  const response = await api.get("/openapi/keys");
  return response.data;
};

export const createOpenApiKey = async (
  name: string, scopes: string[], rateLimit: number | null,
): Promise<{ secret: string; key: ApiKeyInfo; notice: string }> => {
  const response = await api.post("/openapi/keys", { name, scopes, rate_limit: rateLimit });
  return response.data;
};

export const setKeyEnabled = async (keyId: string, enabled: boolean): Promise<any> => {
  const response = await api.post(`/openapi/keys/${keyId}/${enabled ? "enable" : "disable"}`);
  return response.data;
};

export const revokeOpenApiKey = async (keyId: string): Promise<any> => {
  const response = await api.delete(`/openapi/keys/${keyId}`);
  return response.data;
};

export const setKeyRateLimit = async (keyId: string, rateLimit: number | null): Promise<any> => {
  const response = await api.post(`/openapi/keys/${keyId}/rate-limit`, { rate_limit: rateLimit });
  return response.data;
};

export const getWebhooks = async (): Promise<{ webhooks: WebhookInfo[]; stats: any; events: string[] }> => {
  const response = await api.get("/openapi/webhooks");
  return response.data;
};

export const createWebhook = async (
  url: string, events: string[] | null,
): Promise<{ webhook: WebhookInfo; secret: string; notice: string }> => {
  const response = await api.post("/openapi/webhooks", { url, events });
  return response.data;
};

export const setWebhookEnabled = async (webhookId: string, enabled: boolean): Promise<any> => {
  const response = await api.post(`/openapi/webhooks/${webhookId}/${enabled ? "enable" : "disable"}`);
  return response.data;
};

export const deleteWebhook = async (webhookId: string): Promise<any> => {
  const response = await api.delete(`/openapi/webhooks/${webhookId}`);
  return response.data;
};

export const testWebhook = async (webhookId: string): Promise<any> => {
  const response = await api.post(`/openapi/webhooks/${webhookId}/test`);
  return response.data;
};

export const getWebhookDeliveries = async (webhookId: string): Promise<{ deliveries: DeliveryInfo[] }> => {
  const response = await api.get(`/openapi/webhooks/${webhookId}/deliveries`);
  return response.data;
};

export const retryDelivery = async (deliveryId: string): Promise<any> => {
  const response = await api.post(`/openapi/webhooks/deliveries/${deliveryId}/retry`);
  return response.data;
};
