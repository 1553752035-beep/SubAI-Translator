import { useCallback, useEffect, useRef, useState } from 'react';
import {
  addTerminology,
  deleteTerminology,
  getTerminologyList,
  importTerminology,
} from '../api';
import type { TerminologyRecord } from '../types';

const PRIORITY_LABEL: Record<string, string> = { high: '高', medium: '中', low: '低' };

export function TerminologyManager() {
  const [terms, setTerms] = useState<TerminologyRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [keyword, setKeyword] = useState('');
  const [showAddModal, setShowAddModal] = useState(false);
  const [newTerm, setNewTerm] = useState<{
    source_text: string;
    translation: string;
    category: string;
    priority: 'high' | 'medium' | 'low';
  }>({ source_text: '', translation: '', category: 'custom', priority: 'medium' });
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await getTerminologyList({ limit: 500 });
      setTerms(data.terms);
    } catch (err: any) {
      setError(
        err?.response?.status === 401
          ? '登录已过期，请重新登录'
          : '加载术语库失败，请确认后端服务已启动',
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleAddTerm = async () => {
    if (!newTerm.source_text.trim() || !newTerm.translation.trim()) {
      alert('请填写完整的术语信息');
      return;
    }
    try {
      await addTerminology({
        source_text: newTerm.source_text.trim(),
        translation: newTerm.translation.trim(),
        priority: newTerm.priority,
        category: newTerm.category.trim() || 'custom',
      });
      setNewTerm({ source_text: '', translation: '', category: 'custom', priority: 'medium' });
      setShowAddModal(false);
      await load();
    } catch (err: any) {
      alert(err?.response?.data?.detail || '添加失败');
    }
  };

  const handleDeleteTerm = async (source: string) => {
    if (!confirm('确定要删除术语「' + source + '」吗？')) return;
    try {
      await deleteTerminology(source);
      await load();
    } catch (err: any) {
      alert(err?.response?.data?.detail || '删除失败');
    }
  };

  const handleExport = (format: 'json' | 'csv') => {
    let content: string;
    let filename: string;

    if (format === 'json') {
      content = JSON.stringify(
        terms.map((t) => ({
          source: t.source,
          translation: t.translation,
          priority: t.priority,
          category: t.category,
        })),
        null,
        2,
      );
      filename = 'terminology.json';
    } else {
      const rows = terms.map((t) => [t.source, t.translation, t.category, t.priority].join(','));
      content = '源术语,目标术语,分类,优先级\n' + rows.join('\n');
      filename = 'terminology.csv';
    }

    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  };

  const handleImport = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const result = await importTerminology(file);
      alert(result?.message || '导入完成');
      await load();
    } catch {
      alert('导入失败，请确认文件为合法 JSON 数组');
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const visible = keyword.trim()
    ? terms.filter((t) => t.source.includes(keyword.trim()) || t.translation.includes(keyword.trim()))
    : terms;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* 工具栏 */}
      <div style={{ display: 'flex', gap: '12px', marginBottom: '16px', alignItems: 'center' }}>
        <button className="btn primary" onClick={() => setShowAddModal(true)}>
          + 添加术语
        </button>
        <button className="btn" onClick={() => handleExport('json')}>导出 JSON</button>
        <button className="btn" onClick={() => handleExport('csv')}>导出 CSV</button>
        <label className="btn" style={{ cursor: 'pointer' }}>
          导入
          <input
            ref={fileInputRef}
            type="file"
            accept=".json,application/json"
            style={{ display: 'none' }}
            onChange={handleImport}
          />
        </label>
        <input
          className="auth-input"
          style={{ marginLeft: 'auto', width: '220px' }}
          placeholder="搜索原文或译文…"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
      </div>

      {error && <div className="auth-error">{error}</div>}

      {/* 术语列表 */}
      <div className="table-card">
        <div className="table-head">
          <div className="t">术语库</div>
          <div className="cnt">
            {loading ? '加载中…' : '共 ' + visible.length + ' 条术语'}
          </div>
        </div>
        <table>
          <thead>
            <tr>
              <th style={{ width: '60px' }}>#</th>
              <th>源术语</th>
              <th>目标术语</th>
              <th style={{ width: '120px' }}>分类</th>
              <th style={{ width: '90px' }}>优先级</th>
              <th style={{ width: '90px' }}>使用次数</th>
              <th style={{ width: '80px' }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((term, index) => (
              <tr key={term.source + '|' + (term.user_id || 'system')}>
                <td className="idx">{index + 1}</td>
                <td className="src">{term.source}</td>
                <td className="tgt">{term.translation}</td>
                <td>{term.category}</td>
                <td>{PRIORITY_LABEL[term.priority] || term.priority}</td>
                <td>{term.usage_count ?? 0}</td>
                <td>
                  <button
                    className="btn"
                    style={{ padding: '4px 8px', fontSize: '11px' }}
                    onClick={() => handleDeleteTerm(term.source)}
                  >
                    删除
                  </button>
                </td>
              </tr>
            ))}
            {!loading && visible.length === 0 && (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', color: 'var(--text-dim)', padding: '32px 0' }}>
                  暂无术语
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* 添加术语模态框 */}
      {showAddModal && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.45)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
          onClick={() => setShowAddModal(false)}
        >
          <div
            style={{
              background: 'var(--bg)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              padding: '24px',
              width: '480px',
              maxWidth: '90vw',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ fontSize: '16px', marginBottom: '20px' }}>添加新术语</h3>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <label className="auth-label">源术语</label>
                <input
                  className="auth-input"
                  value={newTerm.source_text}
                  onChange={(e) => setNewTerm({ ...newTerm, source_text: e.target.value })}
                  placeholder="例如：API"
                />
              </div>

              <div>
                <label className="auth-label">目标术语</label>
                <input
                  className="auth-input"
                  value={newTerm.translation}
                  onChange={(e) => setNewTerm({ ...newTerm, translation: e.target.value })}
                  placeholder="例如：应用程序接口"
                />
              </div>

              <div>
                <label className="auth-label">分类</label>
                <input
                  className="auth-input"
                  value={newTerm.category}
                  onChange={(e) => setNewTerm({ ...newTerm, category: e.target.value })}
                  placeholder="例如：计算机"
                />
              </div>

              <div>
                <label className="auth-label">优先级</label>
                <select
                  className="auth-input"
                  value={newTerm.priority}
                  onChange={(e) =>
                    setNewTerm({ ...newTerm, priority: e.target.value as 'high' | 'medium' | 'low' })
                  }
                >
                  <option value="high">高</option>
                  <option value="medium">中</option>
                  <option value="low">低</option>
                </select>
              </div>
            </div>

            <div style={{ display: 'flex', gap: '12px', marginTop: '24px', justifyContent: 'flex-end' }}>
              <button className="btn" onClick={() => setShowAddModal(false)}>取消</button>
              <button className="btn primary" onClick={handleAddTerm}>添加</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
