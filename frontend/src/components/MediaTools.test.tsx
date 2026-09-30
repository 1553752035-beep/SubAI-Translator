import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api', () => ({
  burnHardsub: vi.fn(),
  muxSoftsub: vi.fn(),
  dubSubtitles: vi.fn(),
  getTaskSubtitles: vi.fn(),
  getVoices: vi.fn(),
  downloadOutput: vi.fn(),
}));

import {
  burnHardsub,
  downloadOutput,
  dubSubtitles,
  getTaskSubtitles,
  getVoices,
  muxSoftsub,
} from '../api';
import type { TaskRecord } from '../types';
import { MediaTools } from './MediaTools';

const mBurn = vi.mocked(burnHardsub);
const mMux = vi.mocked(muxSoftsub);
const mDub = vi.mocked(dubSubtitles);
const mSubs = vi.mocked(getTaskSubtitles);
const mVoices = vi.mocked(getVoices);
const mDownload = vi.mocked(downloadOutput);

const task = (over: Partial<TaskRecord> = {}): TaskRecord => ({
  task_id: 't1',
  video_path: 'D:/v/demo.mp4',
  mode: 'asr',
  source_lang: null,
  target_lang: 'en',
  output_format: 'srt',
  status: 'completed',
  progress: 1,
  message: '任务完成',
  result_files: ['D:/out/demo.en.srt', 'D:/out/demo.bilingual.srt', 'D:/out/demo.en.json'],
  created_at: '2026-10-01T00:00:00',
  updated_at: '2026-10-01T00:00:00',
  completed_at: '2026-10-01T00:01:00',
  error_message: null,
  ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  mVoices.mockResolvedValue({ engine: 'fake', voices: [{ name: 'voice-a', culture: 'zh-CN', engine: 'fake' }] });
  mSubs.mockResolvedValue({
    task_id: 't1', status: 'completed', kind: 'bilingual', file: 'D:/out/demo.bilingual.srt',
    segments: [
      { index: 1, start: 0, end: 1.5, source: '你好', translation: 'Hello' },
      { index: 2, start: 2, end: 3.5, source: '世界', translation: 'World' },
    ],
  });
});

describe('MediaTools', () => {
  it('只把字幕文件当作可选项（忽略 json 等）', async () => {
    render(<MediaTools task={task()} />);
    const options = await screen.findAllByRole('option');
    const values = options.map((o) => (o as HTMLOptionElement).value);
    expect(values).toContain('D:/out/demo.en.srt');
    expect(values).toContain('D:/out/demo.bilingual.srt');
    expect(values).not.toContain('D:/out/demo.en.json');
  });

  it('没有字幕文件时给出明确提示', () => {
    render(<MediaTools task={task({ result_files: ['D:/out/x.mp4'] })} />);
    expect(screen.getByText(/无法进行压制或配音/)).toBeInTheDocument();
  });

  it('压制：参数正确传入，并可下载产物', async () => {
    mBurn.mockResolvedValue({ output_path: 'D:/out/demo.hardsub.mp4', filename: 'demo.hardsub.mp4' });
    render(<MediaTools task={task()} />);

    fireEvent.change(await screen.findByLabelText('压制字幕文件'), { target: { value: 'D:/out/demo.bilingual.srt' } });
    fireEvent.change(screen.getByLabelText('CRF'), { target: { value: '22' } });
    fireEvent.change(screen.getByLabelText('字号'), { target: { value: '36' } });
    fireEvent.click(screen.getByRole('button', { name: '开始压制' }));

    await waitFor(() => expect(mBurn).toHaveBeenCalledTimes(1));
    expect(mBurn.mock.calls[0][0]).toEqual({
      video_path: 'D:/v/demo.mp4',
      subtitle_path: 'D:/out/demo.bilingual.srt',
      crf: 22,
      font_size: 36,
    });
    fireEvent.click(await screen.findByRole('button', { name: '下载' }));
    expect(mDownload).toHaveBeenCalledWith('demo.hardsub.mp4');
  });

  it('封装：把所有字幕文件作为轨道提交', async () => {
    mMux.mockResolvedValue({ output_path: 'D:/out/demo.softsub.mkv', filename: 'demo.softsub.mkv' });
    render(<MediaTools task={task()} />);
    fireEvent.click(await screen.findByRole('button', { name: '开始封装' }));
    await waitFor(() => expect(mMux).toHaveBeenCalledTimes(1));
    const tracks = mMux.mock.calls[0][0].tracks;
    expect(tracks.map((x) => x.path)).toEqual(['D:/out/demo.en.srt', 'D:/out/demo.bilingual.srt']);
  });

  it('配音：用译文按时间轴生成，并显示时长与偏差', async () => {
    mDub.mockResolvedValue({
      merged: 'D:/out/dub_ab12.wav', clips: [], max_drift_seconds: 0.12, total_seconds: 3.5,
      voice: 'voice-a', engine: 'fake', filename: 'dub_ab12.wav',
    });
    render(<MediaTools task={task()} />);
    fireEvent.click(await screen.findByRole('button', { name: '开始配音' }));

    await waitFor(() => expect(mDub).toHaveBeenCalledTimes(1));
    const payload = mDub.mock.calls[0][0];
    expect(payload.segments).toEqual([
      { start: 0, end: 1.5, text: 'Hello' },
      { start: 2, end: 3.5, text: 'World' },
    ]);
    expect(payload.voice).toBe('voice-a');
    expect(await screen.findByText(/最大同步偏差 0.12s/)).toBeInTheDocument();
  });

  it('配音可选择原文', async () => {
    mDub.mockResolvedValue({
      merged: 'x.wav', clips: [], max_drift_seconds: 0, total_seconds: 1,
      voice: 'voice-a', engine: 'fake', filename: 'x.wav',
    });
    render(<MediaTools task={task()} />);
    fireEvent.change(await screen.findByLabelText('文本来源'), { target: { value: 'source' } });
    fireEvent.click(screen.getByRole('button', { name: '开始配音' }));
    await waitFor(() => expect(mDub).toHaveBeenCalled());
    expect(mDub.mock.calls[0][0].segments[0].text).toBe('你好');
  });

  it('没有字幕文本时给出错误而不是静默失败', async () => {
    mSubs.mockResolvedValue({ task_id: 't1', status: 'completed', kind: 'bilingual', file: 'f.srt', segments: [] });
    render(<MediaTools task={task()} />);
    fireEvent.click(await screen.findByRole('button', { name: '开始配音' }));
    expect(await screen.findByText(/没有可用于配音的字幕文本/)).toBeInTheDocument();
    expect(mDub).not.toHaveBeenCalled();
  });

  it('后端报错时展示 detail 原文', async () => {
    mBurn.mockRejectedValue({ response: { data: { detail: '字幕不存在: D:/out/x.srt' } } });
    render(<MediaTools task={task()} />);
    fireEvent.click(await screen.findByRole('button', { name: '开始压制' }));
    expect(await screen.findByText('字幕不存在: D:/out/x.srt')).toBeInTheDocument();
  });
});
