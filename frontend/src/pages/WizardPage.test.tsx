import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { WizardPage } from './WizardPage';

const mGetAsrEngine = vi.fn();
const mSubmitTranscode = vi.fn();
const mUpload = vi.fn();

vi.mock('../api', () => ({
  getAsrEngine: (...a: any[]) => mGetAsrEngine(...a),
  submitTranscodeTask: (...a: any[]) => mSubmitTranscode(...a),
  uploadVideoFile: (...a: any[]) => mUpload(...a),
  listGlossary: vi.fn().mockResolvedValue({ series: [] }),
  saveGlossarySeries: vi.fn().mockResolvedValue({}),
  getTaskStatus: vi.fn().mockResolvedValue({ status: 'running', progress: 0.1 }),
  openInExplorer: vi.fn(),
  submitAlignTask: vi.fn().mockResolvedValue({ task_id: 't1' }),
  submitComposeTask: vi.fn().mockResolvedValue({ task_id: 't2' }),
}));

const ENGINE_ALL = {
  engine: 'sensevoice',
  models: { sensevoice: true, paraformer: true, qwen3: false, firered: false, vad: true, denoise: false },
};

/** 走到 options 步骤：选文件 -> 选意图 -> 选项页 */
const gotoOptions = async () => {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  const file = new File(['x'], 'a.mp4', { type: 'video/mp4' });
  fireEvent.change(input, { target: { files: [file] } });
  // 意图页：点第一个「翻译」卡片（不是「只加字幕，不翻译」）
  const cards = await screen.findAllByText('翻译');
  fireEvent.click(cards[0]);
};

describe('WizardPage 逐任务选 ASR 引擎', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mGetAsrEngine.mockResolvedValue(ENGINE_ALL);
    mUpload.mockResolvedValue({ video_path: 'C:/v/a.mp4' });
    mSubmitTranscode.mockResolvedValue({ task_id: 'task-1', status: 'pending', message: '' });
  });

  it('默认跟随设置，并显示当前全局引擎', async () => {
    render(<WizardPage theme={'dark' as any} />);
    await gotoOptions();
    // 用 class 定位 chip，避免匹配到说明文字
    const chip = await waitFor(() => {
      const el = Array.from(document.querySelectorAll('.w-chip'))
        .find((n) => n.textContent?.startsWith('跟随设置'));
      if (!el) throw new Error('没渲染出「跟随设置」chip');
      return el as HTMLElement;
    });
    // 默认态：不覆盖全局配置
    expect(chip.className).toContain('on');
    // 应显示全局引擎名，用户才知道「跟随」到底跟的是什么
    expect(chip.textContent).toContain('sensevoice');
  });

  it('引擎列表按可用性置灰，未安装的点不动', async () => {
    render(<WizardPage theme={'dark' as any} />);
    await gotoOptions();

    const qwen = await screen.findByText('Qwen3');
    // qwen3: false -> 置灰
    expect(qwen.getAttribute('aria-disabled')).toBe('true');
    fireEvent.click(qwen);
    // 点了也不应选中（仍无 on 类）
    expect(qwen.className).not.toContain(' on');

    const sv = await screen.findByText('SenseVoice');
    expect(sv.getAttribute('aria-disabled')).toBe('false');
  });

  it('选中已安装引擎后，提交带上 asr_engine', async () => {
    render(<WizardPage theme={'dark' as any} />);
    await gotoOptions();

    const sv = await screen.findByText('SenseVoice');
    fireEvent.click(sv);
    expect(sv.className).toContain(' on');
    // 选具体引擎后「跟随设置」应取消选中，避免两个同时高亮
    const follow = Array.from(document.querySelectorAll('.w-chip'))
      .find((n) => n.textContent?.startsWith('跟随设置')) as HTMLElement;
    expect(follow.className).not.toContain(' on');
  });

  it('引擎接口失败时不阻断，选项仍可点', async () => {
    mGetAsrEngine.mockRejectedValue(new Error('boom'));
    render(<WizardPage theme={'dark' as any} />);
    await gotoOptions();

    const sv = await screen.findByText('SenseVoice');
    // 拿不到可用性信息 -> 当作全部可用
    expect(sv.getAttribute('aria-disabled')).toBe('false');
    fireEvent.click(sv);
    expect(sv.className).toContain(' on');
  });
});