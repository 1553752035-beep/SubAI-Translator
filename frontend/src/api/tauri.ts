import { invoke } from '@tauri-apps/api/core';

/**
 * 检查后端服务健康状态
 */
export async function checkBackendHealth(): Promise<boolean> {
  try {
    return await invoke('check_backend_health');
  } catch (error) {
    console.error('Backend health check failed:', error);
    return false;
  }
}

/**
 * 启动后端服务
 */
export async function startBackend(): Promise<string> {
  try {
    return await invoke('start_backend');
  } catch (error) {
    console.error('Failed to start backend:', error);
    throw error;
  }
}

/**
 * 停止后端服务
 */
export async function stopBackend(): Promise<string> {
  try {
    return await invoke('stop_backend');
  } catch (error) {
    console.error('Failed to stop backend:', error);
    throw error;
  }
}

/**
 * 获取后端状态
 */
export async function getBackendStatus(): Promise<BackendStatus> {
  try {
    return await invoke('get_backend_status');
  } catch (error) {
    console.error('Failed to get backend status:', error);
    throw error;
  }
}

/**
 * 获取任务列表
 */
export async function getTaskList(): Promise<TaskInfo[]> {
  try {
    return await invoke('get_task_list');
  } catch (error) {
    console.error('Failed to get task list:', error);
    return [];
  }
}

/**
 * 上传视频文件
 */
export async function uploadVideo(filePath: string): Promise<string> {
  try {
    return await invoke('upload_video', { filePath });
  } catch (error) {
    console.error('Failed to upload video:', error);
    throw error;
  }
}

/**
 * 开始翻译任务
 */
export async function startTranslation(taskId: string): Promise<string> {
  try {
    return await invoke('start_translation', { taskId });
  } catch (error) {
    console.error('Failed to start translation:', error);
    throw error;
  }
}

/**
 * 取消翻译任务
 */
export async function cancelTranslation(taskId: string): Promise<string> {
  try {
    return await invoke('cancel_translation', { taskId });
  } catch (error) {
    console.error('Failed to cancel translation:', error);
    throw error;
  }
}

/**
 * 获取任务状态
 */
export async function getTaskStatus(taskId: string): Promise<string> {
  try {
    return await invoke('get_task_status', { taskId });
  } catch (error) {
    console.error('Failed to get task status:', error);
    throw error;
  }
}

/**
 * 获取系统信息（内存、GPU）
 */
export async function getSystemInfo(): Promise<SystemInfo> {
  try {
    return await invoke('get_system_info');
  } catch (error) {
    console.error('Failed to get system info:', error);
    throw error;
  }
}

/**
 * 获取应用配置
 */
export async function getAppConfig(): Promise<Record<string, any>> {
  try {
    return await invoke('get_app_config');
  } catch (error) {
    console.error('Failed to get app config:', error);
    throw error;
  }
}

/**
 * 更新应用配置
 */
export async function updateAppConfig(config: Record<string, any>): Promise<string> {
  try {
    return await invoke('update_app_config', { config });
  } catch (error) {
    console.error('Failed to update app config:', error);
    throw error;
  }
}

/**
 * 获取术语列表
 */
export async function getTerminologyList(): Promise<string> {
  try {
    return await invoke('get_terminology_list');
  } catch (error) {
    console.error('Failed to get terminology list:', error);
    throw error;
  }
}

/**
 * 添加术语
 */
export async function addTerminology(sourceText: string, translation: string, priority: string): Promise<string> {
  try {
    return await invoke('add_terminology', { 
      sourceText, 
      translation, 
      priority 
    });
  } catch (error) {
    console.error('Failed to add terminology:', error);
    throw error;
  }
}

/**
 * 获取帮助信息
 */
export async function getHelpInfo(): Promise<HelpInfo> {
  try {
    return await invoke('get_help_info');
  } catch (error) {
    console.error('Failed to get help info:', error);
    throw error;
  }
}

// 类型定义
export interface StageInfo {
  name: string;
  status: 'done' | 'active' | 'wait';
  description: string;
}

export interface TaskInfo {
  id: string;
  name: string;
  status: string;
  progress: number;
  stages: StageInfo[];
}

export interface BackendStatus {
  running: boolean;
  pid: number | null;
  url: string;
}

export interface SystemInfo {
  memory_used_gb: number;
  memory_total_gb: number;
  gpu_used_gb: number;
  gpu_total_gb: number;
  gpu_utilization: number;
}

export interface HelpInfo {
  version: string;
  features: string[];
  shortcuts: {
    upload: string;
    start: string;
    cancel: string;
  };
}