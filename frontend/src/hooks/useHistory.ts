import { useState, useEffect } from 'react';
import { getHistory } from '../api';
import type { TaskRecord } from '../types';

interface UseHistoryResult {
  tasks: TaskRecord[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

/**
 * 历史记录查询 Hook
 */
export const useHistory = (): UseHistoryResult => {
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getHistory({ limit: 50 });
      setTasks(data);
    } catch (err: any) {
      setError(err.message || '查询历史记录失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  return { tasks, loading, error, refresh };
};