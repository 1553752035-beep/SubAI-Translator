import React from 'react';
import type { TaskRecord } from '../types';
import styles from '../styles/components.module.css';

interface TaskListProps {
  tasks: TaskRecord[];
  loading: boolean;
  onSelectTask: (taskId: string) => void;
}

const TaskList: React.FC<TaskListProps> = ({ tasks, loading, onSelectTask }) => {
  const getStatusBadge = (status: TaskRecord['status']) => {
    const classMap = {
      pending: styles.badgePending,
      processing: styles.badgeProcessing,
      completed: styles.badgeCompleted,
      failed: styles.badgeFailed,
    };
    return <span className={`${styles.badge} ${classMap[status]}`}>{status}</span>;
  };

  if (loading) {
    return <div className={styles.loading}>加载中...</div>;
  }

  if (tasks.length === 0) {
    return <div className={styles.empty}>暂无任务记录</div>;
  }

  return (
    <div className={styles.taskList}>
      <h3>📋 任务历史</h3>
      <div className={styles.taskTable}>
        <table>
          <thead>
            <tr>
              <th>任务ID</th>
              <th>视频名称</th>
              <th>模式</th>
              <th>状态</th>
              <th>进度</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((task) => (
              <tr key={task.task_id}>
                <td className={styles.taskId}>{task.task_id.slice(0, 8)}</td>
                <td>{task.video_path.split('/').pop()}</td>
                <td>{task.mode}</td>
                <td>{getStatusBadge(task.status)}</td>
                <td>{Math.round(task.progress * 100)}%</td>
                <td>{new Date(task.created_at * 1000).toLocaleString()}</td>
                <td>
                  <button
                    className={styles.btnSmall}
                    onClick={() => onSelectTask(task.task_id)}
                  >
                    查看
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default TaskList;