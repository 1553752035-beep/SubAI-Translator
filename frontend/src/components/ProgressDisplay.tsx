import React from 'react';
import type { TaskRecord } from '../types';
import styles from '../styles/components.module.css';

interface ProgressDisplayProps {
  task: TaskRecord;
}

const ProgressDisplay: React.FC<ProgressDisplayProps> = ({ task }) => {
  const getStatusIcon = (status: TaskRecord['status']) => {
    switch (status) {
      case 'pending':
        return '⏳';
      case 'processing':
        return '🔄';
      case 'completed':
        return '✅';
      case 'failed':
        return '❌';
      default:
        return '❓';
    }
  };

  const getStatusText = (status: TaskRecord['status']) => {
    switch (status) {
      case 'pending':
        return '等待中';
      case 'processing':
        return '处理中';
      case 'completed':
        return '已完成';
      case 'failed':
        return '失败';
      default:
        return '未知';
    }
  };

  return (
    <div className={styles.progressContainer}>
      <div className={styles.progressHeader}>
        <span className={styles.statusIcon}>{getStatusIcon(task.status)}</span>
        <span className={styles.statusText}>{getStatusText(task.status)}</span>
        <span className={styles.progressPercent}>{Math.round(task.progress * 100)}%</span>
      </div>

      <div className={styles.progressBar}>
        <div
          className={`${styles.progressFill} ${
            task.status === 'failed' ? styles.failed : task.status === 'completed' ? styles.completed : ''
          }`}
          style={{ width: `${task.progress * 100}%` }}
        />
      </div>

      <p className={styles.progressMessage}>{task.message}</p>

      {task.status === 'failed' && task.error_message && (
        <div className={styles.errorMessage}>
          <strong>错误信息：</strong>
          {task.error_message}
        </div>
      )}

      {task.status === 'completed' && task.result_files.length > 0 && (
        <div className={styles.resultFiles}>
          <strong>输出文件：</strong>
          <ul>
            {task.result_files.map((file, index) => (
              <li key={index}>
                <a href={`/api/output/${file}`} target="_blank" rel="noopener noreferrer">
                  📄 {file}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

export default ProgressDisplay;