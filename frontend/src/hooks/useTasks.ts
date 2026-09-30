import { useCallback, useEffect, useState } from 'react';
import type { StageInfo, TaskInfo } from '../api/tauri';
import { getHistory } from '../api';

type StageState = 'done' | 'active' | 'wait';

// 依据任务状态与进度推导流水线三个阶段（与后端进度回调的 0.3/0.6/0.95 分界一致）
function deriveStages(status: string, progress: number, message: string): StageInfo[] {
  let asr: StageState = 'wait';
  let tr: StageState = 'wait';
  let out: StageState = 'wait';

  if (status === 'pending') {
    // 全部等待
  } else if (status === 'processing' && progress < 0.3) {
    asr = 'active';
  } else if (status === 'processing' && progress < 0.95) {
    asr = 'done';
    tr = 'active';
  } else if (status === 'processing') {
    asr = 'done';
    tr = 'done';
    out = 'active';
  } else if (status === 'completed') {
    asr = 'done';
    tr = 'done';
    out = 'done';
  } else if (status === 'failed') {
    asr = 'done';
  }

  return [
    { name: 'ASR', status: asr, description: message || '语音识别' },
    { name: '翻译', status: tr, description: '翻译字幕' },
    { name: '输出', status: out, description: '生成字幕文件' },
  ];
}

export function useTasks() {
  const [tasks, setTasks] = useState<TaskInfo[]>([]);
  const [loading, setLoading] = useState(true);

  const refreshTasks = useCallback(async () => {
    try {
      const data = await getHistory({ limit: 50 });
      setTasks(
        data.tasks.map((t) => ({
          id: t.task_id,
          name: t.video_path.split(/[\\/]/).pop() || t.task_id,
          status: t.status,
          progress: t.progress,
          stages: deriveStages(t.status, t.progress, t.message),
        })),
      );
    } catch {
      // 后端未启动或未登录：保持既有列表，由页面自行提示
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshTasks();
    const interval = setInterval(() => {
      void refreshTasks();
    }, 5000);
    return () => clearInterval(interval);
  }, [refreshTasks]);

  return { tasks, loading, refreshTasks };
}
