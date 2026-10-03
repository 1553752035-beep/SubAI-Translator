import { useState, useEffect, useRef } from 'react';
import { deleteTasks, purgeTask, cancelTask, getHistory } from '../api';
import { MediaTools } from '../components/MediaTools';
import { SubtitleEditor } from '../components/SubtitleEditor';
import type { TaskRecord } from '../types';

// 任务状态徽章
function StatusBadge({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    pending: '#ff9800',
    processing: '#2196f3',
    completed: '#4caf50',
    failed: '#f44336',
  };
  
  const textMap: Record<string, string> = {
    pending: '等待中',
    processing: '处理中',
    completed: '已完成',
    failed: '失败',
  };
  
  return (
    <span style={{
      display: 'inline-block',
      padding: '4px 12px',
      borderRadius: '12px',
      backgroundColor: colorMap[status] || '#999',
      color: '#fff',
      fontSize: '12px',
      fontWeight: '500',
    }}>
      {textMap[status] || status}
    </span>
  );
}

// 任务详情弹窗
function TaskDetail({ task, onClose }: { task: TaskRecord; onClose: () => void }) {
  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      backgroundColor: 'rgba(0,0,0,0.5)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1000,
    }} onClick={onClose}>
      <div style={{
        backgroundColor: 'var(--bg)',
        border: '1px solid var(--border)',
        borderRadius: '12px',
        padding: '24px',
        maxWidth: '1100px',
        width: '94%',
        maxHeight: '88vh',
        overflow: 'auto',
      }} onClick={e => e.stopPropagation()}>
        <h3 style={{ marginTop: 0 }}>任务详情</h3>
        <div style={{ lineHeight: '2' }}>
          <div><strong>任务 ID:</strong> {task.task_id}</div>
          <div><strong>视频路径:</strong> {task.video_path}</div>
          <div><strong>模式:</strong> {task.mode}</div>
          <div><strong>源语言:</strong> {task.source_lang || '自动'}</div>
          <div><strong>目标语言:</strong> {task.target_lang}</div>
          <div><strong>输出格式:</strong> {task.output_format}</div>
          <div><strong>状态:</strong> <StatusBadge status={task.status} /></div>
          <div><strong>进度:</strong> {Math.round(task.progress * 100)}%</div>
          <div><strong>消息:</strong> {task.message}</div>
          <div><strong>创建时间:</strong> {new Date(task.created_at).toLocaleString()}</div>
          <div><strong>更新时间:</strong> {new Date(task.updated_at).toLocaleString()}</div>
          {task.completed_at && (
            <div><strong>完成时间:</strong> {new Date(task.completed_at).toLocaleString()}</div>
          )}
          {task.error_message && (
            <div style={{ color: '#f44336' }}>
              <strong>错误信息:</strong> {task.error_message}
            </div>
          )}
          {task.result_files && task.result_files.length > 0 && (
            <div>
              <strong>输出文件:</strong>
              <ul style={{ margin: '8px 0', paddingLeft: '20px' }}>
                {task.result_files.map((file, idx) => (
                  <li key={idx}>{file}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
        <div style={{ marginTop: '18px', borderTop: '1px solid var(--border)', paddingTop: '14px' }}>
          <h4 style={{ margin: '0 0 10px', fontSize: '14px' }}>字幕内容</h4>
          {task.status === 'completed' ? (
            <SubtitleEditor taskId={task.task_id} />
          ) : (
            <div style={{ color: 'var(--text-dim)', fontSize: '13px' }}>
              任务完成后可在此查看与编辑字幕（当前状态：{task.status}）。
            </div>
          )}
        </div>
        {task.status === 'completed' && (
          <div style={{ marginTop: '18px', borderTop: '1px solid var(--border)', paddingTop: '14px' }}>
            <h4 style={{ margin: '0 0 10px', fontSize: '14px' }}>视频与配音</h4>
            <MediaTools task={task} />
          </div>
        )}
        <div style={{ textAlign: 'right' }}>
          <button className="btn" onClick={onClose} style={{ marginTop: '16px' }}>关闭</button>
        </div>
      </div>
    </div>
  );
}

// 任务列表页
export function TasksPage() {
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedTask, setSelectedTask] = useState<TaskRecord | null>(null);
  const [filterStatus, setFilterStatus] = useState<string>('');
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [dragFrom, setDragFrom] = useState<{ x: number; y: number } | null>(null);
  const [marquee, setMarquee] = useState<{ x1: number; y1: number; x2: number; y2: number } | null>(null);
  const tableRef = useRef<HTMLDivElement | null>(null);
  const [showTrash, setShowTrash] = useState(false);

  // 加载历史记录
  useEffect(() => {
    const loadTasks = async () => {
      try {
        const data = await getHistory({ limit: 100 });
        setTasks(data.tasks);
      } catch (error) {
        console.error('加载任务列表失败:', error);
      } finally {
        setLoading(false);
      }
    };
    
    loadTasks();
  }, []);

  // 静默轮询，让进行中的任务状态自动更新
  useEffect(() => {
    const timer = setInterval(() => {
      void (async () => {
        try {
          const data = await getHistory({ limit: 100 });
          setTasks(data.tasks);
        } catch {
          /* 忽略瞬时失败 */
        }
      })();
    }, 5000);
    return () => clearInterval(timer);
  }, []);

  // 取消排队/处理中的任务
  const handleCancel = async (taskId: string) => {
    try {
      await cancelTask(taskId);
      await handleRefresh();
    } catch (error) {
      console.error('取消失败:', error);
    }
  };

  // 刷新任务列表
  const handleRefresh = async () => {
    setLoading(true);
    try {
      const data = await getHistory({ limit: 100 });
      setTasks(data.tasks);
    } catch (error) {
      console.error('刷新任务列表失败:', error);
    } finally {
      setLoading(false);
    }
  };

  // 五期：删除（后端为归档，可在「回收站」查看）；只刷新列表，不整页跳回首页
  const handleDelete = async (taskId: string) => {
    const isTrash = showTrash;
    if (!window.confirm(isTrash ? '彻底删除这个任务？\n\n会一起删掉：本任务产出的视频与字幕文件。\n（你自己「视频」文件夹里的源视频不会被删）' : '确定删除这个任务？删除后可在「回收站」查看。')) return;
    try { if (isTrash) { await purgeTask(taskId); } else { await deleteTasks([taskId]); } await handleRefresh(); }
    catch (error: any) { const d = error?.response?.data?.detail || error?.message || String(error); console.error('删除失败:', error); window.alert('删除失败：' + d); }
  };

  // 五期：批量删除选中的任务
  const handleDeleteSelected = async () => {
    if (selectedIds.length === 0) return;
    if (!window.confirm('确定删除选中的 ' + selectedIds.length + ' 个任务？')) return;
    try {
      const res = await deleteTasks(selectedIds);
      setSelectedIds((res.failed || []).map((f) => f.task_id));
      await handleRefresh();
      if ((res.failed || []).length) window.alert('已删除 ' + res.ok + ' 个，' + res.failed.length + ' 个失败（已保留勾选，可重试）');
      setSelectedIds([]);
      await handleRefresh();
    } catch (error: any) { const d = error?.response?.data?.detail || error?.message || String(error); console.error('删除失败:', error); window.alert('删除失败：' + d); }
  };

  // 过滤任务
  // 五期：删除=归档，默认不出现在列表里（进「回收站」才看到）
  const baseTasks = showTrash
    ? tasks.filter((t) => t.status === 'archived' || t.status === 'cancelled')
    : tasks.filter((t) => t.status !== 'archived' && t.status !== 'cancelled');
  const filteredTasks = filterStatus ? baseTasks.filter((t) => t.status === filterStatus) : baseTasks;

  return (
    <>
      <div className="page-head">
        <h1>任务列表</h1>
        <div className="sub">查看和管理所有翻译任务</div>
        <div>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button className="btn" onClick={() => { setShowTrash(!showTrash); setSelectedIds([]); }}>{showTrash ? '← 返回任务列表' : '回收站'}</button>
          <button className="btn" disabled={selectedIds.length === 0} onClick={() => void handleDeleteSelected()}>删除选中（{selectedIds.length}）</button>
          <button className="btn" onClick={handleRefresh}>刷新</button>
        </div>
        </div>
      </div>

      {/* 过滤选项 */}
      <div style={{
        marginBottom: '16px',
        display: 'flex',
        gap: '8px',
        alignItems: 'center',
      }}>
        <span>过滤:</span>
        <button
          className={`btn ${!filterStatus ? 'primary' : ''}`}
          onClick={() => setFilterStatus('')}
        >
          全部
        </button>
        <button
          className={`btn ${filterStatus === 'pending' ? 'primary' : ''}`}
          onClick={() => setFilterStatus('pending')}
        >
          等待中
        </button>
        <button
          className={`btn ${filterStatus === 'processing' ? 'primary' : ''}`}
          onClick={() => setFilterStatus('processing')}
        >
          处理中
        </button>
        <button
          className={`btn ${filterStatus === 'completed' ? 'primary' : ''}`}
          onClick={() => setFilterStatus('completed')}
        >
          已完成
        </button>
        <button
          className={`btn ${filterStatus === 'failed' ? 'primary' : ''}`}
          onClick={() => setFilterStatus('failed')}
        >
          失败
        </button>
      </div>

      {/* 任务表格 */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text-dim)' }}>
          加载中...
        </div>
      ) : filteredTasks.length === 0 ? (
        <div style={{
          textAlign: 'center',
          padding: '60px 0',
          color: 'var(--text-dim)',
          backgroundColor: 'var(--panel)',
          borderRadius: '12px',
        }}>
          暂无任务记录
        </div>
      ) : (
        <div
          className="table-card"
          ref={tableRef}
          style={{ maxHeight: '62vh', overflowY: 'auto', overflowX: 'auto', position: 'relative' }}
          onMouseDown={(e) => {
            const el = e.target as HTMLElement;
            if (el.closest('button') || el.closest('input') || el.closest('a')) return;
            const box = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
            setDragFrom({ x: e.clientX - box.left + (e.currentTarget as HTMLDivElement).scrollLeft, y: e.clientY - box.top + (e.currentTarget as HTMLDivElement).scrollTop });
            setMarquee(null);
          }}
          onMouseMove={(e) => {
            if (!dragFrom) return;
            const box = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
            setMarquee({ x1: dragFrom.x, y1: dragFrom.y, x2: e.clientX - box.left + (e.currentTarget as HTMLDivElement).scrollLeft, y2: e.clientY - box.top + (e.currentTarget as HTMLDivElement).scrollTop });
          }}
          onMouseUp={() => {
            if (marquee && tableRef.current) {
              const r = { l: Math.min(marquee.x1, marquee.x2), t: Math.min(marquee.y1, marquee.y2), rr: Math.max(marquee.x1, marquee.x2), b: Math.max(marquee.y1, marquee.y2) };
              if (r.rr - r.l > 6 && r.b - r.t > 6) {
                const hit: string[] = [];
                tableRef.current.querySelectorAll('tr[data-id]').forEach((row) => {
                  const rb = (row as HTMLElement).getBoundingClientRect();
                  const cb = tableRef.current!.getBoundingClientRect();
                  const y1 = rb.top - cb.top + tableRef.current!.scrollTop;
                  const y2 = rb.bottom - cb.top + tableRef.current!.scrollTop;
                  if (y2 >= r.t && y1 <= r.b) { const id = (row as HTMLElement).getAttribute('data-id'); if (id) hit.push(id); }
                });
                if (hit.length) setSelectedIds((prev) => Array.from(new Set([...prev, ...hit])));
              }
            }
            setDragFrom(null);
            setMarquee(null);
          }}
          onMouseLeave={() => { setDragFrom(null); setMarquee(null); }}
        >
          {marquee && (
            <div style={{ position: 'absolute', left: Math.min(marquee.x1, marquee.x2), top: Math.min(marquee.y1, marquee.y2), width: Math.abs(marquee.x2 - marquee.x1), height: Math.abs(marquee.y2 - marquee.y1), border: '1px solid var(--accent, #5b4be0)', background: 'rgba(91,75,224,.12)', pointerEvents: 'none', zIndex: 5 }} />
          )}
          <table>
            <thead>
              <tr>
                <th style={{ width: '36px' }}>
                  <input type="checkbox" title="全选"
                    checked={filteredTasks.length > 0 && selectedIds.length === filteredTasks.length}
                    onChange={(e) => setSelectedIds(e.target.checked ? filteredTasks.map((t) => t.task_id) : [])} />
                </th>
                <th style={{ width: '120px' }}>任务 ID</th>
                <th>视频名称</th>
                <th style={{ width: '80px' }}>模式</th>
                <th style={{ width: '80px' }}>格式</th>
                <th style={{ width: '100px' }}>状态</th>
                <th style={{ width: '80px' }}>进度</th>
                <th style={{ width: '160px' }}>创建时间</th>
                <th style={{ width: '100px' }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {filteredTasks.map((task) => (
                <tr key={task.task_id} data-id={task.task_id}>
                  <td>
                    <input type="checkbox" checked={selectedIds.includes(task.task_id)}
                      onChange={(e) => setSelectedIds(e.target.checked ? [...selectedIds, task.task_id] : selectedIds.filter((x) => x !== task.task_id))} />
                  </td>
                  <td className="idx">{task.task_id}</td>
                  <td>{task.video_path.split('\\').pop() || task.video_path}</td>
                  <td>{task.mode}</td>
                  <td>{task.output_format.toUpperCase()}</td>
                  <td><StatusBadge status={task.status} /></td>
                  <td>{Math.round(task.progress * 100)}%</td>
                  <td>{new Date(task.created_at).toLocaleDateString()}</td>
                  <td>
                    <div className="row-actions">
                      <button className="btn" onClick={() => setSelectedTask(task)}>详情 / 字幕</button>
                      {(task.status === 'pending' || task.status === 'processing') && (
                        <button className="btn" onClick={() => void handleCancel(task.task_id)}>取消</button>
                      )}
                      <button className="btn" onClick={() => void handleDelete(task.task_id)}>删除</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 任务详情弹窗 */}
      {selectedTask && (
        <TaskDetail task={selectedTask} onClose={() => setSelectedTask(null)} />
      )}
    </>
  );
}