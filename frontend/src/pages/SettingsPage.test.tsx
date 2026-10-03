import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@tauri-apps/plugin-updater', () => ({ check: vi.fn() }));

vi.mock('../api', () => ({
  changePassword: vi.fn(),
  checkHealth: vi.fn(),
  clearCache: vi.fn(),
  getAsrDevice: vi.fn(),
  getCacheStats: vi.fn(),
  getCurrentUser: vi.fn(),
  getLlmStatus: vi.fn(),
  getQueueStats: vi.fn(),
  getTranslationSettings: vi.fn(),
  setLlmMode: vi.fn(),
  setTermMode: vi.fn(),
  testLlm: vi.fn(),
  getLanguages: vi.fn(),
  getLlmProviders: vi.fn(),
  detectLanguage: vi.fn(),
  getOpenApiStats: vi.fn(),
  downloadReport: vi.fn(),
}));

import {
  checkHealth,
  getAsrDevice,
  getCacheStats,
  getCurrentUser,
  getLanguages,
  getLlmProviders,
  getLlmStatus,
  getOpenApiStats,
  getQueueStats,
  getTranslationSettings,
  setTermMode,
} from '../api';
import { SettingsPage } from './SettingsPage';

const mTerm = vi.mocked(getTranslationSettings);
const mSetTerm = vi.mocked(setTermMode);

const termCard = () => screen.getByText('术语库模式').closest('.table-card') as HTMLElement;

// 只读"当前模式"那一行的值，避免与同名按钮冲突
const rowValues = () => Array.from(termCard().querySelectorAll('.v')).map((e) => e.textContent);

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getCurrentUser).mockResolvedValue({
    user_id: 'u1', username: 'admin', role: 'admin', email: null,
    is_active: true, created_at: '', updated_at: '',
  });
  vi.mocked(checkHealth).mockResolvedValue({ status: 'ok', version: '4.1.0' } as any);
  vi.mocked(getAsrDevice).mockResolvedValue({
    configured: 'auto', effective_device: 'cpu', compute_type: 'int8',
    ct2_cuda_supported: true, cuda_dll_dirs: [], free_vram_gb: 6.8,
  });
  vi.mocked(getLlmStatus).mockResolvedValue({
    mode: 'local',
    effective: { url: 'http://127.0.0.1:5001/v1/chat/completions', model: 'koboldcpp' },
    local: { reachable: true, detail: 'HTTP 200' },
    cloud: { url: '', model: '', has_key: false },
  } as any);
  // 让缓存/队列渲染成 '-'，避免猜测结构
  vi.mocked(getCacheStats).mockRejectedValue(new Error('n/a'));
  vi.mocked(getQueueStats).mockRejectedValue(new Error('n/a'));
  vi.mocked(getLanguages).mockResolvedValue({
    languages: [],
    stats: { total: 72, asr: 44, translate: 72, tts: 35 },
  });
  vi.mocked(getLlmProviders).mockResolvedValue({
    providers: [
      { id: 'deepseek', name: 'DeepSeek 深度求索', base_url: 'https://api.deepseek.com/v1',
        models: ['deepseek-chat'], key_url: 'https://platform.deepseek.com/api_keys', note: '推荐 chat' },
    ],
  } as any);
  vi.mocked(getOpenApiStats).mockResolvedValue({
    keys: { keys: 2, calls: 10 },
    webhooks: { deliveries: 5, success_rate: 1 },
  });
  mTerm.mockResolvedValue({
    term_mode: 'strict',
    available: [
      { value: 'strict', label: '强制锁定', description: '译名一致' },
      { value: 'hint', label: '软提示', description: '语句自然' },
    ],
  });
});

describe('SettingsPage 术语库模式', () => {
  it('展示后端返回的当前模式', async () => {
    render(<SettingsPage />);
    await waitFor(() => expect(rowValues()).toContain('强制锁定'));
    expect(within(termCard()).getByRole('button', { name: '软提示' })).toBeInTheDocument();
  });

  it('切换到软提示会调用接口并立即反映到界面', async () => {
    mSetTerm.mockResolvedValue({ term_mode: 'hint' });
    render(<SettingsPage />);
    await waitFor(() => expect(rowValues()).toContain('强制锁定'));

    fireEvent.click(within(termCard()).getByRole('button', { name: '软提示' }));

    await waitFor(() => expect(mSetTerm).toHaveBeenCalledWith('hint'));
    expect(await screen.findByText(/术语模式已切换为软提示/)).toBeInTheDocument();
    await waitFor(() => expect(rowValues()).toContain('软提示'));
  });

  it('切换失败时展示后端 detail', async () => {
    mSetTerm.mockRejectedValue({ response: { data: { detail: 'mode 必须是 strict / hint' } } });
    render(<SettingsPage />);
    await waitFor(() => expect(rowValues()).toContain('强制锁定'));

    fireEvent.click(within(termCard()).getByRole('button', { name: '强制锁定' }));

    expect(await screen.findByText('mode 必须是 strict / hint')).toBeInTheDocument();
  });

  it('读取失败时不会显示虚假模式', async () => {
    mTerm.mockRejectedValue(new Error('boom'));
    render(<SettingsPage />);
    await waitFor(() => expect(mTerm).toHaveBeenCalled());
    await waitFor(() => expect(rowValues()).toContain('-'));
  });
});

describe("SettingsPage 版本与更新", () => {
  it("显示当前版本", async () => {
    render(<SettingsPage />);
    expect(await screen.findByText("版本与更新")).toBeInTheDocument();
    expect(screen.getByText("4.1.0")).toBeInTheDocument();
  });

  it("已是最新时给出提示", async () => {
    const { check } = await import("@tauri-apps/plugin-updater");
    vi.mocked(check).mockResolvedValue(null);
    render(<SettingsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "检查更新" }));
    expect(await screen.findByText(/已是最新版本/)).toBeInTheDocument();
  });

  it("有更新时给出新版本与安装按钮", async () => {
    const { check } = await import("@tauri-apps/plugin-updater");
    vi.mocked(check).mockResolvedValue({ version: "9.9.9", body: "修复若干问题" } as any);
    render(<SettingsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "检查更新" }));
    expect(await screen.findByText(/发现新版本 9.9.9/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下载并安装" })).toBeInTheDocument();
  });

  it("检查失败时给出失败提示而不是崩溃", async () => {
    const { check } = await import("@tauri-apps/plugin-updater");
    vi.mocked(check).mockRejectedValue(new Error("updater 未配置"));
    render(<SettingsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "检查更新" }));
    expect(await screen.findByText(/检查更新失败：updater 未配置/)).toBeInTheDocument();
  });
});
