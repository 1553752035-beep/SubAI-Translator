import { useState } from 'react';

interface Terminology {
  id: string;
  source: string;
  target: string;
  domain: string;
  createdAt: string;
}

export function TerminologyManager() {
  const [terminologyList, setTerminologyList] = useState<Terminology[]>([
    {
      id: '1',
      source: 'API',
      target: '应用程序接口',
      domain: '计算机',
      createdAt: '2026-09-15',
    },
    {
      id: '2',
      source: 'Machine Learning',
      target: '机器学习',
      domain: '人工智能',
      createdAt: '2026-09-16',
    },
    {
      id: '3',
      source: 'Neural Network',
      target: '神经网络',
      domain: '人工智能',
      createdAt: '2026-09-17',
    },
  ]);

  const [showAddModal, setShowAddModal] = useState(false);
  const [newTerm, setNewTerm] = useState<{ source: string; target: string; domain: string }>({
    source: '',
    target: '',
    domain: '',
  });

  const handleAddTerm = () => {
    if (!newTerm.source || !newTerm.target) {
      alert('请填写完整的术语信息');
      return;
    }

    const term: Terminology = {
      id: Date.now().toString(),
      source: newTerm.source,
      target: newTerm.target,
      domain: newTerm.domain || '通用',
      createdAt: new Date().toISOString().split('T')[0],
    };

    setTerminologyList([...terminologyList, term]);
    setNewTerm({ source: '', target: '', domain: '' });
    setShowAddModal(false);
  };

  const handleDeleteTerm = (id: string) => {
    if (confirm('确定要删除这个术语吗？')) {
      setTerminologyList(terminologyList.filter(t => t.id !== id));
    }
  };

  const handleExport = (format: 'json' | 'csv') => {
    let content: string;
    let filename: string;

    if (format === 'json') {
      content = JSON.stringify(terminologyList, null, 2);
      filename = 'terminology.json';
    } else {
      const csv = terminologyList
        .map(t => `${t.source},${t.target},${t.domain}`)
        .join('\n');
      content = `源术语,目标术语,领域\n${csv}`;
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

  const handleImport = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const content = e.target?.result as string;
        if (file.name.endsWith('.json')) {
          const imported = JSON.parse(content);
          setTerminologyList([...terminologyList, ...imported]);
        } else {
          alert('仅支持 JSON 格式文件');
        }
      } catch (error) {
        alert('导入失败，文件格式错误');
      }
    };
    reader.readAsText(file);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* 工具栏 */}
      <div style={{ display: 'flex', gap: '12px', marginBottom: '16px' }}>
        <button className="btn primary" onClick={() => setShowAddModal(true)}>
          + 添加术语
        </button>
        <button className="btn" onClick={() => handleExport('json')}>
          导出 JSON
        </button>
        <button className="btn" onClick={() => handleExport('csv')}>
          导出 CSV
        </button>
        <label className="btn" style={{ cursor: 'pointer' }}>
          导入
          <input
            type="file"
            accept=".json"
            style={{ display: 'none' }}
            onChange={handleImport}
          />
        </label>
      </div>

      {/* 术语列表 */}
      <div className="table-card">
        <div className="table-head">
          <div className="t">术语库</div>
          <div className="cnt">共 {terminologyList.length} 条术语</div>
        </div>
        <table>
          <thead>
            <tr>
              <th style={{ width: '60px' }}>#</th>
              <th>源术语</th>
              <th>目标术语</th>
              <th style={{ width: '120px' }}>领域</th>
              <th style={{ width: '120px' }}>添加日期</th>
              <th style={{ width: '80px' }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {terminologyList.map((term, index) => (
              <tr key={term.id}>
                <td className="idx">{index + 1}</td>
                <td className="src">{term.source}</td>
                <td className="tgt">{term.target}</td>
                <td>{term.domain}</td>
                <td className="time">{term.createdAt}</td>
                <td>
                  <button
                    className="btn"
                    style={{ padding: '4px 8px', fontSize: '11px' }}
                    onClick={() => handleDeleteTerm(term.id)}
                  >
                    删除
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 添加术语模态框 */}
      {showAddModal && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0,0,0,0.7)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
          onClick={() => setShowAddModal(false)}
        >
          <div
            style={{
              background: 'var(--panel)',
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
                <label style={{ fontSize: '12px', color: 'var(--text-dim)', display: 'block', marginBottom: '6px' }}>
                  源术语
                </label>
                <input
                  type="text"
                  value={newTerm.source}
                  onChange={(e) => setNewTerm({ ...newTerm, source: e.target.value })}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    background: 'var(--bg)',
                    border: '1px solid var(--border)',
                    borderRadius: '7px',
                    color: 'var(--text)',
                    fontSize: '13px',
                    outline: 'none',
                  }}
                  placeholder="例如：API"
                />
              </div>

              <div>
                <label style={{ fontSize: '12px', color: 'var(--text-dim)', display: 'block', marginBottom: '6px' }}>
                  目标术语
                </label>
                <input
                  type="text"
                  value={newTerm.target}
                  onChange={(e) => setNewTerm({ ...newTerm, target: e.target.value })}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    background: 'var(--bg)',
                    border: '1px solid var(--border)',
                    borderRadius: '7px',
                    color: 'var(--text)',
                    fontSize: '13px',
                    outline: 'none',
                  }}
                  placeholder="例如：应用程序接口"
                />
              </div>

              <div>
                <label style={{ fontSize: '12px', color: 'var(--text-dim)', display: 'block', marginBottom: '6px' }}>
                  领域
                </label>
                <input
                  type="text"
                  value={newTerm.domain}
                  onChange={(e) => setNewTerm({ ...newTerm, domain: e.target.value })}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    background: 'var(--bg)',
                    border: '1px solid var(--border)',
                    borderRadius: '7px',
                    color: 'var(--text)',
                    fontSize: '13px',
                    outline: 'none',
                  }}
                  placeholder="例如：计算机"
                />
              </div>
            </div>

            <div
              style={{
                display: 'flex',
                gap: '12px',
                marginTop: '24px',
                justifyContent: 'flex-end',
              }}
            >
              <button className="btn" onClick={() => setShowAddModal(false)}>
                取消
              </button>
              <button className="btn primary" onClick={handleAddTerm}>
                添加
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}