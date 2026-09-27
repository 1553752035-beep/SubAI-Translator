import { useState, useEffect } from 'react';
import { getTaskList, type TaskInfo } from '../api/tauri';

export function useTasks() {
  const [tasks, setTasks] = useState<TaskInfo[]>([]);
  const [loading, setLoading] = useState(true);

  const refreshTasks = async () => {
    const taskList = await getTaskList();
    setTasks(taskList);
    setLoading(false);
  };

  useEffect(() => {
    refreshTasks();
    // 每 5 秒刷新一次任务状态
    const interval = setInterval(refreshTasks, 5000);
    return () => clearInterval(interval);
  }, []);

  return { tasks, loading, refreshTasks };
}