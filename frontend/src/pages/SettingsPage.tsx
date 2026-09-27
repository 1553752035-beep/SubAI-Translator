import { useState, useEffect } from 'react';
import { getAppConfig, updateAppConfig } from '../api/tauri';
import { reloadConfig } from '../api';

// 设置页
export function SettingsPage() {
  const [appConfig, setAppConfig] = useState<Record<string, any>>({});
  const [backendConfig, setBackendConfig] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  // 加载配置
  useEffect(() => {
    const loadConfigs = async () => {
      try {
        const [app, backend] = await Promise.all([
          getAppConfig(),
          reloadConfig(),
        ]);
        setAppConfig(app);
        setBackendConfig(backend);
      } catch (error) {
        console.error('加载配置失败:', error);
      } finally {
        setLoading(false);
      }
    };
    
    loadConfigs();
  }, []);

  // 保存配置
  const handleSave = async () => {
    setSaving(true);
    try {
      await updateAppConfig(appConfig);
      setMessage('配置已保存');
      setTimeout(() => setMessage(''), 3000);
    } catch (error) {
      console.error('保存配置失败:', error);
      setMessage('保存失败');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <>
        <div className="page-head">
          <h1>设置</h1>
          <div className="sub">配置应用参数和偏好设置</div>
        </div>
        <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text-dim)' }}>
          加载中...
        </div>
      </>
    );
  }

  return (
    <>
      <div className="page-head">
        <h1>设置</h1>
        <div className="sub">配置应用参数和偏好设置</div>
      </div>

      {/* 配置保存消息 */}
      {message && (
        <div style={{
          padding: '12px 16px',
          backgroundColor: message.includes('失败') ? '#ffebee' : '#e8f5e9',
          color: message.includes('失败') ? '#c62828' : '#2e7d32',
          borderRadius: '8px',
          marginBottom: '16px',
        }}>
          {message}
        </div>
      )}

      <div style={{ display: 'grid', gap: '24px' }}>
        {/* 后端服务配置 */}
        <div className="table-card">
          <div className="table-head">
            <div className="t">后端服务配置</div>
          </div>
          <div style={{ padding: '16px', lineHeight: '2.5' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <strong>后端地址</strong>
                <div style={{ fontSize: '14px', color: 'var(--text-dim)' }}>
                  {backendConfig?.backend_url || 'http://localhost:8000'}
                </div>
              </div>
              <div>
                <strong>状态</strong>
                <div style={{
                  marginTop: '4px',
                  padding: '4px 12px',
                  borderRadius: '12px',
                  backgroundColor: backendConfig?.running ? '#4caf50' : '#999',
                  color: '#fff',
                  fontSize: '12px',
                }}>
                  {backendConfig?.running ? '运行中' : '未运行'}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* 处理配置 */}
        <div className="table-card">
          <div className="table-head">
            <div className="t">处理配置</div>
          </div>
          <div style={{ padding: '16px', lineHeight: '2.5' }}>
            <div>
              <strong>最大并发数</strong>
              <div style={{ fontSize: '14px', color: 'var(--text-dim)' }}>
                {appConfig?.max_concurrent || 2}
              </div>
            </div>
            <div>
              <strong>默认输出格式</strong>
              <div style={{ fontSize: '14px', color: 'var(--text-dim)' }}>
                {(appConfig?.output_format || 'srt').toUpperCase()}
              </div>
            </div>
            <div>
              <strong>自动启动后端</strong>
              <div style={{ fontSize: '14px', color: 'var(--text-dim)' }}>
                {appConfig?.auto_start_backend ? '是' : '否'}
              </div>
            </div>
          </div>
        </div>

        {/* 保存按钮 */}
        <div style={{ textAlign: 'right' }}>
          <button
            className="btn primary"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? '保存中...' : '保存配置'}
          </button>
        </div>
      </div>
    </>
  );
}