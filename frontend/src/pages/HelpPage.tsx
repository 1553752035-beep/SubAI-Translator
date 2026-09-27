import { useState, useEffect } from 'react';
import { getHelpInfo } from '../api/tauri';

// 帮助页
export function HelpPage() {
  const [helpInfo, setHelpInfo] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadHelpInfo = async () => {
      try {
        const info = await getHelpInfo();
        setHelpInfo(info);
      } catch (error) {
        console.error('加载帮助信息失败:', error);
      } finally {
        setLoading(false);
      }
    };
    
    loadHelpInfo();
  }, []);

  if (loading) {
    return (
      <>
        <div className="page-head">
          <h1>使用帮助</h1>
          <div className="sub">了解如何使用 SubAI Translator</div>
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
        <h1>使用帮助</h1>
        <div className="sub">了解如何使用 SubAI Translator</div>
      </div>

      <div style={{ display: 'grid', gap: '24px' }}>
        {/* 版本信息 */}
        <div className="table-card">
          <div className="table-head">
            <div className="t">版本信息</div>
          </div>
          <div style={{ padding: '16px', lineHeight: '2' }}>
            <div><strong>应用版本:</strong> v{helpInfo?.version || '2.0.0'}</div>
            <div><strong>开发状态:</strong> 公测版</div>
            <div><strong>更新日期:</strong> 2026-09-19</div>
          </div>
        </div>

        {/* 核心功能 */}
        <div className="table-card">
          <div className="table-head">
            <div className="t">核心功能</div>
          </div>
          <div style={{ padding: '16px', lineHeight: '2' }}>
            <ul style={{ margin: 0, paddingLeft: '20px' }}>
              {helpInfo?.features?.map((feature: string, idx: number) => (
                <li key={idx}>{feature}</li>
              )) || (
                <>
                  <li>视频字幕识别 (ASR)</li>
                  <li>硬字幕 OCR 识别</li>
                  <li>多格式输出 (SRT/VTT/ASS/JSON)</li>
                  <li>术语库管理</li>
                  <li>实时进度显示</li>
                </>
              )}
            </ul>
          </div>
        </div>

        {/* 快捷键 */}
        <div className="table-card">
          <div className="table-head">
            <div className="t">操作指南</div>
          </div>
          <div style={{ padding: '16px', lineHeight: '2' }}>
            <div>
              <strong>📤 上传视频</strong>
              <div style={{ fontSize: '14px', color: 'var(--text-dim)' }}>
                {helpInfo?.shortcuts?.upload || '拖拽视频文件到上传区域'}
              </div>
            </div>
            <div>
              <strong>▶️ 开始翻译</strong>
              <div style={{ fontSize: '14px', color: 'var(--text-dim)' }}>
                {helpInfo?.shortcuts?.start || '点击"开始翻译"按钮'}
              </div>
            </div>
            <div>
              <strong>⏹️ 取消任务</strong>
              <div style={{ fontSize: '14px', color: 'var(--text-dim)' }}>
                {helpInfo?.shortcuts?.cancel || '点击"取消"按钮'}
              </div>
            </div>
          </div>
        </div>

        {/* 常见问题 */}
        <div className="table-card">
          <div className="table-head">
            <div className="t">常见问题</div>
          </div>
          <div style={{ padding: '16px', lineHeight: '2' }}>
            <details>
              <summary style={{ cursor: 'pointer', fontWeight: '500' }}>
                后端服务无法启动怎么办？
              </summary>
              <div style={{ marginTop: '8px', paddingLeft: '16px', color: 'var(--text-dim)' }}>
                <p>1. 确认 Python 环境已正确安装</p>
                <p>2. 检查端口 8000 是否被占用</p>
                <p>3. 查看应用日志获取详细信息</p>
              </div>
            </details>
            <details style={{ marginTop: '12px' }}>
              <summary style={{ cursor: 'pointer', fontWeight: '500' }}>
                翻译质量不佳如何改善？
              </summary>
              <div style={{ marginTop: '8px', paddingLeft: '16px', color: 'var(--text-dim)' }}>
                <p>1. 添加专业术语库提升术语翻译</p>
                <p>2. 尝试切换云端 API 模式</p>
                <p>3. 手动编辑字幕调整译文</p>
              </div>
            </details>
            <details style={{ marginTop: '12px' }}>
              <summary style={{ cursor: 'pointer', fontWeight: '500' }}>
                GPU 未使用如何处理？
              </summary>
              <div style={{ marginTop: '8px', paddingLeft: '16px', color: 'var(--text-dim)' }}>
                <p>1. 确认已安装 NVIDIA 驱动</p>
                <p>2. 检查 CUDA 版本是否兼容</p>
                <p>3. 在设置中手动选择 GPU 设备</p>
              </div>
            </details>
          </div>
        </div>

        {/* 技术支持 */}
        <div className="table-card">
          <div className="table-head">
            <div className="t">技术支持</div>
          </div>
          <div style={{ padding: '16px', lineHeight: '2' }}>
            <div><strong>问题反馈:</strong> 通过应用内反馈功能提交</div>
            <div><strong>文档地址:</strong> https://docs.subai.translator</div>
            <div><strong>社区论坛:</strong> https://community.subai.translator</div>
          </div>
        </div>
      </div>
    </>
  );
}