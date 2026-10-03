import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api', () => ({
  getTaskStatus: vi.fn(),
  getTaskSubtitles: vi.fn(),
  saveTaskSubtitles: vi.fn(),
  renderTaskVideo: vi.fn(),
}));

import { getTaskStatus, getTaskSubtitles, saveTaskSubtitles } from '../api';
import { SimpleSubtitleEditor } from './SimpleSubtitleEditor';

const asMock = (f: unknown) => f as { mockResolvedValue: (v: unknown) => void };

// 五期：确认页把同一句文字渲染在两处（播放器叠字 .w-cap + 列表行）
// 因此列表断言必须限定在 .w-conflist 区域内，否则 getAllByText 会命中两处。
const listOf = () => within(document.querySelector('.w-conflist') as HTMLElement);

beforeEach(() => {
  vi.resetAllMocks();
  asMock(getTaskStatus).mockResolvedValue({});
  asMock(saveTaskSubtitles).mockResolvedValue(undefined);
  asMock(getTaskSubtitles).mockResolvedValue({
    task_id: 't1',
    status: 'completed',
    kind: 'mono',
    file: 'demo.source.srt',
    segments: [
      { start: 0, end: 2, source: '原文一', translation: '译文一' },
      { start: 2, end: 4, source: '原文二', translation: '' },
    ],
  });
});

describe('SimpleSubtitleEditor', () => {
  it('列出字幕文字（没有译文时显示原文）', async () => {
    render(<SimpleSubtitleEditor taskId="t1" />);
    await waitFor(() => expect(document.querySelectorAll('.w-subrow').length).toBe(2));
    const list = listOf();
    expect(list.getByText('译文一')).toBeInTheDocument();
    expect(list.getByText('原文二')).toBeInTheDocument();
    expect(list.getByText(/00:00 → 00:02/)).toBeInTheDocument();
  });

  it('改文字后能保存', async () => {
    render(<SimpleSubtitleEditor taskId="t1" />);
    await waitFor(() => expect(document.querySelectorAll('.w-subrow').length).toBe(2));
    // 五期：编辑入口是双击行内文字（单击只切换当前行）
    fireEvent.doubleClick(listOf().getByText('译文一'));
    const input = await screen.findByDisplayValue('译文一');
    fireEvent.change(input, { target: { value: '改过的译文' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    fireEvent.click(screen.getByRole('button', { name: '保存草稿' }));
    await waitFor(() => expect(vi.mocked(saveTaskSubtitles)).toHaveBeenCalled());
    const call = vi.mocked(saveTaskSubtitles).mock.calls[0] as unknown as [string, { translation: string }[]];
    expect(call[1][0].translation).toBe('改过的译文');
  });
});