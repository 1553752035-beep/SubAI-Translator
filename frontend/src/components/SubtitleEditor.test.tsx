import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api', () => ({
  getTaskSubtitles: vi.fn(),
  saveTaskSubtitles: vi.fn(),
  downloadOutput: vi.fn(),
  getHistory: vi.fn(),
}));

import { getHistory, getTaskSubtitles, saveTaskSubtitles } from '../api';
import { SubtitleEditor } from './SubtitleEditor';

const mockGet = vi.mocked(getTaskSubtitles);
const mockSave = vi.mocked(saveTaskSubtitles);
const mockHistory = vi.mocked(getHistory);

const SEGMENTS = {
  task_id: 't1',
  status: 'completed',
  kind: 'bilingual' as const,
  file: 'D:/out/demo.bilingual.srt',
  segments: [
    { index: 1, start: 0, end: 1.5, source: '你好', translation: 'Hello' },
    { index: 2, start: 2, end: 3.25, source: '世界', translation: 'World' },
  ],
};

describe('SubtitleEditor', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockHistory.mockResolvedValue({ tasks: [], total: 0 });
  });

  it('按任务加载真实字幕并渲染每一行', async () => {
    mockGet.mockResolvedValue(SEGMENTS);
    render(<SubtitleEditor taskId="t1" />);
    expect(await screen.findByDisplayValue('你好')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Hello')).toBeInTheDocument();
    expect(screen.getByDisplayValue('世界')).toBeInTheDocument();
    expect(screen.getByText(/共 2 条/)).toBeInTheDocument();
    expect(mockGet).toHaveBeenCalledWith('t1');
  });

  it('编辑后保存会提交修改过的译文', async () => {
    mockGet.mockResolvedValue(SEGMENTS);
    mockSave.mockResolvedValue({ saved: 'x', count: 2, kind: 'bilingual' });
    render(<SubtitleEditor taskId="t1" />);

    const hello = await screen.findByDisplayValue('Hello');
    fireEvent.change(hello, { target: { value: 'Hi there' } });
    expect(screen.getByText(/有未保存修改/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '保存修改' }));
    await waitFor(() => expect(mockSave).toHaveBeenCalledTimes(1));
    const [taskId, segments] = mockSave.mock.calls[0];
    expect(taskId).toBe('t1');
    expect(segments[0].translation).toBe('Hi there');
    expect(await screen.findByText(/已保存/)).toBeInTheDocument();
  });

  it('没有字幕时给出明确空状态（而不是假数据）', async () => {
    mockGet.mockRejectedValue({ response: { status: 404, data: { detail: '该任务还没有可编辑的字幕文件' } } });
    render(<SubtitleEditor taskId="t1" />);
    expect(await screen.findByText(/该任务还没有可编辑的字幕文件/)).toBeInTheDocument();
  });

  it('没有已完成任务时提示上传后才会出现字幕', async () => {
    render(<SubtitleEditor />);
    expect(await screen.findByText(/还没有已完成的任务/)).toBeInTheDocument();
  });
});
