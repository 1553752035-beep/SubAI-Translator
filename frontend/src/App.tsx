import { useState, useEffect, type ReactNode } from 'react';
import { WizardPage } from './pages/WizardPage';
import { SimpleSubtitleEditor } from './pages/SimpleSubtitleEditor';
import { applyTheme, getSavedTheme, saveTheme, systemTheme, type Theme } from './theme';
import { TaskProgress } from './components/TaskProgress';
import { TasksPage } from './pages/TasksPage';
import { SettingsPage } from './pages/SettingsPage';
import { HelpPage } from './pages/HelpPage';
import { PluginsPage } from './pages/PluginsPage';
import { OpenPlatformPage } from './pages/OpenPlatformPage';
import { TerminologyManager } from './components/TerminologyManager';
import { startBackend, checkBackendHealth, getSystemInfo } from './api/tauri';
import type { SystemInfo } from './api/tauri';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { LoginPage } from './pages/LoginPage';
import { getToken, getCurrentUser, logout, getLlmStatus, checkHealth, ensureLocalToken, getLocalTokenError } from './api';
import type { UserInfo, LlmStatus } from './types';

type TabId = 'home' | 'tasks' | 'terms' | 'plugins' | 'openapi' | 'settings' | 'help';

const Icon = ({ d }: { d: string }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d={d} />
  </svg>
);

const NAV_ICONS: Record<TabId, ReactNode> = {
  home: <Icon d="M3 10.5 12 3l9 7.5V21H3z" />,
  tasks: <Icon d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />,
  terms: <Icon d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />,
  settings: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4" />
    </svg>
  ),
  plugins: <Icon d="M9 3v2M15 3v2M6 7h12v3a6 6 0 0 1-6 6 6 6 0 0 1-6-6zM12 16v5" />,
  openapi: <Icon d="M15 7a4 4 0 1 0-4 4h1v3h3v3h3v-4l-3-3V7zM4 20h6" />,
  help: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10" />
      <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3M12 17h.01" />
    </svg>
  ),
};

const NAV_ITEMS: { id: TabId; label: string }[] = [
  { id: 'home', label: '首页' },
  { id: 'tasks', label: '任务列表' },
  { id: 'terms', label: '术语库管理' },
  { id: 'plugins', label: '插件' },
  { id: 'openapi', label: '开放平台' },
  { id: 'settings', label: '设置' },
  { id: 'help', label: '使用帮助' },
];

export default function App() {
  const [activeTab, setActiveTab] = useState<TabId>('home');
  // 五期：双主题。首次进入用系统主题兜底，用户可在向导页右上角切换并记住
  const [theme, setTheme] = useState<Theme>(() => getSavedTheme() ?? systemTheme());
  // 五期：高级功能默认收起来，主界面只留三段式向导
  const [navOpen, setNavOpen] = useState(false);
  const [confirmTask, setConfirmTask] = useState<string | null>(null);
  const [user, setUser] = useState<UserInfo | null>(null);
  // 后端是否要求账号登录（默认否 = 免登录模式）
  const [requireLogin, setRequireLogin] = useState(false);
  const [connectTries, setConnectTries] = useState(0);
  const [connectLog, setConnectLog] = useState("");
  const [llmStatus, setLlmStatus] = useState<LlmStatus | null>(null);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const toggleTheme = () => {
    const next: Theme = theme === 'light' ? 'dark' : 'light';
    saveTheme(next);
    setTheme(next);
  };
  const [queue, setQueue] = useState({ running: 0, waiting: 0 });
  const [backendOk, setBackendOk] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  const [systemInfo, setSystemInfo] = useState<SystemInfo>({
    memory_used_gb: 0,
    memory_total_gb: 0,
    gpu_used_gb: 0,
    gpu_total_gb: 0,
    gpu_utilization: 0,
  });

  // 自动启动后端（双击主程序即用）
  useEffect(() => {
    (async () => {
      try {
        const healthy = await checkBackendHealth();
        if (!healthy) await startBackend();
      } catch {
        /* 浏览器预览或 Tauri 未就绪时忽略 */
      }
    })();
  }, []);

  // 获取系统信息（每 5 秒刷新）
  useEffect(() => {
    const fetch = async () => {
      try {
        setSystemInfo(await getSystemInfo());
      } catch {
        /* 无 Tauri 环境时保持演示值 */
      }
    };
    fetch();
    const timer = setInterval(fetch, 5000);
    return () => clearInterval(timer);
  }, []);

  // 认证：存在令牌则向后端校验；收到 401 广播时切回登录页
  useEffect(() => {
    let cancelled = false;
    const verify = async () => {
      // 账号模式：有令牌就校验。
      // 免登录模式：反复尝试取本机令牌（后端首次启动要十几秒），
      // 期间**不显示登录页**，主界面照常渲染。
      if (!getToken()) {
        let local = await ensureLocalToken(true);
        let tries = 0;
        while (!local && !cancelled && tries < 20) {
          if (!cancelled) {
            setConnectTries(tries + 1);
            setConnectLog(getLocalTokenError());
          }
          await new Promise((r) => setTimeout(r, 1500));
          tries += 1;
          local = await ensureLocalToken(true);
        }
        if (!local) {
          if (!cancelled) setAuthChecked(true);
          return;
        }
      }
      try {
        const me = await getCurrentUser();
        if (!cancelled) { setUser(me); setAuthChecked(true); }
        return;
      } catch (e: any) {
        // 令牌有了但后端还没就绪（还在启动/正在被拉起）：显示真实原因并继续重试，
        // 不要停在"正在连接"上让人干等。
        if (!cancelled) {
          setConnectLog('后端还没就绪：' + String(e?.message || e));
          setConnectTries((v) => v + 1);
          setUser(null);
        }
        await new Promise((r) => setTimeout(r, 2000));
        if (!cancelled) void verify();
        return;
      }
    };
    void verify();
    const onUnauthorized = () => setUser(null);
    window.addEventListener('subai:unauthorized', onUnauthorized);
    return () => {
      cancelled = true;
      window.removeEventListener('subai:unauthorized', onUnauthorized);
    };
  }, []);

  // 翻译模式与队列状态一律以后端为准，避免"假切换"
  useEffect(() => {
    if (!user) {
      setLlmStatus(null);
      return;
    }
    let cancelled = false;
    const loadLlm = async () => {
      try {
        const s = await getLlmStatus();
        if (!cancelled) setLlmStatus(s);
      } catch {
        /* 忽略瞬时失败 */
      }
    };
    const loadQueue = async () => {
      try {
        const h = await checkHealth();
    if (!cancelled) setRequireLogin(!!(h as any)?.require_login);
        const qs = (h && h.queue_stats) || {};
        if (!cancelled) {
          setQueue({ running: qs.running_count || 0, waiting: qs.queue_size || 0 });
          setBackendOk(true);
        }
      } catch {
        if (!cancelled) setBackendOk(false);
      }
    };
    void loadLlm();
    void loadQueue();
    const t1 = setInterval(loadLlm, 15000);
    const t2 = setInterval(loadQueue, 5000);
    return () => {
      cancelled = true;
      clearInterval(t1);
      clearInterval(t2);
    };
  }, [user]);


  // 翻译后端是否真的可用（决定能否提交任务）
  const llmReady = !!llmStatus && (llmStatus.mode === 'local'
    ? llmStatus.local.reachable
    : llmStatus.cloud.has_key);
  const llmHint = !llmStatus
    ? '正在读取翻译后端状态'
    : llmStatus.mode === 'local'
      ? '本地翻译服务未就绪（' + llmStatus.local.url + '）'
      : '云端翻译未配置 API Key 或地址';



  // 无边框标题栏的窗口控制（浏览器预览时静默降级）
  const handleMinimize = () => {
    try { void getCurrentWindow().minimize(); } catch { /* 浏览器预览降级 */ }
  };
  const handleToggleMaximize = () => {
    try { void getCurrentWindow().toggleMaximize(); } catch { /* 浏览器预览降级 */ }
  };
  const handleClose = () => {
    try { void getCurrentWindow().close(); } catch { /* 浏览器预览降级 */ }
  };

  // 状态栏指标：有真实数据用真实值，否则用原型演示值
  const memText =
    systemInfo.memory_total_gb > 0
      ? `${systemInfo.memory_used_gb.toFixed(1)} / ${systemInfo.memory_total_gb.toFixed(1)} GB`
      : '9.2 / 32 GB';
  const gpuText =
    systemInfo.gpu_total_gb > 0
      ? `${(systemInfo.gpu_used_gb > 200 ? systemInfo.gpu_used_gb / 1024 : systemInfo.gpu_used_gb).toFixed(1)} / ${(systemInfo.gpu_total_gb > 200 ? systemInfo.gpu_total_gb / 1024 : systemInfo.gpu_total_gb).toFixed(1)} GB`
      : '2.1 / 8 GB';

  if (!authChecked) {
    return (
      <div className="app-container auth-loading">
        <div className="auth-loading-text">正在检查登录状态…</div>
      </div>
    );
  }

  if (!user) {
    // 还没有当前用户：
  //  - 后端明确要求登录 → 显示登录页（需要 SUBAI_AUTH_REQUIRE_LOGIN=true）
  //  - 否则（免登录模式）→ 显示"正在连接"，等本机令牌到位，**绝不弹登录页**
  if (!user) {
    if (requireLogin) {
      return <LoginPage onAuthenticated={setUser} />;
    }
    return (
      <div className="w-app">
        <div className="w-wrap" style={{ textAlign: 'center', paddingTop: 90 }}>
          <div className="w-spin" />
          <h1 className="w-h1">正在连接后端服务…</h1>
          <div className="w-sub">
            首次启动需要十几秒（后端是单文件程序），请稍候。
            {connectTries > 0 && <div style={{ marginTop: 8 }}>已尝试 {connectTries} 次</div>}
          </div>
          {connectLog && (
            <div className="w-err" style={{ textAlign: 'left', display: 'inline-block' }}>
              取本机令牌失败：{connectLog}
              <div style={{ marginTop: 6, opacity: 0.8 }}>
                可截图给我；或直接告诉我 D:\SubAI-Translator\tauri_debug.log 的最后几行。
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }
  }

  // 五期：确认页作为独立整页显示（不在向导页下方挤着）
  if (confirmTask) {
    return (
      <div className="w-app">
        <div className="w-wrap">
          <SimpleSubtitleEditor taskId={confirmTask} onClose={() => setConfirmTask(null)} />
        </div>
      </div>
    );
  }

  return (
    <div className="app-container">
      <div className="titlebar">
        <div className="logo" />
        <div className="title">
          SubAI Translator <span>v2.0</span>
        </div>
        <div className="spacer" />
        <div className="user-chip">
            
          {requireLogin && user.role === 'admin' && <em>管理员</em>}
          <button
            className="win-btn"
            title="退出登录"
            onClick={() => {
              logout();
              setUser(null);
            }}
          >
            ⏻
          </button>
        </div>
        <div className="window-controls">
          <button className="win-btn" onClick={handleMinimize}>─</button>
          <button className="win-btn" onClick={handleToggleMaximize}>□</button>
          <button className="win-btn close" onClick={handleClose}>✕</button>
        </div>
      </div>

      <div className="main-content">
        <div className={'sidebar' + (navOpen ? '' : ' w-hidden')}>
            <button className="w-btn w-ghost" style={{ marginBottom: 10, width: "100%" }} onClick={() => setNavOpen(false)}>收起</button>
          {NAV_ITEMS.map((item) => (
            <div
              key={item.id}
              className={`nav-item ${activeTab === item.id ? 'active' : ''}`}
              onClick={() => setActiveTab(item.id)}
            >
              {NAV_ICONS[item.id]}
              {item.label}
            </div>
          ))}
          <div className="divider" />

        </div>

        <div className="content">
          {activeTab !== 'home' && !navOpen && (
            <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
              <button className="w-btn w-ghost" title="打开侧边栏" style={{ padding: "5px 11px" }} onClick={() => setNavOpen(true)}>☰</button>
              <button className="w-btn w-ghost" title="返回主界面" style={{ padding: "5px 11px" }} onClick={() => setActiveTab('home')}>←</button>
            </div>
          )}
          {llmStatus && !llmReady && (
            <div className="notice warn">
              <b>翻译后端不可用</b>：{llmHint}。任务会在翻译阶段失败——请先启动本地翻译服务，或在“设置 → 翻译后端”中配置并切换到云端 API。
              <button className="btn" style={{ marginLeft: '10px', padding: '3px 10px' }} onClick={() => setActiveTab('settings')}>
                去设置
              </button>
            </div>
          )}
          {activeTab === 'home' && (
            <>
              <WizardPage
                onEditTask={(id) => { setActiveTaskId(id); setConfirmTask(id); }}
                theme={theme}
                onToggleTheme={toggleTheme}
                onOpenAdvanced={() => setNavOpen((v) => !v)}
              />
              {activeTaskId && (
                <>
                  <TaskProgress taskId={activeTaskId} />
                  <div id="sub-editor">
                    <SimpleSubtitleEditor taskId={activeTaskId} />
                  </div>
                </>
              )}
            </>
          )}
          {activeTab === 'tasks' && <TasksPage />}
          {activeTab === 'terms' && (
            <>
              <div className="page-head">
                <h1>术语库管理</h1>
                <div className="sub">管理专业术语，提升翻译准确率</div>
              </div>
              <TerminologyManager />
            </>
          )}
          {activeTab === 'settings' && <SettingsPage />}
          {activeTab === 'help' && <HelpPage />}
      {activeTab === 'plugins' && <PluginsPage />}
      {activeTab === 'openapi' && <OpenPlatformPage />}
        </div>
      </div>

      <div className="statusbar">
        <span>
          <span className={backendOk ? 'led' : 'led off'} />
          {backendOk ? '后端服务运行中' : '后端服务未连接'} · localhost:8000
        </span>
        <span>
          队列 <b>{queue.running}</b> 运行 / <b>{queue.waiting}</b> 等待
        </span>
        <span className="right">
          <span>
            内存 <b>{memText}</b>
          </span>
          <span>
            GPU <b>{gpuText}</b>
          </span>
        </span>
      </div>
    </div>
  );
}
