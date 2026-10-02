import { useCallback, useEffect, useState } from 'react';
import {
  checkHealth,
  clearCache,
  getAsrDevice,
  getCacheStats,
  getCurrentUser,
  getLlmStatus,
  getQueueStats,
  getTranslationSettings,
  getLanguages,
  detectLanguage,
  getOpenApiStats,
  getLlmProviders,
  openExternal,
  downloadReport,
  setLlmMode,
  setTermMode,
  testLlm,
} from '../api';
import type {
  AsrDeviceInfo,
  LanguageStats,
  CacheStats,
  LlmStatus,
  QueueStats,
  TranslationSettings,
  UserInfo,
} from '../types';

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
  const [term, setTerm] = useState<TranslationSettings | null>(null);
  const [adminNote, setAdminNote] = useState('');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [langStats, setLangStats] = useState<LanguageStats | null>(null);
  const [detectText, setDetectText] = useState('');
  const [detectResult, setDetectResult] = useState('');
  const [openStats, setOpenStats] = useState<any>(null);
  // 五期：服务商预设（选一家就自动带出地址与模型，小白只需填 Key）
  const [providers, setProviders] = useState<any[]>([]);
  const [providerId, setProviderId] = useState('');
  const [providersError, setProvidersError] = useState('');
  const [updateMsg, setUpdateMsg] = useState('');
  const [updateBusy, setUpdateBusy] = useState(false);
  const [pendingUpdate, setPendingUpdate] = useState<any>(null);
  const [testResult, setTestResult] = useState<any>(null);

  const [cloudUrl, setCloudUrl] = useState('');
  const [cloudModel, setCloudModel] = useState('');
  const [cloudKey, setCloudKey] = useState('');

  const load = useCallback(async () => {
    setMsg('');
    try { setMe(await getCurrentUser()); } catch { /* 忽略 */ }
    try { setHealth(await checkHealth()); } catch { setHealth(null); }
    try { setAsr(await getAsrDevice()); } catch { setAsr(null); }
    try { setTerm(await getTranslationSettings()); } catch { setTerm(null); }
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

  // 四期 4.4 / 4.5：语言支持与开放平台概览（接口不可用时不影响页面其它部分）
  // 五期：加载服务商预设（失败不影响页面其它部分）
  useEffect(() => {
    (async () => {
      try {
        const data = await getLlmProviders();
        setProviders(data.providers || []);
      } catch {
        // 五期：不要静默失败——之前后端版本旧时这里悄悄空列表，让人以为"没有服务商"
        setProvidersError('服务商列表加载失败：后端可能不是最新版本（请更新 subai-backend.exe）');
      }
    })();
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const langs = await getLanguages();
        setLangStats(langs.stats);
      } catch {
        /* 旧后端无该接口时保持占位符即可 */
      }
      try {
        setOpenStats(await getOpenApiStats());
      } catch {
        /* 同上 */
      }
    })();
  }, []);

  const doDetect = async () => {
    setDetectResult("");
    try {
      const r = await detectLanguage(detectText);
      setDetectResult(r.code
        ? ("检测结果：" + r.code + "（置信度 " + String(Math.round(r.confidence * 100)) + "%，方法 " + r.method + "）")
        : "无法判定该文本的语言");
    } catch {
      setDetectResult("检测失败");
    }
  };

  // 四期深化：检查更新（插件按需动态导入，浏览器/测试环境不受影响）
  const doCheckUpdate = async () => {
    setUpdateBusy(true);
    setUpdateMsg('正在检查更新…');
    try {
      const mod = await import('@tauri-apps/plugin-updater');
      const update = await mod.check();
      if (!update) {
        setPendingUpdate(null);
        setUpdateMsg('已是最新版本（当前 ' + (health ? String(health.version) : '未知') + '）');
      } else {
        setPendingUpdate(update);
        setUpdateMsg('发现新版本 ' + String(update.version)
          + (update.body ? '：' + String(update.body) : ''));
      }
    } catch (e: any) {
      setUpdateMsg('检查更新失败：' + String(e?.message || e));
    } finally {
      setUpdateBusy(false);
    }
  };

  const doInstallUpdate = async () => {
    if (!pendingUpdate) return;
    setUpdateBusy(true);
    setUpdateMsg('正在下载并安装更新，请勿关闭程序…');
    try {
      await pendingUpdate.downloadAndInstall();
      setUpdateMsg('更新已安装，正在重启…');
      const proc = await import('@tauri-apps/plugin-process');
      await proc.relaunch();
    } catch (e: any) {
      setUpdateMsg('更新失败：' + String(e?.message || e));
      setUpdateBusy(false);
    }
  };

  const doExport = async (format: string) => {
    try {
      await downloadReport(format);
    } catch {
      setDetectResult("报表导出失败");
    }
  };

  const switchTermMode = async (mode: string) => {
    setBusy(true);
    setMsg('');
    try {
      const s = await setTermMode(mode);
      setTerm((prev) => (prev ? { ...prev, term_mode: s.term_mode } : prev));
      setMsg('术语模式已切换为' + (s.term_mode === 'hint' ? '软提示' : '强制锁定'));
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      setMsg(typeof detail === 'string' ? detail : '切换术语模式失败');
    } finally {
      setBusy(false);
    }
  };

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
              <select
                className="auth-input"
                value={providerId}
                onChange={(e) => {
                  const id = e.target.value;
                  setProviderId(id);
                  const p = providers.find((x) => x.id === id);
                  if (p) {
                    setCloudUrl(p.base_url);
                    setCloudModel(p.models?.[0] || '');
                  }
                }}
              >
                <option value="">选择服务商（不会填就选这个）</option>
                {providers.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
              {providersError && (
                <div className="set-hint" style={{ color: "#ff9b9b" }}>{providersError}</div>
              )}
              {providerId && (() => {
                const p = providers.find((x) => x.id === providerId);
                if (!p) return null;
                return (
                  <div className="set-hint" style={{ marginTop: 0 }}>
                    还没 Key？<button className="btn" style={{ padding: '2px 8px', margin: '0 4px' }} onClick={() => void openExternal(p.key_url)}>点这里获取 {p.name} 的 API Key</button>
                    {p.note ? '　·　' + p.note : ''}
                  </div>
                );
              })()}
              {providerId && (providers.find((x) => x.id === providerId)?.models?.length > 0) && (
                <select
                  className="auth-input"
                  value={cloudModel}
                  onChange={(e) => setCloudModel(e.target.value)}
                >
                  {providers.find((x) => x.id === providerId).models.map((m: string) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                  <option value={cloudModel}>其他（用下面的输入框自己填）</option>
                </select>
              )}
              <input className="auth-input" placeholder="云端 API 地址（OpenAI 兼容）" value={cloudUrl} onChange={(e) => setCloudUrl(e.target.value)} />
              <input className="auth-input" placeholder="云端模型名（如 gpt-4o）" value={cloudModel} onChange={(e) => setCloudModel(e.target.value)} />
              <input className="auth-input" type="password" placeholder="云端 API Key（仅提交给后端，不回显）" value={cloudKey} onChange={(e) => setCloudKey(e.target.value)} />
            </div>
            <div className="set-actions">
              {/* 五期：服务商列表已含本地方案，三个模式按钮合并为一个「保存并使用」 */}
              <button
                className="btn"
                disabled={busy}
                onClick={() => {
                  const sel = providers.find((x) => x.id === providerId);
                  void switchMode(sel && sel.group === '本地' ? 'local' : 'cloud');
                }}
              >
                保存并使用
              </button>
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
          <div className="table-head"><div className="t">术语库模式</div></div>
          <div className="set-body">
            <Row
              label="当前模式"
              value={term ? (term.term_mode === 'hint' ? '软提示' : '强制锁定') : '-'}
            />
            <div className="set-actions">
              <button className="btn" disabled={busy} onClick={() => void switchTermMode('strict')}>强制锁定</button>
              <button className="btn" disabled={busy} onClick={() => void switchTermMode('hint')}>软提示</button>
            </div>
            <div className="set-hint">
              强制锁定：术语译名 100% 一致（占位符替换后再还原），术语作定语时句式可能略生硬。<br />
              软提示：把命中的术语作为"必须使用"的要求交给模型，语句更自然，但不保证逐字一致。<br />
              两种模式下，命中术语的字幕行都不会使用翻译缓存（术语改动后必须重译）。
            </div>
          </div>
        </div>

        <div className="table-card">
          <div className="table-head"><div className="t">版本与更新</div></div>
          <div className="set-body">
            <Row label="当前版本" value={health ? String(health.version) : '-'} />
            <div className="set-actions">
              <button className="btn" disabled={updateBusy} onClick={() => void doCheckUpdate()}>
                检查更新
              </button>
              {pendingUpdate && (
                <button className="btn" disabled={updateBusy} onClick={() => void doInstallUpdate()}>
                  下载并安装
                </button>
              )}
            </div>
            {updateMsg && <div className="auth-msg ok">{updateMsg}</div>}
            <div className="set-hint">
              更新包需通过签名校验才会安装；更新源为本仓库 GitHub Releases 的 latest.json。
            </div>
          </div>
        </div>

        <div className="table-card">
          <div className="table-head"><div className="t">语言与报表（四期）</div></div>
          <div className="set-body">
            <Row
              label="支持语言"
              value={langStats
                ? (String(langStats.total) + ' 种（识别 ' + String(langStats.asr) + ' · 翻译 '
                   + String(langStats.translate) + ' · 配音 ' + String(langStats.tts) + '）')
                : '-'}
            />
            <div className="set-actions">
              <input
                className="auth-input"
                placeholder="输入一段文本，检测它的语言"
                value={detectText}
                onChange={(e) => setDetectText(e.target.value)}
              />
              <button className="btn" disabled={!detectText} onClick={() => void doDetect()}>检测语言</button>
            </div>
            {detectResult && <div className="auth-msg ok">{detectResult}</div>}
            <Row
              label="开放平台"
              value={openStats
                ? ('密钥 ' + String(openStats.keys?.keys ?? 0) + ' 个 · 调用 '
                   + String(openStats.keys?.calls ?? 0) + ' 次 · 回调 '
                   + String(openStats.webhooks?.deliveries ?? 0) + ' 次（成功率 '
                   + String(Math.round((openStats.webhooks?.success_rate ?? 1) * 100)) + '%）')
                : '-'}
            />
            <div className="set-actions">
              <button className="btn" onClick={() => void doExport('xlsx')}>导出统计 Excel</button>
              <button className="btn" onClick={() => void doExport('pdf')}>导出统计 PDF</button>
              <button className="btn" onClick={() => void doExport('html')}>导出统计 HTML</button>
            </div>
            <div className="set-hint">
              报表数据直接来自任务记录（含翻译行数 / 术语命中 / 缓存命中），因此与任务列表里的数字一致。
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

      </div>
    </>
  );
}
