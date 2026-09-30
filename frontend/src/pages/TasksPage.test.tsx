import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api', () => ({
  getHistory: vi.fn(),
  cancelTask: vi.fn(),
}));

import { cancelTask, getHistory } from '../api';
import { TasksPage } from './TasksPage';

const mockHistory = vi.mocked(getHistory);
const mockCancel = vi.mocked(cancelTask);

const task = (over: Record<string, unknown> = {}) => ({
  task_id: 't1',
  video_path: 'D:/v/demo.mp4',
  mode: 'asr' as const,
  source_lang: null,
  target_lang: 'en',
  output_format: 'srt' as const,
  status: 'processing' as const,
  progress: 0.5,
  message: '翻译中',
  result_files: [] as string[],
  created_at: '2026-10-01T00:00:00',
  updated_at: '2026-10-01T00:00:01',
  completed_at: null,
  error_message: null,
  ...over,
});

describe('TasksPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('渲染真实任务列表与状态标签', async () => {
    mockHistory.mockResolvedValue({
      tasks: [task({ task_id: 'a', status: 'processing' }), task({ task_id: 'b', status: 'completed' })],
      total: 2,
    });
    render(<TasksPage />);
    // 状态文案同时出现在筛选下拉的 <option> 里，故用 getAllByText
    expect((await screen.findAllByText('处理中')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('已完成').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/demo\.mp4/).length).toBeGreaterThan(0);
  });

  it('处理中的任务提供取消入口并调用接口', async () => {
    mockHistory.mockResolvedValue({ tasks: [task({ task_id: 'a', status: 'processing' })], total: 1 });
    mockCancel.mockResolvedValue({});
    render(<TasksPage />);
    const cancel = await screen.findByRole('button', { name: '取消' });
    fireEvent.click(cancel);
    await waitFor(() => expect(mockCancel).toHaveBeenCalledWith('a'));
  });

  it('已完成任务不显示取消按钮', async () => {
    mockHistory.mockResolvedValue({ tasks: [task({ task_id: 'b', status: 'completed' })], total: 1 });
    render(<TasksPage />);
    await screen.findByText('已完成');
    expect(screen.queryByRole('button', { name: '取消' })).toBeNull();
  });

  it('空列表给出空状态', async () => {
    mockHistory.mockResolvedValue({ tasks: [], total: 0 });
    render(<TasksPage />);
    await waitFor(() => expect(screen.queryByText(/demo\.mp4/)).toBeNull());
  });
});
