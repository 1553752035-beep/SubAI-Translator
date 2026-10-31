import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mWave = vi.fn();
vi.mock('../api', () => ({
  getWaveform: (...a: any[]) => mWave(...a),
}));

import { WaveformView } from './WaveformView';

/**
 * 波形组件测试。
 *
 * jsdom 没有真实的 canvas 2D 上下文，所以绘制本身不在这里验证
 * （那部分靠后端的 peaks 数值测试 + 真实浏览器人工确认）。
 * 这里盯住的是**交互与数据流**，这些是真正会坏的：
 * 1. 请求参数正确（桶数跟宽度走）
 * 2. 加载失败要显示错误，而不是白屏
 * 3. 点击能算出正确时间点
 */
describe('WaveformView', () => {
  beforeEach(() => {
    mWave.mockReset();
    // jsdom 里 canvas.getContext 返回 null，给个最小桩避免抛错
    HTMLCanvasElement.prototype.getContext = vi.fn(() => null) as any;
  });

  it('请求波形时桶数随容器宽度走', async () => {
    mWave.mockResolvedValue({ buckets: 2, duration: 10, peaks: [[0, 1], [0, 0.5]], sample_rate: 8000, silence_ratio: 0.5 });
    render(<WaveformView mediaPath="C:/v/a.mp4" />);
    await waitFor(() => expect(mWave).toHaveBeenCalledTimes(1));
    const arg = mWave.mock.calls[0][0];
    expect(arg.path).toBe('C:/v/a.mp4');
    expect(arg.buckets).toBeGreaterThanOrEqual(200);
  });

  it('没有媒体路径时不发请求', () => {
    render(<WaveformView mediaPath="" />);
    expect(mWave).not.toHaveBeenCalled();
  });

  it('加载失败显示后端错误信息', async () => {
    mWave.mockRejectedValue({ response: { data: { detail: '媒体不存在: C:/nope.mp4' } } });
    render(<WaveformView mediaPath="C:/nope.mp4" />);
    expect(await screen.findByText(/媒体不存在/)).toBeInTheDocument();
  });

  it('点击波形换算成秒并回调', async () => {
    mWave.mockResolvedValue({ buckets: 2, duration: 100, peaks: [[0, 1], [0, 0.5]], sample_rate: 8000, silence_ratio: 0 });
    const onSeek = vi.fn();
    render(<WaveformView mediaPath="C:/v/a.mp4" onSeek={onSeek} />);
    await waitFor(() => expect(mWave).toHaveBeenCalled());

    const canvas = screen.getByLabelText('音频波形') as HTMLCanvasElement;
    // jsdom 下 getBoundingClientRect 全 0，手动给宽度
    canvas.getBoundingClientRect = () => ({ left: 0, width: 400, top: 0, height: 76, right: 400, bottom: 76, x: 0, y: 0, toJSON: () => ({}) }) as any;
    fireEvent.click(canvas, { clientX: 100 });   // 1/4 处 -> 25 秒
    expect(onSeek).toHaveBeenCalledWith(25);
  });

  it('没传 onSeek 时点击不崩', async () => {
    mWave.mockResolvedValue({ buckets: 2, duration: 10, peaks: [[0, 1], [0, 0.5]], sample_rate: 8000, silence_ratio: 0 });
    render(<WaveformView mediaPath="C:/v/a.mp4" />);
    await waitFor(() => expect(mWave).toHaveBeenCalled());
    const canvas = screen.getByLabelText('音频波形');
    expect(() => fireEvent.click(canvas, { clientX: 10 })).not.toThrow();
  });
});
