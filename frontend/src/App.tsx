import { useState, useCallback, useEffect } from 'react';
import { VideoUpload } from './components/VideoUpload';
import { TaskProgress } from './components/TaskProgress';
import { SubtitleEditor } from './components/SubtitleEditor';
import { TasksPage } from './pages/TasksPage';
import { SettingsPage } from './pages/SettingsPage';
import { HelpPage } from './pages/HelpPage';
import { startBackend, checkBackendHealth, getSystemInfo } from './api/tauri';
import type { SystemInfo } from './api/tauri';

// 侧边栏导航项
type TabId = 'home' | 'tasks' | 'terms' | 'settings' | 'help';

function NavItem({
  id,
  label,
  icon,
  active,
  onClick,
}: {
  id: TabId;
  label: string;
  icon: string;
  active: boolean;
  onClick: (id: TabId) => void;
}) {
  return (
    <div
      onClick={() => onClick(id)}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
        padding: '10px 12px',
        cursor: 'pointer',
        borderRadius: '6px',
        backgroundColor: active ? 'rgba(102, 126, 234, 0.1)' : 'transparent',
        color: active ? '#667eea' : 'var(--text)',
        fontWeight: active ? 500 : 400,
        fontSize: '14px',
        transition: 'all 0.2s',
      }}
    >
      <span style={{ fontSize: '16px' }}>{icon}</span>
      <span>{label}</span>
    </div>
  );
}

// 资源监控卡片
function ResourceMonitor({ systemInfo }: { systemInfo: SystemInfo }) {
  const memUsage = systemInfo.memory_total_gb > 0
    ? (systemInfo.memory_used_gb / systemInfo.memory_total_gb * 100).toFixed(1)
    : '0.0';
  const gpuUsage = systemInfo.gpu_total_gb > 0
    ? (systemInfo.gpu_used_gb / systemInfo.gpu_total_gb * 100).toFixed(1)
    : '0.0';

  return (
    <div style={{
      backgroundColor: '#fff',
      borderRadius: '12px',
      padding: '16px 20px',
      display: 'flex',
      gap: '40px',
      boxShadow: 'var(--shadow)',
    }}>
      <div>
        <div style={{ fontSize: '12px', color: 'var(--text-dim)', marginBottom: '4px' }}>
          内存
        </div>
        <div style={{ fontSize: '14px' }}>
          {systemInfo.memory_used_gb.toFixed(1)} / {systemInfo.memory_total_gb.toFixed(1)} GB
        </div>
        <div style={{
          height: '4px',
          backgroundColor: '#eee',
          borderRadius: '2px',
          marginTop: '6px',
          overflow: 'hidden',
        }}>
          <div style={{
            width: `${memUsage}%`,
            height: '100%',
            backgroundColor: '#667eea',
            borderRadius: '2px',
            transition: 'width 0.3s',
          }} />
        </div>
      </div>
      <div>
        <div style={{ fontSize: '12px', color: 'var(--text-dim)', marginBottom: '4px' }}>
          GPU
        </div>
        <div style={{ fontSize: '14px' }}>
          {systemInfo.gpu_used_gb.toFixed(1)} / {systemInfo.gpu_total_gb.toFixed(1)} GB ({gpuUsage}%)
        </div>
        <div style={{
          height: '4px',
          backgroundColor: '#eee',
          borderRadius: '2px',
          marginTop: '6px',
          overflow: 'hidden',
        }}>
          <div style={{
            width: `${gpuUsage}%`,
            height: '100%',
            backgroundColor: '#52c41a',
            borderRadius: '2px',
            transition: 'width 0.3s',
          }} />
        </div>
      </div>
    </div>
  );
}

// 主应用组件
export default function App() {
  const [activeTab, setActiveTab] = useState<TabId>('home');
  const [systemInfo, setSystemInfo] = useState<SystemInfo>({
    memory_used_gb: 0,
    memory_total_gb: 0,
    gpu_used_gb: 0,
    gpu_total_gb: 0,
    gpu_utilization: 0,
  });

  // 自动启动后端（双击主程序即用）
  useEffect(() => {
    const autoStartBackend = async () => {
      try {
        const healthy = await checkBackendHealth();
        if (!healthy) {
          await startBackend();
        }
      } catch (error) {
        console.error('自动启动后端失败:', error);
      }
    };
    autoStartBackend();
  }, []);

  // 获取系统信息
  useEffect(() => {
    const fetchSystemInfo = async () => {
      try {
        const info = await getSystemInfo();
        setSystemInfo(info);
      } catch (error) {
        console.error('获取系统信息失败:', error);
      }
    };

    fetchSystemInfo();
    // 每 5 秒刷新一次系统信息
    const interval = setInterval(fetchSystemInfo, 5000);
    return () => clearInterval(interval);
  }, []);

  // 处理视频上传
  const handleVideoUploaded = useCallback(
    (filePath: string) => {
      console.log('Video uploaded:', filePath);
    },
    [],
  );

  return (
    <div className="app">
      {/* 侧边栏 */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <div style={{ fontSize: '18px', fontWeight: 600 }}>SubAI</div>
        </div>
        <nav className="sidebar-nav">
          <NavItem id="home" label="主页" icon="🏠" active={activeTab === 'home'} onClick={setActiveTab} />
          <NavItem id="tasks" label="任务列表" icon="📋" active={activeTab === 'tasks'} onClick={setActiveTab} />
          <NavItem id="terms" label="术语库" icon="📚" active={activeTab === 'terms'} onClick={setActiveTab} />
          <NavItem id="settings" label="设置" icon="⚙️" active={activeTab === 'settings'} onClick={setActiveTab} />
          <NavItem id="help" label="帮助" icon="❓" active={activeTab === 'help'} onClick={setActiveTab} />
        </nav>
      </aside>

      {/* 主内容 */}
      <main className="main">
        {activeTab === 'home' && (
          <>
            <div className="page-head">
              <h1>AI 视频字幕翻译</h1>
              <div className="sub">上传视频，自动识别字幕并翻译</div>
              <div>
                <button
                  className="btn"
                  onClick={async () => {
                    try {
                      const message = await startBackend();
                      alert(message);
                    } catch (error) {
                      console.error('启动后端失败:', error);
                      alert('启动后端失败: ' + error);
                    }
                  }}
                  style={{
                    backgroundColor: '#ff9800',
                  }}
                >
                  启动后端
                </button>
              </div>
            </div>

            {/* 资源监控 */}
            <ResourceMonitor systemInfo={systemInfo} />

            {/* 视频上传 */}
            <VideoUpload onUploadComplete={handleVideoUploaded} />

            {/* 翻译任务进度 */}
            <TaskProgress />

            {/* 字幕编辑器 */}
            <SubtitleEditor />
          </>
        )}
        {activeTab === 'tasks' && <TasksPage />}
        {activeTab === 'terms' && (
          <div>
            <div className="page-head">
              <h1>术语库</h1>
              <div className="sub">管理专业术语提升翻译质量</div>
            </div>
            <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text-dim)' }}>
              术语库功能开发中...
            </div>
          </div>
        )}
        {activeTab === 'settings' && <SettingsPage />}
        {activeTab === 'help' && <HelpPage />}
      </main>
    </div>
  );
}