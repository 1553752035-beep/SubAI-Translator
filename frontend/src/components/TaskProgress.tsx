import { useTask } from '../hooks/useTask';
import { useTasks } from '../hooks/useTasks';

interface TaskProgressProps {
  taskId?: string | null;
}

const SEP = String.fromCharCode(92);
const baseName = (p: string) => {
  const i = Math.max(p.lastIndexOf('/'), p.lastIndexOf(SEP));
  return i >= 0 ? p.slice(i + 1) : p;
};

interface View {
  name: string;
  status: string;
  progress: number;
  message: string;
  error?: string | null;
  stages?: { name: string; status: string; description: string }[];
}

const STATUS_LABEL: Record<string, string> = {
  pending: '等待中',
  processing: '处理中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  archived: '已归档',
};

function Card({ view }: { view: View }) {
  const running = view.status === 'processing' || view.status === 'pending';
  return (
    <div className="task-card">
      <div className="task-head">
        <div className="name">{view.name}</div>
        <span className={'badge ' + (running ? 'running' : '')}>
          {STATUS_LABEL[view.status] || view.status}
        </span>
        <div className="pct">{Math.round(view.progress * 100)}%</div>
      </div>
      {view.stages && view.stages.length > 0 && (
        <div className="stages">
          {view.stages.map((s, i) => (
            <div className={'stage ' + s.status} key={i}>
              <div className="s-name">
                <span className="dot" />
                {s.name}
              </div>
              <div className="s-sub">{s.description}</div>
            </div>
          ))}
        </div>
      )}
      <div className="bar">
        <i style={{ width: Math.round(view.progress * 100) + '%' }} />
      </div>
      {view.message && <div className="task-msg">{view.message}</div>}
      {view.error && <div className="task-err">{view.error}</div>}
    </div>
  );
}

function Empty() {
  return (
    <div className="task-card task-empty">
      <div className="task-head">
        <div className="name" style={{ color: 'var(--text-dim)' }}>暂无进行中的任务</div>
      </div>
      <div className="task-empty-sub">上传视频后，这里会显示真实的处理阶段与进度。</div>
    </div>
  );
}

export function TaskProgress({ taskId }: TaskProgressProps) {
  const { task, loading } = useTask(taskId ?? null, 1500);
  const { tasks } = useTasks();

  if (taskId) {
    if (loading && !task) {
      return (
        <div className="task-card">
          <div className="task-head">
            <div className="name" style={{ color: 'var(--text-dim)' }}>加载中…</div>
          </div>
        </div>
      );
    }
    if (!task) return <Empty />;
    return (
      <Card
        view={{
          name: baseName(task.video_path),
          status: task.status,
          progress: task.progress,
          message: task.message,
          error: task.error_message,
        }}
      />
    );
  }

  const active = tasks.find((t) => t.status === 'processing' || t.status === 'pending') || tasks[0];
  if (!active) return <Empty />;
  return <Card view={{ name: active.name, status: active.status, progress: active.progress, message: '', stages: active.stages }} />;
}
