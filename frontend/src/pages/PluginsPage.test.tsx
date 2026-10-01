import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api', () => ({
  listPlugins: vi.fn(),
  setPluginEnabled: vi.fn(),
  reloadPlugins: vi.fn(),
  probePlugin: vi.fn(),
  getPluginMarketplace: vi.fn(),
}));

import { getPluginMarketplace, listPlugins, setPluginEnabled } from '../api';
import type { PluginInfo, PluginListResponse } from '../types';
import { PluginsPage } from './PluginsPage';

const mList = vi.mocked(listPlugins);
const mSet = vi.mocked(setPluginEnabled);
const mMarket = vi.mocked(getPluginMarketplace);

const plugin = (over: Partial<PluginInfo> = {}): PluginInfo => ({
  id: 'subai.ocr.rapidocr',
  name: 'RapidOCR 硬字幕识别',
  kind: 'ocr',
  version: '1.0.0',
  description: '从视频画面识别硬字幕',
  author: '内置',
  builtin: true,
  external: false,
  enabled: true,
  loaded: true,
  state: 'enabled',
  error: '',
  capabilities: ['recognize'],
  available: true,
  ...over,
});

const listing = (plugins: PluginInfo[]): PluginListResponse => ({
  plugins,
  stats: { total: plugins.length, enabled: plugins.filter((p) => p.enabled).length, errors: 0, by_kind: {} },
  kinds: ['translator', 'ocr', 'tts'],
});

beforeEach(() => {
  vi.clearAllMocks();
  mList.mockResolvedValue(listing([plugin()]));
  mMarket.mockResolvedValue({
    entries: [
      {
        id: 'demo.tts.edge',
        name: '示例语音插件',
        kind: 'tts',
        version: '0.9.0',
        description: '演示用',
        author: '某人',
        rating: null,
        installed: false,
      },
    ],
    note: '',
  });
  mSet.mockResolvedValue(plugin({ enabled: false }));
});

describe('PluginsPage', () => {
  it('渲染插件列表与统计', async () => {
    render(<PluginsPage />);
    expect(await screen.findByText('RapidOCR 硬字幕识别')).toBeInTheDocument();
    expect(screen.getByText(/共 1 个/)).toBeInTheDocument();
    expect(screen.getByText('示例语音插件')).toBeInTheDocument();
  });

  it('点击停用会调用接口并刷新', async () => {
    render(<PluginsPage />);
    fireEvent.click(await screen.findByRole('button', { name: '停用' }));
    await waitFor(() => expect(mSet).toHaveBeenCalledWith('subai.ocr.rapidocr', false));
    await waitFor(() => expect(mList).toHaveBeenCalledTimes(2));
  });

  it('展示插件错误信息', async () => {
    mList.mockResolvedValue(listing([plugin({ id: 'bad', name: '坏插件', state: 'error', error: '清单不是合法 JSON', enabled: false })]));
    render(<PluginsPage />);
    expect(await screen.findByText(/清单不是合法 JSON/)).toBeInTheDocument();
  });

  it('目录搜索会带上关键词', async () => {
    render(<PluginsPage />);
    const input = await screen.findByPlaceholderText(/搜索插件/);
    fireEvent.change(input, { target: { value: '语音' } });
    fireEvent.click(screen.getByRole('button', { name: '搜索' }));
    await waitFor(() => expect(mMarket).toHaveBeenLastCalledWith('语音'));
  });

  it('分类筛选只显示对应类型', async () => {
    mList.mockResolvedValue(listing([
      plugin(),
      plugin({ id: 'subai.tts.sapi', name: 'SAPI 配音', kind: 'tts', capabilities: ['synthesize'] }),
    ]));
    render(<PluginsPage />);
    expect(await screen.findByText('RapidOCR 硬字幕识别')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '配音' }));
    await waitFor(() => expect(screen.queryByText('RapidOCR 硬字幕识别')).toBeNull());
    expect(screen.getByText('SAPI 配音')).toBeInTheDocument();
  });
});
