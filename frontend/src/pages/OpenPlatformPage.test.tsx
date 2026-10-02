import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api', () => ({
  getOpenApiKeys: vi.fn(),
  createOpenApiKey: vi.fn(),
  setKeyEnabled: vi.fn(),
  revokeOpenApiKey: vi.fn(),
  setKeyRateLimit: vi.fn(),
  getWebhooks: vi.fn(),
  createWebhook: vi.fn(),
  setWebhookEnabled: vi.fn(),
  deleteWebhook: vi.fn(),
  testWebhook: vi.fn(),
  getWebhookDeliveries: vi.fn(),
  retryDelivery: vi.fn(),
}));

import {
  createOpenApiKey,
  createWebhook,
  getOpenApiKeys,
  getWebhookDeliveries,
  getWebhooks,
  retryDelivery,
  testWebhook,
} from '../api';
import { OpenPlatformPage } from './OpenPlatformPage';

const KEY = {
  key_id: 'key_1',
  name: '我的脚本',
  prefix: 'subai_abcd****',
  scopes: ['translate'],
  enabled: true,
  revoked: false,
  rate_limit: null,
  call_count: 7,
  error_count: 1,
  success_rate: 0.875,
  last_used_at: null,
};

const HOOK = {
  webhook_id: 'wh_1',
  url: 'https://example.com/hook',
  events: ['task.completed'],
  enabled: true,
  secret: 'whsec****',
  created_at: 1,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getOpenApiKeys).mockResolvedValue({
    keys: [KEY as any],
    stats: { keys: 1, calls: 7 },
  });
  vi.mocked(getWebhooks).mockResolvedValue({
    webhooks: [HOOK as any],
    stats: { webhooks: 1, deliveries: 3, success_rate: 0.667, stale_pending: 0 },
    events: ['task.completed', 'task.failed'],
  });
});

describe('OpenPlatformPage', () => {
  it('展示密钥与回调信息', async () => {
    render(<OpenPlatformPage />);
    expect(await screen.findByText(/subai_abcd\*\*\*\*/)).toBeInTheDocument();
    expect(screen.getByText(/调用 7/)).toBeInTheDocument();
    expect(screen.getByText('https://example.com/hook')).toBeInTheDocument();
    expect(screen.getByText(/成功率 67%/)).toBeInTheDocument();
  });

  it('创建密钥后明文只显示一次', async () => {
    vi.mocked(createOpenApiKey).mockResolvedValue({
      secret: 'subai_brand_new_secret', key: KEY as any, notice: '只显示一次',
    });
    render(<OpenPlatformPage />);
    await screen.findByText(/subai_abcd/);
    fireEvent.change(screen.getByPlaceholderText(/密钥名称/), { target: { value: '我的脚本' } });
    fireEvent.click(screen.getByRole('button', { name: '创建密钥' }));
    expect(await screen.findByText(/subai_brand_new_secret/)).toBeInTheDocument();
    await waitFor(() => expect(vi.mocked(createOpenApiKey)).toHaveBeenCalledWith(
      '我的脚本', ['translate', 'tasks', 'languages', 'transcode'], null,
    ));
  });

  it('添加 Webhook 后展示签名密钥', async () => {
    vi.mocked(createWebhook).mockResolvedValue({
      webhook: HOOK as any, secret: 'sign-key-123', notice: '请保存',
    });
    render(<OpenPlatformPage />);
    await screen.findByText('https://example.com/hook');
    fireEvent.change(screen.getByPlaceholderText(/回调地址/), {
      target: { value: 'https://new.example.com/cb' },
    });
    fireEvent.click(screen.getByRole('button', { name: '添加 Webhook' }));
    expect(await screen.findByText(/sign-key-123/)).toBeInTheDocument();
    await waitFor(() => expect(vi.mocked(createWebhook)).toHaveBeenCalledWith(
      'https://new.example.com/cb', [],
    ));
  });

  it('测试回调与查看投递记录', async () => {
    vi.mocked(testWebhook).mockResolvedValue({ webhook_id: 'wh_1', deliveries: [] });
    vi.mocked(getWebhookDeliveries).mockResolvedValue({
      deliveries: [{
        delivery_id: 'dl_1', webhook_id: 'wh_1', event: 'task.completed',
        status: 'failed', attempts: 3, status_code: 500, error: '连接超时', created_at: 1,
      } as any],
    });
    vi.mocked(retryDelivery).mockResolvedValue({ delivery_id: 'dl_1', status: 'success' });
    render(<OpenPlatformPage />);
    await screen.findByText('https://example.com/hook');

    fireEvent.click(screen.getByRole('button', { name: '测试' }));
    await waitFor(() => expect(vi.mocked(testWebhook)).toHaveBeenCalledWith('wh_1'));

    fireEvent.click(screen.getByRole('button', { name: '投递记录' }));
    expect(await screen.findByText(/尝试 3 次/)).toBeInTheDocument();
    expect(screen.getByText(/连接超时/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '重投' }));
    await waitFor(() => expect(vi.mocked(retryDelivery)).toHaveBeenCalledWith('dl_1'));
  });

  it('加载失败时给出提示', async () => {
    vi.mocked(getOpenApiKeys).mockRejectedValue(new Error('boom'));
    render(<OpenPlatformPage />);
    expect(await screen.findByText(/加载失败/)).toBeInTheDocument();
  });
});
