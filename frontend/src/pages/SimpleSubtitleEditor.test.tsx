import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api', () => ({
  getTaskSubtitles: vi.fn(),
  saveTaskSubtitles: vi.fn(),
}));

import { getTaskSubtitles, saveTaskSubtitles } from '../api';
import { SimpleSubtitleEditor } from './SimpleSubtitleEditor';

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getTaskSubtitles).mockResolvedValue({
    task_id: 't1',
    status: 'completed',
    kind: 'mono',
    file: 'demo.source.srt',
    segments: [
      { start: 0, end: 2, source: '原文一', translation: '译文一' } as any,
      { start: 2, end: 4, source: '原文二', translation: '' } as any,
    ],
  });
  vi.mocked(saveTaskSubtitles).mockResolvedValue(undefined as any);
});

describe('SimpleSubtitleEditor', () => {
  it('列出字幕文字（没有译文时显示原文）', async () => {
    render(<SimpleSubtitleEditor taskId="t1" />);
    expect(await screen.findByText('译文一')).toBeInTheDocument();
    expect(screen.getByText('原文二')).toBeInTheDocument();
    expect(screen.getByText('00:00 → 00:02')).toBeInTheDocument();
  });

  it('改文字后能保存', async () => {
    render(<SimpleSubtitleEditor taskId="t1" />);
    fireEvent.click(await screen.findByText('译文一'));
    const input = screen.getByDisplayValue('译文一');
    fireEvent.change(input, { target: { value: '改过的译文' } });
    fireEvent.click(screen.getByRole('button', { name: '保存字幕' }));
    await waitFor(() => expect(vi.mocked(saveTaskSubtitles)).toHaveBeenCalled());
    const [, segments] = vi.mocked(saveTaskSubtitles).mock.calls[0];
    expect(segments[0].translation).toBe('改过的译文');
  });

  it('读取失败时给出提示而不是白屏', async () => {
    vi.mocked(getTaskSubtitles).mockRejectedValue(new Error('boom'));
    render(<SimpleSubtitleEditor taskId="t1" />);
    expect(await screen.findByText(/读取字幕失败/)).toBeInTheDocument();
  });
});
