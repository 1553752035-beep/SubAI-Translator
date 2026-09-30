import { useCallback, useEffect, useState } from 'react';
import {
  changePassword,
  checkHealth,
  clearCache,
  getAsrDevice,
  getCacheStats,
  getCurrentUser,
  getLlmStatus,
  getQueueStats,
  setLlmMode,
  testLlm,
} from '../api';
import type { AsrDeviceInfo, CacheStats, LlmStatus, QueueStats, UserInfo } from '../types';

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="set-row">
      <span className="k">{label}</span>
      <span className="v">{value}</span>
    </div>
  );
}

export function SettingsPage() {
  const [me, setMe] = useState<UserInfo | null>(null);
  const [health, setHealth] = useState<any>(null);
  const [asr, setAsr] = useState<AsrDeviceInfo | null>(null);
  const [llm, setLlm] = useState<LlmStatus | null>(null);
  const [cache, setCache] = useState<CacheStats | null>(null);
  const [queue, setQueue] = useState<QueueStats | null>(null);
  const [adminNote, setAdminNote] = useState('');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<any>(null);

  const [cloudUrl, setCloudUrl] = useState('');
  const [cloudModel, setCloudModel] = useState('');
  const [cloudKey, setCloudKey] = useState('');
  const [oldPw, setOldPw] = useState('');
  const [newPw, setNewPw] = useState('');

  const load = useCallback(async () => {
    setMsg('');
    try { setMe(await getCurrentUser()); } catch { /* 忽略 */ }
    try { setHealth(await checkHealth()); } catch { setHealth(null); }
    try { setAsr(await getAsrDevice()); } catch { setAsr(null); }
    try {
      const s = await getLlmStatus();
      setLlm(s);
      setCloudUrl(s.cloud.url || '');
      setCloudModel(s.cloud.model || '');
    } catch { setLlm(null); }
    try {
      setCache(await getCacheStats());
      setQueue(await getQueueStats());
      setAdminNote('');
    } catch {
      setCache(null);
      setQueue(null);
      setAdminNote('缓存 / 队列统计需要管理员权限');
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const switchMode = async (mode: string) => {
    setBusy(true);
    setMsg('');
    try {
      const s = await setLlmMode(mode, {
        cloud_url: cloudUrl || undefined,
        cloud_model: cloudModel || undefined,
        cloud_api_key: cloudKey || undefined,
      });
      setLlm(s);
      setCloudKey('');
      setMsg('已切换到 ' + mode);
    } catch (err: any) {
      const detail = err && err.response ? err.response.data.detail : null;
      setMsg(typeof detail === 'string' ? detail : '切换失败');
    } finally {
      setBusy(false);
    }
  };

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      setTestResult(await testLlm(llm ? llm.mode : undefined));
    } catch (err: any) {
      const detail = err && err.response ? err.response.data.detail : null;
      setTestResult({ reachable: false, detail: typeof detail === 'string' ? detail : '测试失败' });
    } finally {
      setTesting(false);
    }
  };

  const doClearCache = async () => {
    try { const r = await clearCache(); setMsg(r.message || '缓存已清空'); await load(); }
    catch { setMsg('清空缓存失败（需要管理员权限）'); }
  };

  const doChangePassword = async () => {
    if (newPw.length < 6) { setMsg('新密码至少 6 个字符'); return; }
    try {
      await changePassword(oldPw, newPw);
      setOldPw(''); setNewPw('');
      setMsg('密码已修改');
    } catch (err: any) {
      const detail = err && err.response ? err.response.data.detail : null;
      setMsg(typeof detail === 'string' ? detail : '修改密码失败');
    }
  };

  const qs = (health && health.queue_stats) || null;

  return (
    <>
      <div className="page-head">
        <h1>设置</h1>
        <div className="sub">以下信息全部来自后端实时状态（非本地占位）</div>
        <div><button className="btn" onClick={() => void load()}>刷新</button></div>
      </div>

      {msg && <div className="auth-msg info">{msg}</div>}

      <div style={{ display: 'grid', gap: '20px' }}>
        <div className="table-card">
          <div className="table-head"><div className="t">后端连接</div></div>
          <div className="set-body">
            <Row label="服务地址" value="http://localhost:8000" />
            <Row label="状态" value={health ? ('已连接 · ' + (health.status || 'ok')) : '未连接'} />
            <Row label="翻译模式(后端)" value={health ? String(health.llm_mode) : '-'} />
            <Row label="ASR 设备" value={health ? String(health.asr_device) : '-'} />
            <Row label="队列" value={qs ? (String(qs.running_count) + ' 运行 / ' + String(qs.queue_size) + ' 等待（上限 ' + String(qs.max_queue_size) + '）') : '-'} />
            <Row label="当前账号" value={me ? (me.username + ' / ' + me.role) : '-'} />
          </div>
        </div>

        <div className="table-card">
          <div className="table-head"><div className="t">语音识别设备（ASR）</div></div>
          <div className="set-body">
            <Row label="配置值" value={asr ? asr.configured : '-'} />
            <Row label="实际生效" value={asr ? (asr.effective_device + ' / ' + asr.compute_type) : '-'} />
            <Row label="CTranslate2 CUDA" value={asr ? (asr.ct2_cuda_supported ? '支持' : '不支持') : '-'} />
            <Row
              label="空闲显存"
              value={asr && asr.free_vram_gb != null ? (asr.free_vram_gb.toFixed(1) + ' GB') : '未知'}
            />
            <Row label="CUDA DLL 目录" value={asr ? (String(asr.cuda_dll_dirs.length) + ' 个') : '-'} />
            <div className="set-hint">
              判定规则：CTranslate2 支持 CUDA 且 能找到 CUDA DLL 且 空闲显存 ≥4GB，才会使用 GPU，否则安全回落 CPU。
              绿色版主包不含 CUDA 运行库（约 2.0 GB），可用 tools/build_gpu_pack.ps1 生成可选 GPU 包后放入安装目录。
            </div>
          </div>
        </div>

        <div className="table-card">
          <div className="table-head"><div className="t">翻译后端（AI 调用模式）</div></div>
          <div className="set-body">
            <Row label="当前模式" value={llm ? llm.mode : '-'} />
            <Row label="有效端点" value={llm ? (llm.effective.url || '未配置') : '-'} />
            <Row label="有效模型" value={llm ? (llm.effective.model || '-') : '-'} />
            <Row
              label="本地服务"
              value={llm ? (llm.local.reachable ? '可达' : '不可达（' + llm.local.detail + '）') : '-'}
            />
            <Row label="云端 Key" value={llm ? (llm.cloud.has_key ? '已配置' : '未配置') : '-'} />

            <div className="set-form">
              <input className="auth-input" placeholder="云端 API 地址（OpenAI 兼容）" value={cloudUrl} onChange={(e) => setCloudUrl(e.target.value)} />
              <input className="auth-input" placeholder="云端模型名（如 gpt-4o）" value={cloudModel} onChange={(e) => setCloudModel(e.target.value)} />
              <input className="auth-input" type="password" placeholder="云端 API Key（仅提交给后端，不回显）" value={cloudKey} onChange={(e) => setCloudKey(e.target.value)} />
            </div>
            <div className="set-actions">
              <button className="btn" disabled={busy} onClick={() => void switchMode('local')}>使用本地模型</button>
              <button className="btn" disabled={busy} onClick={() => void switchMode('cloud')}>使用云端 API</button>
              <button className="btn" disabled={busy} onClick={() => void switchMode('hybrid')}>混合模式</button>
              <button className="btn" disabled={testing} onClick={() => void runTest()}>
                {testing ? '测试中…' : '测试连接'}
              </button>
            </div>

            {testResult && (
              <div className={testResult.reachable ? 'auth-msg ok' : 'auth-msg error'}>
                {testResult.reachable
                  ? ('连接成功（方式：' + (testResult.method || '-') + '，' + String(testResult.elapsed_ms) + ' ms）—— ' + (testResult.url || ''))
                  : ('连接失败：' + (testResult.detail || '未知原因'))}
              </div>
            )}

            <div className="set-hint">
              本地模式：启动本地翻译服务（如 koboldcpp）并监听 5001 的 OpenAI 兼容端点。<br />
              云端模式：填写 OpenAI 兼容地址、模型名与 API Key 后点“使用云端 API”。<br />
              两者都不可用时，任务会在翻译阶段失败；修改会写入后端 .env 并持久化。
            </div>
          </div>
        </div>

        <div className="table-card">
          <div className="table-head">
            <div className="t">运维（管理员）</div>
            <div className="cnt">{adminNote}</div>
          </div>
          <div className="set-body">
            <Row label="缓存条目" value={cache ? String(cache.total_entries) : '-'} />
            <Row label="缓存命中率" value={cache ? (String(cache.hit_rate) + '%') : '-'} />
            <Row label="缓存容量" value={cache ? (String(cache.size_mb) + ' MB / TTL ' + String(cache.ttl_days) + ' 天') : '-'} />
            <Row label="队列并发上限" value={queue ? String(queue.max_concurrent) : '-'} />
            <div className="set-actions">
              <button className="btn" disabled={!cache} onClick={() => void doClearCache()}>清空翻译缓存</button>
            </div>
          </div>
        </div>

        <div className="table-card">
          <div className="table-head"><div className="t">修改密码</div></div>
          <div className="set-body">
            <div className="set-form">
              <input className="auth-input" type="password" placeholder="当前密码" value={oldPw} onChange={(e) => setOldPw(e.target.value)} />
              <input className="auth-input" type="password" placeholder="新密码（至少 6 位）" value={newPw} onChange={(e) => setNewPw(e.target.value)} />
            </div>
            <div className="set-actions">
              <button className="btn primary" disabled={!oldPw || !newPw} onClick={() => void doChangePassword()}>修改密码</button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
