import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../hooks/useTasks', () => ({ useTasks: vi.fn() }));
vi.mock('../hooks/useTask', () => ({ useTask: vi.fn() }));

import { useTask } from '../hooks/useTask';
import { useTasks } from '../hooks/useTasks';
import { TaskProgress } from './TaskProgress';

const mockUseTasks = vi.mocked(useTasks);
const mockUseTask = vi.mocked(useTask);

const emptyTasks = { tasks: [], loading: false, refreshTasks: vi.fn() };

describe('TaskProgress', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseTask.mockReturnValue({ task: null, loading: false, error: null, refresh: vi.fn() });
  });

  it('没有任务时显示真实空状态，而不是演示数据', () => {
    mockUseTasks.mockReturnValue(emptyTasks);
    render(<TaskProgress />);
    expect(screen.getByText('暂无进行中的任务')).toBeInTheDocument();
    expect(screen.queryByText(/产品发布会/)).toBeNull();
  });

  it('有进行中任务时显示名称与百分比', () => {
    mockUseTasks.mockReturnValue({
      tasks: [{
        id: 'a', name: 'demo.mp4', status: 'processing', progress: 0.42,
        stages: [{ name: 'ASR', status: 'done', description: '识别完成' }],
      }],
      loading: false,
      refreshTasks: vi.fn(),
    });
    render(<TaskProgress />);
    expect(screen.getByText('demo.mp4')).toBeInTheDocument();
    expect(screen.getByText('42%')).toBeInTheDocument();
    expect(screen.getByText('处理中')).toBeInTheDocument();
  });

  it('指定 taskId 时使用该任务的真实状态与错误', () => {
    mockUseTask.mockReturnValue({
      task: {
        task_id: 'x', video_path: 'D:/v/abc.mp4', mode: 'asr', source_lang: null,
        target_lang: 'en', output_format: 'srt', status: 'failed', progress: 1,
        message: '翻译全部失败', result_files: [], created_at: '', updated_at: '',
        completed_at: '', error_message: '翻译后端不可用',
      },
      loading: false, error: null, refresh: vi.fn(),
    });
    render(<TaskProgress taskId="x" />);
    expect(screen.getByText('abc.mp4')).toBeInTheDocument();
    expect(screen.getByText('失败')).toBeInTheDocument();
    expect(screen.getByText('翻译后端不可用')).toBeInTheDocument();
  });
});
