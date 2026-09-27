import { useState, useEffect, useCallback } from 'react';
import { getTaskStatus } from '../api';
import type { TaskRecord } from '../types';

interface UseTaskResult {
  task: TaskRecord | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

/**
 * 任务状态查询 Hook
 * 自动轮询更新任务状态
 */
export const useTask = (taskId: string | null, interval: number = 1000): UseTaskResult => {
  const [task, setTask] = useState<TaskRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!taskId) return;

    try {
      setLoading(true);
      setError(null);
      const data = await getTaskStatus(taskId);
      setTask(data);

      // 如果任务完成或失败，停止轮询
      if (data.status === 'completed' || data.status === 'failed') {
        // 不再自动停止，由组件控制
      }
    } catch (err: any) {
      setError(err.message || '查询任务状态失败');
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    if (!taskId) {
      setTask(null);
      return;
    }

    // 立即查询一次
    refresh();

    // 设置轮询
    const timer = setInterval(refresh, interval);

    return () => {
      clearInterval(timer);
    };
  }, [taskId, interval, refresh]);

  return { task, loading, error, refresh };
};