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
  SubtitleStyleForm,
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

const API_BASE_URL = 'http://127.0.0.1:8000/api';   // 五期：用 127.0.0.1 而非 localhost，避开 IPv6/系统代理导致的 Network Error
const TOKEN_KEY = 'subai_access_token';

// --------------------------------------------------------------------------- //
// 令牌存取（登录页与拦截器共用；后端所有业务接口都需要它）
// --------------------------------------------------------------------------- //

// 五期：免登录模式 —— 本机令牌（由 Tauri 读取后端生成的 data/local_token.txt）
let _localToken: string | null = null;
let _localTokenResolved = false;
let _localTokenError = '';

export const ensureLocalToken = async (force = false): Promise<string | null> => {
  if (_localTokenResolved && !force) return _localToken;

  // 通道 1（主）：Rust 侧在启动后把令牌注入网页（window.__SUBAI_LOCAL_TOKEN__）
  const injected = (window as any).__SUBAI_LOCAL_TOKEN__;
  if (injected) {
    _localToken = String(injected);
    _localTokenResolved = true;
    _localTokenError = "";
    return _localToken;
  }

  // 通道 2（兜底）：Tauri 命令；带 3 秒超时，绝不让界面被挂住
  try {
    const invokePromise = (async () => {
      const { invoke } = await import('@tauri-apps/api/core');
      return await invoke<string>('get_local_token');
    })();
    const timeout = new Promise<string>((_, reject) =>
      setTimeout(() => reject(new Error('取令牌超时（3 秒）')), 3000));
    const token = await Promise.race([invokePromise, timeout]);
    _localToken = token || null;
    if (_localToken) _localTokenResolved = true;
  } catch (e: any) {
    _localToken = null;
    _localTokenError = String(e?.message || e || '未知错误');
  }
  return _localToken;
};

export const getLocalTokenError = (): string => _localTokenError;

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

/** 五期「我有文字稿」：上传视频 + 稿子，自动对齐时间轴 */
export const submitAlignTask = async (
  file: File, script: string, outputVideo: string, sourceLang?: string,
): Promise<{ task_id: string; status: string; lines: number }> => {
  const form = new FormData();
  form.append('file', file);
  form.append('script', script);
  form.append('output_video', outputVideo);
  if (sourceLang) form.append('source_lang', sourceLang);
  const response = await api.post('/align', form);
  return response.data;
};

/**
 * 「我已有字幕文件」：不识别；targetLang 非 none 时先翻译已有字幕，再出片。
 *
 * [P1 2026-10-24] 加 targetLang。后端 _run_compose_task 早就支持翻译已有字幕，
 * 但路由一直硬编码 target_lang="none"，所以界面只能「直接套用」——想翻译就得
 * 回头重跑一遍识别。等价于 CLI 的 --translate-only。
 */
export const submitComposeTask = async (
  file: File, subtitle: File, outputVideo: string, targetLang: string = 'none',
): Promise<{ task_id: string; status: string }> => {
  const form = new FormData();
  form.append('file', file);
  form.append('subtitle', subtitle);
  form.append('output_video', outputVideo);
  form.append('target_lang', targetLang);
  // 翻译要跑 LLM，30s 默认超时不够
  const response = await api.post('/compose', form, { timeout: 0 });
  return response.data;
};

/** 五期：用系统浏览器打开链接（Tauri 里 a[target=_blank] 不会跳转） */
export const openExternal = async (url: string): Promise<void> => {
  const { invoke } = await import('@tauri-apps/api/core');
  await invoke('open_external', { url });
};

/** 五期：在资源管理器里定位成品文件 */
export const openInExplorer = async (path: string): Promise<void> => {
  const { invoke } = await import('@tauri-apps/api/core');
  await invoke('open_in_explorer', { path });
};

/** 五期：云端翻译服务商预设（含"去哪里拿 Key"的链接） */
export const getLlmProviders = async (): Promise<{ providers: any[] }> => {
  const response = await api.get('/llm/providers');
  return response.data;
};

/**
 * 批量核验服务商端点是否真实可用。
 *
 * 预填的 base_url 只是「猜这个地址应该对」，不等于今天还能用 ——
 * 地址会变、模型会下线、服务会停服（实测 yi 返回 HTTP 410 已停服）。
 * 传 api_key 时能额外判断「这个 Key 能不能用」，不传只探端点是否活着。
 */
export const probeLlmProviders = async (
  api_key?: string,
): Promise<{ results: any[]; summary: any }> => {
  const response = await api.post('/llm/provider-probe', { api_key: api_key || '' });
  return response.data;
};

/** 读取上次核验结果（纯读盘，不重新探测，秒回）。 */
export const getLlmProviderHealth = async (): Promise<{ results: any[] }> => {
  const response = await api.get('/llm/provider-health');
  return response.data;
};

/** 五期：两段式第二段——用户确认字幕后，再生成成品视频 */
export const renderTaskVideo = async (taskId: string): Promise<{ task_id: string; files: string[] }> => {
  const response = await api.post('/task/' + encodeURIComponent(taskId) + '/render');
  return response.data;
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
/** 五期：删除任务（后端已有 DELETE /api/task/{id}） */
/** 五期：批量删除——一次请求，服务端循环；id 在 body 里，不受路径编码影响 */
/** 五期：批量彻底移除（回收站用），一次请求，body 传 ids */
// 五期 P2：专有名词词表（按名字复用）
// 五期：可选增强识别模型（turbo）
/**
 * 字幕质量开关（幻觉丢弃 / 单行最长显示时长）。
 *
 * [P2 2026-10-24] 只读：这两个值在 pipeline 导入时就进了模块常量，
 * 运行时改不了。界面上要明确告诉用户「改 .env 后重启生效」。
 */
export const getSubtitleQuality = async (): Promise<{
  drop_hallucination: boolean;
  hallucination_nsp: number;
  hallucination_cr: number;
  max_subtitle_sec: number;
  /** [2026-10-25] 最短显示时长护栏（秒，0=关闭） */
  min_display_sec: number;
  asr_device: string;
  need_restart_to_apply: boolean;
}> => (await api.get('/system/subtitle-quality')).data;

/** [2026-10-25] ASR 引擎与 sherpa 模型就绪状态（只读）。 */
export const getAsrEngine = async (): Promise<{
  engine: string;
  denoise: boolean;
  sensevoice_itn: boolean;
  sensevoice_language: string;
  vad_threshold: number;
  vad_min_silence_ms: number;
  vad_min_speech_ms: number;
  need_restart_to_apply: boolean;
  sherpa_installed: boolean;
  models: {
    sensevoice: boolean;
    paraformer: boolean;
    /** Qwen3-ASR：多语言（日/粤/中英混说），936MB，速度慢 */
    qwen3: boolean;
    /** FireRed-ASR：中英 + 方言，739MB */
    firered: boolean;
    vad: boolean;
    denoise: boolean;
  };
  models_dir: string;
  models_error?: string;
  /** 说话人分离状态（2026-10-25 新增） */
  diarize?: boolean;
  diarize_speakers?: number;
  diarize_threshold?: number;
  diarize_models?: { segmentation: boolean; embedding: boolean };
  diarize_dir?: string;
  diarize_error?: string;
}> => (await api.get('/system/asr-engine')).data;

/**
 * 取音频波形峰值（校对台画图用）。
 *
 * 后端只返回按像素桶归并的 min/max，不返回原始采样。
 * 1000 桶约 2000 个数字，足够画满一屏。
 */
export const getWaveform = async (params: {
  path: string;
  buckets?: number;
  start?: number;
  end?: number;
}): Promise<{
  buckets: number;
  duration: number;
  peaks: [number, number][];
  sample_rate: number;
  silence_ratio: number;
}> => (await api.get('/video/waveform', { params, timeout: 120000 })).data;

export const getAsrModelStatus = async (): Promise<any> =>
  (await api.get('/asr/model/status')).data;

export const downloadAsrModel = async (): Promise<any> =>
  (await api.post('/asr/model/download')).data;

export const cancelAsrModel = async (): Promise<any> =>
  (await api.post('/asr/model/cancel')).data;

export const listGlossary = async (): Promise<{ series: any[] }> =>
  (await api.get('/glossary')).data;

export const saveGlossarySeries = async (name: string, terms: any[]): Promise<any> =>
  (await api.post('/glossary', { name, terms })).data;

export const purgeTasks = async (ids: string[]): Promise<{ ok: number; failed: { task_id: string; error: string }[] }> => {
  const r = await api.post('/tasks/purge', { ids });
  return (r.data || { ok: 0, failed: [] }) as { ok: number; failed: { task_id: string; error: string }[] };
};

export const deleteTasks = async (ids: string[]): Promise<{ ok: number; failed: { task_id: string; error: string }[] }> => {
  const r = await api.post('/tasks/delete', { ids });
  return (r.data || { ok: 0, failed: [] }) as { ok: number; failed: { task_id: string; error: string }[] };
};

export const deleteTask = async (taskId: string): Promise<void> => {
  await api.delete('/task', { params: { task_id: taskId } });   // 五期：走 query，避开路径特殊字符
};


/** 五期：从回收站彻底移除任务记录（后端不动磁盘文件） */
export const purgeTask = async (taskId: string): Promise<void> => {
  await api.post('/tasks/purge', { ids: [taskId] });
};
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
  font_name?: string;
  font_size?: number;
  /**
   * 完整字幕样式（颜色/描边/阴影/位置/背景框）。
   * 不传时后端沿用 font_name + font_size 的旧行为，观感零变化。
   */
  style?: SubtitleStyleForm;
}): Promise<MediaOutput> => {
  const response = await api.post('/video/burn', payload, { timeout: 0 });
  return response.data as MediaOutput;
};

export const muxSoftsub = async (payload: {
  video_path: string;
  tracks: { path: string; language?: string; title?: string }[];
  /** [2026-10-25] 要内嵌进 MKV 的字体族名（仅 MKV 生效），不传则行为不变 */
  embed_fonts?: string[];
}): Promise<MediaOutput & { fonts_embedded?: number; fonts_missing?: string[] }> => {
  const response = await api.post('/video/mux', payload, { timeout: 0 });
  return response.data as MediaOutput & { fonts_embedded?: number; fonts_missing?: string[] };
};

/** 可内嵌的字体族列表（只列出能真正找到文件的） */
export const getEmbeddableFonts = async (): Promise<{
  available: { family: string; path: string; size: number }[];
  font_dirs: string[];
}> => {
  const response = await api.get('/system/fonts');
  return response.data;
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
