import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@tauri-apps/plugin-updater', () => ({ check: vi.fn() }));

vi.mock('../api', () => ({
  changePassword: vi.fn(),
  checkHealth: vi.fn(),
  clearCache: vi.fn(),
  getAsrDevice: vi.fn(),
  getAsrEngine: vi.fn(),
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
  probeLlmProviders: vi.fn(),
  getLlmProviderHealth: vi.fn(),
  cancelAsrModel: vi.fn(),
  downloadAsrModel: vi.fn(),
  getAsrModelStatus: vi.fn(),
  getSubtitleQuality: vi.fn(),
  openExternal: vi.fn(),
}));

import {
  checkHealth,
  getAsrDevice,
  getAsrEngine,
  getCacheStats,
  getCurrentUser,
  getLanguages,
  getLlmProviders,
  getLlmStatus,
  getOpenApiStats,
  getQueueStats,
  getTranslationSettings,
  probeLlmProviders,
  getSubtitleQuality,
  getAsrModelStatus,
  downloadAsrModel,
  cancelAsrModel,
  openExternal,
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
  // 新增 mock 必须给默认值：页面挂载时会立刻调用它们，
  // 返回 undefined 会在 .then 上炸掉，整个用例连渲染都过不去
  vi.mocked(getSubtitleQuality).mockResolvedValue({
    drop_hallucination: false, hallucination_nsp: 0.6, hallucination_cr: 2.4,
    max_subtitle_sec: 8, asr_device: 'auto', need_restart_to_apply: true,
  } as any);
  vi.mocked(getAsrModelStatus).mockResolvedValue({
    models: {}, dir: '', downloading: false,
  } as any);
  vi.mocked(downloadAsrModel).mockResolvedValue({ ok: true } as any);
  vi.mocked(cancelAsrModel).mockResolvedValue({ ok: true } as any);
  vi.mocked(openExternal).mockResolvedValue(undefined as any);
  vi.mocked(getAsrEngine).mockResolvedValue({
    engine: 'whisper', denoise: false, sensevoice_itn: true,
    sensevoice_language: 'auto', vad_threshold: 0.5,
    vad_min_silence_ms: 100, vad_min_speech_ms: 250,
    need_restart_to_apply: true, sherpa_installed: false,
    models: { sensevoice: false, paraformer: false, qwen3: false,
              vad: false, denoise: false },
    models_dir: 'models/sherpa',
  } as any);
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

describe('SettingsPage 服务商核验', () => {
  it('点核验后展示每个服务商的结论', async () => {
    vi.mocked(probeLlmProviders).mockResolvedValue({
      results: [
        { id: 'deepseek', name: 'DeepSeek', verdict: 'auth_failed', detail: 'HTTP 401' },
        { id: 'yi', name: '零一万物', verdict: 'discontinued', detail: 'model_service_closed' },
        { id: 'openrouter', name: 'OpenRouter', verdict: 'ok', detail: 'HTTP 200' },
      ],
      summary: { total: 3 },
    } as any);
    render(<SettingsPage />);
    fireEvent.click(await screen.findByRole('button', { name: '核验全部服务商' }));
    await waitFor(() => expect(screen.getByText('已停服')).toBeInTheDocument());
    expect(screen.getByText('Key 无效')).toBeInTheDocument();
    expect(screen.getByText('可用')).toBeInTheDocument();
  });

  it('已停服排在网络不可达之前', async () => {
    vi.mocked(probeLlmProviders).mockResolvedValue({
      results: [
        { id: 'openai', name: 'OpenAI', verdict: 'network_error', detail: 'timeout' },
        { id: 'yi', name: '零一万物', verdict: 'discontinued', detail: 'closed' },
      ],
      summary: { total: 2 },
    } as any);
    render(<SettingsPage />);
    fireEvent.click(await screen.findByRole('button', { name: '核验全部服务商' }));
    await waitFor(() => expect(screen.getByText('已停服')).toBeInTheDocument());
    // 用「结论文字」定位所在行，再取该行的名字单元格。
    // 直接扫 div 的 textContent 会匹配到外层容器，顺序不可靠。
    const rowOf = (verdict: string) => {
      const cell = Array.from(document.querySelectorAll('span'))
        .find((s) => s.textContent === verdict);
      return cell?.parentElement as HTMLElement;
    };
    const disc = rowOf('已停服');
    const net = rowOf('本机不可达');
    expect(disc).toBeTruthy();
    expect(net).toBeTruthy();
    // compareDocumentPosition: 4 = DOCUMENT_POSITION_FOLLOWING
    expect(disc.compareDocumentPosition(net) & 4).toBe(4);
    expect(disc.children[0].textContent).toBe('零一万物');
  });

  it('核验失败时给出错误提示，不静默', async () => {
    vi.mocked(probeLlmProviders).mockRejectedValue(new Error('后端未就绪'));
    render(<SettingsPage />);
    fireEvent.click(await screen.findByRole('button', { name: '核验全部服务商' }));
    await waitFor(() => expect(screen.getByText(/后端未就绪/)).toBeInTheDocument());
  });
});
