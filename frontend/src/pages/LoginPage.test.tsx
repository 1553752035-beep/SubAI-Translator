import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api', () => ({
  checkHealth: vi.fn(),
  login: vi.fn(),
  register: vi.fn(),
}));
vi.mock('../api/tauri', () => ({
  startBackend: vi.fn(),
}));

import { checkHealth, login, register } from '../api';
import { LoginPage, formatError } from './LoginPage';

const mockLogin = vi.mocked(login);
const mockRegister = vi.mocked(register);
const mockHealth = vi.mocked(checkHealth);

describe('formatError', () => {
  it('无响应时提示无法连接后端', () => {
    expect(formatError(new Error('Network Error'))).toContain('无法连接后端服务');
  });

  it('字符串 detail 原样展示', () => {
    expect(formatError({ response: { status: 400, data: { detail: '用户名已存在' } } })).toBe('用户名已存在');
  });

  it('数组 detail 逐条拼成可读信息（含字段名）', () => {
    const msg = formatError({
      response: {
        status: 422,
        data: { detail: [{ loc: ['body', 'password'], msg: 'String should have at least 6 characters' }] },
      },
    });
    expect(msg).toContain('password');
    expect(msg).toContain('at least 6 characters');
  });

  it('401 给出用户名或密码错误', () => {
    expect(formatError({ response: { status: 401, data: {} } })).toBe('用户名或密码错误');
  });
});

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockHealth.mockRejectedValue(new Error('down'));
  });

  it('展示默认管理员提示与登录按钮', async () => {
    render(<LoginPage onAuthenticated={vi.fn()} />);
    expect(screen.getByRole('button', { name: '登录' })).toBeInTheDocument();
    expect(screen.getByText(/admin \/ admin123/)).toBeInTheDocument();
  });

  it('注册模式下密码过短会被前端拦下', async () => {
    render(<LoginPage onAuthenticated={vi.fn()} />);
    fireEvent.click(screen.getByText('没有账户？去注册'));
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'someone' } });
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: '123' } });
    fireEvent.click(screen.getByRole('button', { name: '注册并登录' }));
    expect(await screen.findByText('密码至少 6 个字符')).toBeInTheDocument();
    expect(mockRegister).not.toHaveBeenCalled();
  });

  it('登录失败时展示后端返回的字段级原因', async () => {
    mockLogin.mockRejectedValue({
      response: { status: 422, data: { detail: [{ loc: ['body', 'password'], msg: 'String should have at least 6 characters' }] } },
    });
    render(<LoginPage onAuthenticated={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'admin' } });
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'admin123' } });
    fireEvent.click(screen.getByRole('button', { name: '登录' }));
    expect(await screen.findByText(/at least 6 characters/)).toBeInTheDocument();
  });

  it('登录成功会回调用户信息', async () => {
    const onAuth = vi.fn();
    mockLogin.mockResolvedValue({
      access_token: 't',
      token_type: 'bearer',
      expires_in: 86400,
      user: { user_id: 'u1', username: 'admin', role: 'admin', email: null, is_active: true, created_at: '', updated_at: '' },
    });
    render(<LoginPage onAuthenticated={onAuth} />);
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'admin' } });
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'admin123' } });
    fireEvent.click(screen.getByRole('button', { name: '登录' }));
    await waitFor(() => expect(onAuth).toHaveBeenCalledTimes(1));
    expect(onAuth.mock.calls[0][0].username).toBe('admin');
  });
});
