import { useCallback, useEffect, useState } from 'react';
import { getPluginMarketplace, listPlugins, probePlugin, reloadPlugins, setPluginEnabled } from '../api';
import type { PluginInfo, PluginMarketplaceEntry, PluginStats } from '../types';

const KIND_LABEL: Record<string, string> = { translator: '翻译', ocr: 'OCR', tts: '配音' };
const STATE_LABEL: Record<string, string> = { enabled: '已启用', pending: '待加载', disabled: '已停用', error: '异常' };
const STATE_COLOR: Record<string, string> = { enabled: '#2e7d32', pending: '#ef6c00', disabled: '#757575', error: '#c62828' };
const FILTERS = [
  { v: '', t: '全部' },
  { v: 'translator', t: '翻译' },
  { v: 'ocr', t: 'OCR' },
  { v: 'tts', t: '配音' },
];

export function PluginsPage() {
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [stats, setStats] = useState<PluginStats | null>(null);
  const [kind, setKind] = useState('');
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState('');
  const [entries, setEntries] = useState<PluginMarketplaceEntry[]>([]);
  const [query, setQuery] = useState('');

  const load = useCallback(async () => {
    try {
      const data = await listPlugins(true);
      setPlugins(data.plugins);
      setStats(data.stats);
    } catch (e: any) {
      setMsg('读取插件列表失败：' + (e?.response?.data?.detail || e?.message || '未知错误'));
    }
  }, []);

  const loadMarket = useCallback(async (q: string) => {
    try {
      const data = await getPluginMarketplace(q || undefined);
      setEntries(data.entries);
    } catch {
      setEntries([]);
    }
  }, []);

  useEffect(() => {
    void load();
    void loadMarket('');
  }, [load, loadMarket]);

  const toggle = async (p: PluginInfo) => {
    setBusy(p.id);
    setMsg('');
    try {
      await setPluginEnabled(p.id, !p.enabled);
      await load();
    } catch (e: any) {
      setMsg('操作失败：' + (e?.response?.data?.detail || e?.message || '未知错误'));
    } finally {
      setBusy('');
    }
  };

  const probe = async (p: PluginInfo) => {
    setBusy(p.id);
    setMsg('');
    try {
      const r = await probePlugin(p.id);
      if (r?.error) setMsg(p.name + ' 探测失败：' + r.error);
      else if (r?.result) setMsg(p.name + ' 探测正常：' + JSON.stringify(r.result));
      else setMsg(p.name + ' 不支持探测');
    } catch (e: any) {
      setMsg('探测请求失败：' + (e?.response?.data?.detail || e?.message || '未知错误'));
    } finally {
      setBusy('');
    }
  };

  const doReload = async () => {
    setBusy('__reload__');
    setMsg('');
    try {
      const r = await reloadPlugins();
      setMsg('已重新扫描，发现 ' + r.discovered + ' 个插件');
      await load();
    } catch (e: any) {
      setMsg('重新扫描失败：' + (e?.response?.data?.detail || e?.message || '未知错误'));
    } finally {
      setBusy('');
    }
  };

  const shown = kind ? plugins.filter((p) => p.kind === kind) : plugins;

  return (
    <div style={{ padding: '16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>插件</h2>
        {stats && (
          <span style={{ fontSize: '13px', color: '#555' }}>
            共 {stats.total} 个 / 已启用 {stats.enabled} 个 / 异常 {stats.errors} 个
          </span>
        )}
        <button className="btn" onClick={() => void doReload()} disabled={busy === '__reload__'}>
          {'重新扫描'}
        </button>
      </div>

      <div style={{ margin: '12px 0', display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
        {FILTERS.map((item) => (
          <button
            key={item.v || 'all'}
            className="btn"
            style={{ opacity: kind === item.v ? 1 : 0.6 }}
            onClick={() => setKind(item.v)}
          >
            {item.t}
          </button>
        ))}
      </div>

      {msg && <div style={{ margin: '8px 0', fontSize: '13px', color: '#1565c0', wordBreak: 'break-all' }}>{msg}</div>}

      <div style={{ display: 'grid', gap: '10px' }}>
        {shown.map((p) => (
          <div key={p.id} style={{ border: '1px solid #e0e0e0', borderRadius: '8px', padding: '12px', background: p.error ? '#fff5f5' : '#fff' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
              <strong>{p.name}</strong>
              <span className="badge">{KIND_LABEL[p.kind] || p.kind || '未知'}</span>
              <span className="badge" style={{ color: STATE_COLOR[p.state] || '#555' }}>{STATE_LABEL[p.state] || p.state}</span>
              <span style={{ fontSize: '12px', color: '#777' }}>
                {'v' + p.version + ' · ' + p.id + (p.builtin ? ' · 内置' : ' · 外部') + (p.available === false ? ' · 当前不可用' : '')}
              </span>
              <span style={{ flex: 1 }} />
              {p.capabilities?.includes('probe') && (
                <button className="btn" onClick={() => void probe(p)} disabled={busy === p.id || !p.enabled}>探测</button>
              )}
              <button className="btn" onClick={() => void toggle(p)} disabled={busy === p.id}>{p.enabled ? '停用' : '启用'}</button>
            </div>
            {p.description && <div style={{ marginTop: '6px', fontSize: '13px', color: '#555' }}>{p.description}</div>}
            {p.error && <div style={{ marginTop: '6px', fontSize: '13px', color: '#c62828' }}>{'错误：' + p.error}</div>}
          </div>
        ))}
        {shown.length === 0 && <div style={{ color: '#777', fontSize: '13px' }}>没有匹配的插件</div>}
      </div>

      <h3 style={{ marginTop: '24px' }}>插件目录</h3>
      <div style={{ display: 'flex', gap: '8px', marginBottom: '10px' }}>
        <input
          value={query}
          placeholder="搜索插件（名称 / 说明）"
          onChange={(e) => setQuery(e.target.value)}
          style={{ padding: '6px 8px', minWidth: '240px' }}
        />
        <button className="btn" onClick={() => void loadMarket(query)}>搜索</button>
      </div>
      <div style={{ display: 'grid', gap: '8px' }}>
        {entries.map((e) => (
          <div key={e.id} style={{ border: '1px solid #eee', borderRadius: '6px', padding: '10px' }}>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
              <strong>{e.name}</strong>
              <span className="badge">{KIND_LABEL[e.kind] || e.kind}</span>
              <span style={{ fontSize: '12px', color: '#777' }}>{'v' + e.version + ' · ' + e.author + (e.installed ? ' · 已安装' : ' · 未安装')}</span>
            </div>
            {e.description && <div style={{ marginTop: '4px', fontSize: '13px', color: '#555' }}>{e.description}</div>}
          </div>
        ))}
        {entries.length === 0 && <div style={{ color: '#777', fontSize: '13px' }}>目录为空（本地索引，远端安装/更新尚未实现）</div>}
      </div>
    </div>
  );
}
