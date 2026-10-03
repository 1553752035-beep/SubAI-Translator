import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
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
const rows = () => Array.from(document.querySelectorAll('.w-subrow'));
const listOf = () => within(document.querySelector('.w-conflist') as HTMLElement);
const rowText = (i: number) => (rows()[i]?.textContent || "").replace("▶", "").trim();   // 只比较数据，▶ 是 UI 光标标记

beforeEach(() => {
  vi.resetAllMocks();
  asMock(getTaskStatus).mockResolvedValue({});
  asMock(saveTaskSubtitles).mockResolvedValue(undefined);
  asMock(getTaskSubtitles).mockResolvedValue({
    task_id: 't1', status: 'completed', kind: 'mono', file: 'a.srt',
    segments: [
      { start: 0, end: 2, source: 'AA', translation: 'AA', words: [0, 1, 2] },
      { start: 2, end: 4, source: 'BB', translation: 'BB', words: [2, 3, 4] },
      { start: 4, end: 6, source: 'CC', translation: 'CC', words: [4, 5, 6] },
    ],
  });
});

describe('确认页撤销（Action 栈 + 稳定 seg_id）', () => {
  it('改字 → 合并 → 连续 Ctrl+Z，必须完全还原', async () => {
    render(<SimpleSubtitleEditor taskId="t1" />);
    await waitFor(() => expect(rows().length).toBe(3));
    console.log("STEP=after-Z1");
    console.log("ROWSTATE:", [0,1,2,3].map((i) => rowText(i)).filter(Boolean).join(" | "));
    console.log("STEP=after-load");
    console.log("ROWSTATE:", [0,1,2,3].map((i) => rowText(i)).filter(Boolean).join(" | "));
    const before = [0, 1, 2].map(rowText);

    // ① 改字（双击第 1 行 → Enter 提交）
    fireEvent.doubleClick(listOf().getByText('AA'));
    const input = await screen.findByDisplayValue('AA');
    fireEvent.change(input, { target: { value: 'AAA' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(rowText(0)).toContain('AAA'));
    console.log("STEP=after-edit");
    console.log("ROWSTATE:", [0,1,2,3].map((i) => rowText(i)).filter(Boolean).join(" | "));

    // ② 合并第 1 行与下一行（悬停菜单：断句 → 并入下行）
    fireEvent.click(document.querySelectorAll('.w-merge')[0]);
    const items = document.querySelectorAll('.w-menu-item');
    expect(items.length).toBeGreaterThan(0);
    fireEvent.click(items[items.length - 1]);
    await waitFor(() => expect(rows().length).toBe(2));
    console.log("STEP=after-merge");
    console.log("ROWSTATE:", [0,1,2,3].map((i) => rowText(i)).filter(Boolean).join(" | "));

    // ③ 连续撤销两次：行数先回到 3，再让文字回到初始
    fireEvent.keyDown(window, { key: 'z', ctrlKey: true });
    await waitFor(() => expect(rows().length).toBe(3));
    console.log("STEP=after-Z1");
    console.log("ROWSTATE:", [0,1,2,3].map((i) => rowText(i)).filter(Boolean).join(" | "));
    console.log("STEP=after-load");
    console.log("ROWSTATE:", [0,1,2,3].map((i) => rowText(i)).filter(Boolean).join(" | "));
    fireEvent.keyDown(window, { key: 'z', ctrlKey: true });
    await waitFor(() => expect(rowText(0)).toContain('AA'));
    console.log("STEP=after-Z2");
    console.log("ROWSTATE:", [0,1,2,3].map((i) => rowText(i)).filter(Boolean).join(" | "));

    // ④ 最终必须与初始完全一致（行数 + 每行文字）
    expect(rows().length).toBe(3);
    expect([0, 1, 2].map(rowText)).toEqual(before);
  });
});