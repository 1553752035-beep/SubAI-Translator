import { invoke } from '@tauri-apps/api/core';

// 五期：后端是 206MB 单文件程序，首次启动要十几秒。
// 之前每次健康检查失败都会再调一次 start_backend，而 Rust 侧会先杀掉旧进程再起新的，
// 结果后端永远来不及就绪（日志里就是"刚 spawn 就被 kill"）。这里加冷却期，杜绝自相残杀。
let __lastStartBackend = 0;
const __START_COOLDOWN_MS = 60000;

/**
 * 与 Tauri(Rust) 侧的通信层。
 *
 * 只保留 UI 现在真正用到的能力：进程管理、系统信息、帮助信息。
 * 业务数据一律走带认证的 axios 层（src/api/index.ts），
 * 避免出现"绕过后端鉴权、且与其他调用点重复"的包装。
 */

/** 检查内置后端是否已就绪 */
export async function checkBackendHealth(): Promise<boolean> {
  try {
    return await invoke('check_backend_health');
  } catch (error) {
    console.error('Backend health check failed:', error);
    return false;
  }
}

/** 启动内置后端（sidecar），返回启动结果描述 */
export async function startBackend(): Promise<string> {
  const __now = Date.now();
  if (__now - __lastStartBackend < __START_COOLDOWN_MS) {
    throw new Error('后端正在启动中，请稍候（已跳过重复启动）');
  }
  __lastStartBackend = __now;
  try {
    return await invoke('start_backend');
  } catch (error) {
    console.error('Failed to start backend:', error);
    throw error;
  }
}

/** 读取系统内存 / GPU 占用（无 Tauri 环境时会失败，由调用方兜底） */
export async function getSystemInfo(): Promise<SystemInfo> {
  try {
    return await invoke('get_system_info');
  } catch (error) {
    console.error('Failed to get system info:', error);
    throw error;
  }
}

/** 读取帮助信息（静态） */
export async function getHelpInfo(): Promise<HelpInfo> {
  try {
    return await invoke('get_help_info');
  } catch (error) {
    console.error('Failed to get help info:', error);
    throw error;
  }
}

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
