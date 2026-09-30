import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { checkHealth, login, register } from '../api';
import { startBackend } from '../api/tauri';
import type { UserInfo } from '../types';

interface LoginPageProps {
  onAuthenticated: (user: UserInfo) => void;
}

type MsgKind = 'error' | 'info' | 'ok';

const BACKEND_URL = 'http://localhost:8000';

/** 把 axios / FastAPI 的错误整理成用户能看懂的一句话 */
function formatError(err: any): string {
  // 没有任何响应：网络层失败（后端未启动 / 端口未监听 / 跨域被拒）
  if (!err || !err.response) {
    return '无法连接后端服务（' + BACKEND_URL + '）。请确认后端已启动，可点击下方“重试连接后端”。';
  }
  const status = err.response.status;
  const detail = err.response.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    // FastAPI / pydantic 校验错误：detail 是数组
    return detail
      .map((d: any) => {
        const field = Array.isArray(d?.loc) ? d.loc.filter((x: any) => x !== 'body').join('.') : '';
        return (field ? field + '：' : '') + (d?.msg || '参数不合法');
      })
      .join('；');
  }
  if (status === 401) return '用户名或密码错误';
  return '请求失败（HTTP ' + status + '）';
}

export function LoginPage({ onAuthenticated }: LoginPageProps) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [msgKind, setMsgKind] = useState<MsgKind>('error');
  const [checking, setChecking] = useState(false);
  const [backendReady, setBackendReady] = useState<boolean | null>(null);

  const probeBackend = useCallback(async (): Promise<boolean> => {
    try {
      await checkHealth();
      setBackendReady(true);
      return true;
    } catch {
      setBackendReady(false);
      return false;
    }
  }, []);

  // 首次进入先探测一次后端
  useEffect(() => {
    void probeBackend();
  }, [probeBackend]);

  const notify = (text: string, kind: MsgKind) => {
    setMessage(text);
    setMsgKind(kind);
  };

  const retryBackend = async () => {
    setChecking(true);
    notify('正在检测后端…', 'info');
    try {
      const healthy = await probeBackend();
      if (healthy) {
        notify('后端已就绪，请登录', 'ok');
        return;
      }
      // 桌面端可尝试拉起内置后端（浏览器预览时不可用，会走 catch）
      await startBackend();
      // 后端冷启动需要十几秒，轮询等待
      for (let i = 0; i < 20; i += 1) {
        await new Promise((r) => setTimeout(r, 1500));
        if (await probeBackend()) {
          notify('后端已就绪，请登录', 'ok');
          return;
        }
      }
      notify('仍未检测到后端服务，请手动启动后端后重试', 'error');
    } catch {
      notify(
        '浏览器预览模式无法自动启动后端。请在项目目录运行：python backend_main.py，然后重试',
        'error',
      );
    } finally {
      setChecking(false);
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const name = username.trim();
    if (mode === 'register' && name.length < 3) {
      notify('用户名至少 3 个字符', 'error');
      return;
    }
    if (!name || !password) {
      notify('请输入用户名与密码', 'error');
      return;
    }
    if (mode === 'register' && password.length < 6) {
      notify('密码至少 6 个字符', 'error');
      return;
    }

    setBusy(true);
    setMessage('');
    try {
      if (mode === 'register') {
        await register(name, password, email.trim() || undefined);
      }
      const result = await login(name, password);
      onAuthenticated(result.user);
    } catch (err: any) {
      notify(formatError(err), 'error');
      void probeBackend();
    } finally {
      setBusy(false);
    }
  };

  const statusText =
    backendReady === null ? '正在检测后端…' : backendReady ? '后端服务已连接' : '后端服务未连接';
  const statusClass = backendReady ? 'ok' : backendReady === null ? '' : 'bad';

  return (
    <div className="auth-wrap">
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-brand">SubAI Translator</div>
        <div className="auth-sub">{mode === 'login' ? '登录以使用翻译服务' : '注册新账户'}</div>

        <div className={'auth-status ' + statusClass}>
          <span className="dot" />
          {statusText}
          <button type="button" className="auth-retry" onClick={retryBackend} disabled={checking}>
            {checking ? '检测中…' : '重试连接后端'}
          </button>
        </div>

        <label className="auth-label" htmlFor="auth-username">用户名</label>
        <input
          id="auth-username"
          className="auth-input"
          value={username}
          autoComplete="username"
          placeholder={mode === 'register' ? '至少 3 个字符' : ''}
          onChange={(e) => setUsername(e.target.value)}
        />

        <label className="auth-label" htmlFor="auth-password">密码</label>
        <input
          id="auth-password"
          className="auth-input"
          type="password"
          value={password}
          autoComplete="current-password"
          placeholder={mode === 'register' ? '至少 6 个字符' : ''}
          onChange={(e) => setPassword(e.target.value)}
        />

        {mode === 'register' && (
          <>
            <label className="auth-label" htmlFor="auth-email">邮箱（可选）</label>
            <input
              id="auth-email"
              className="auth-input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </>
        )}

        {message && <div className={'auth-msg ' + msgKind}>{message}</div>}

        <button className="btn primary auth-submit" type="submit" disabled={busy}>
          {busy ? '请稍候…' : mode === 'login' ? '登录' : '注册并登录'}
        </button>

        <div
          className="auth-switch"
          onClick={() => {
            setMode(mode === 'login' ? 'register' : 'login');
            setMessage('');
          }}
        >
          {mode === 'login' ? '没有账户？去注册' : '已有账户？去登录'}
        </div>

        <div className="auth-hint">默认管理员：admin / admin123</div>
      </form>
    </div>
  );
}
