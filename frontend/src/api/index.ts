import axios from 'axios';
import type {
  TranscodeRequest,
  TranscodeResult,
  UploadResult,
  TaskRecord,
  TerminologyRecord,
  CacheStats,
  QueueStats,
} from '../types';

const API_BASE_URL = 'http://localhost:8000/api';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 健康检查
export const checkHealth = async () => {
  const response = await api.get('/health');
  return response.data;
};

// 提交转码任务
export const submitTranscodeTask = async (requestData: TranscodeRequest): Promise<TranscodeResult> => {
  const response = await api.post('/transcode', requestData);
  return response.data as TranscodeResult;
};

// 上传视频文件（multipart/form-data），返回 { filename, video_path, size_bytes }
export const uploadVideoFile = async (file: File): Promise<UploadResult> => {
  const formData = new FormData();
  formData.append('file', file);
  const response = await api.post('/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 0, // 大文件上传不设超时
  });
  return response.data as UploadResult;
};

// 查询任务状态
export const getTaskStatus = async (taskId: string) => {
  const response = await api.get(`/task/${taskId}`);
  return response.data as TaskRecord;
};

// 查询历史记录
export const getHistory = async (params?: { video_name?: string; status?: string; limit?: number }) => {
  const response = await api.get('/history', { params });
  return response.data as TaskRecord[];
};

// 下载输出文件
export const downloadFile = (filename: string) => {
  return `${API_BASE_URL.replace('/api', '')}/output/${filename}`;
};

// 添加术语
export const addTerminology = async (term: Omit<TerminologyRecord, 'id' | 'created_at'>) => {
  const response = await api.post('/terminology', term);
  return response.data;
};

// 查询术语列表
export const getTerminologyList = async (params?: { source_lang?: string; target_lang?: string }) => {
  const response = await api.get('/terminology', { params });
  return response.data as TerminologyRecord[];
};

// 导入术语
export const importTerminology = async (filePath: string) => {
  const formData = new FormData();
  formData.append('file', filePath);
  const response = await api.post('/terminology/import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
};

// 查询缓存统计
export const getCacheStats = async () => {
  const response = await api.get('/cache/stats');
  return response.data as CacheStats;
};

// 清空缓存
export const clearCache = async () => {
  const response = await api.post('/cache/clear');
  return response.data;
};

// 查询队列统计
export const getQueueStats = async () => {
  const response = await api.get('/queue/stats');
  return response.data as QueueStats;
};

// 重载配置
export const reloadConfig = async () => {
  const response = await api.post('/config/reload');
  return response.data;
};

export default api;