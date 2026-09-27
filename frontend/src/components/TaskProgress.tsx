import { useTasks } from '../hooks/useTasks';
import type { TaskInfo } from '../api/tauri';

interface TaskProgressProps {
  task?: TaskInfo;
}

/**
 * 任务进度卡片
 *
 * 数据来源：useTasks() → 通过 Tauri 命令 get_task_list 拉取后端真实任务
 * 不再使用任何 mock 兜底——若后端未启动或拉不到任务，则显示空状态提示。
 */
export function TaskProgress({ task }: TaskProgressProps) {
  const { tasks, loading } = useTasks();
  const activeTask =
    task ||
    tasks.find((t) => t.status === 'processing' || t.status === 'running') ||
    tasks[0];

  if (loading) {
    return (
      <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-dim)' }}>
        加载中…
      </div>
    );
  }

  if (!activeTask) {
    return (
      <div className="task-card empty">
        <div className="task-head">
          <div className="name" style={{ color: 'var(--text-dim)' }}>
            暂无任务
          </div>
        </div>
        <div className="stages">
          <div className="stage wait">
            <div className="s-name">
              <span className="dot"></span>
              等待上传
            </div>
            <div className="s-sub">
              上传一个视频文件以开始翻译。后端服务可通过主页右上角「启动后端」按钮拉起。
            </div>
          </div>
        </div>
      </div>
    );
  }

  const isRunning = activeTask.status === 'processing' || activeTask.status === 'running';

  return (
    <div className="task-card">
      <div className="task-head">
        <div className="name">{activeTask.name}</div>
        <span className={`badge ${isRunning ? 'running' : ''}`}>
          {isRunning ? '● 处理中' : activeTask.status}
        </span>
        <div className="pct">{Math.round(activeTask.progress)}%</div>
      </div>

      <div className="stages">
        {activeTask.stages.map((stage, index) => (
          <div className={`stage ${stage.status}`} key={index}>
            <div className="s-name">
              <span className="dot"></span>
              {stage.name}
            </div>
            <div className="s-sub">{stage.description}</div>
          </div>
        ))}
      </div>

      <div className="bar">
        <i style={{ width: `${activeTask.progress}%` }}></i>
      </div>
    </div>
  );
}