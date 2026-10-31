import { useCallback, useEffect, useState } from 'react';
import {
  cancelAsrModel,
  checkHealth,
  downloadAsrModel,
  getAsrModelStatus,
  getAsrDevice,
  getAsrEngine,
  getSubtitleQuality,
  getLlmStatus,
  getTranslationSettings,
  getLlmProviders,
  probeLlmProviders,
  openExternal,
  setLlmMode,
  setTermMode,
  testLlm,
} from '../api';
import type {
  AsrDeviceInfo,
  LlmStatus,
  TranslationSettings,
} from '../types';

/**
 * ASR 引擎的中文说明。
 * 放在组件外做常量，避免每次渲染重建对象，也方便新增引擎时只改一处。
 */
const ENGINE_LABELS: Record<string, string> = {
  whisper: 'faster-whisper（默认，有词级时间轴）',
  sensevoice: 'SenseVoice（中文最快；中文游戏/对谈首选）',
  paraformer: 'Paraformer-zh（中文专精，数字念中文）',
  qwen3: 'Qwen3-ASR（多语言/粤语/中英混说/说唱最准，慢 6~8 倍）',
  firered: 'FireRed-ASR（中英 + 方言）',
};

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="set-row">
      <span className="k">{label}</span>
      <span className="v">{value}</span>
    </div>
  );
}

export function SettingsPage() {
  const [health, setHealth] = useState<any>(null);
  const [asr, setAsr] = useState<AsrDeviceInfo | null>(null);
  // [P2 2026-10-24] 字幕质量开关（只读展示；这两项改 .env 后要重启才生效）
  const [quality, setQuality] = useState<{
    drop_hallucination: boolean;
    hallucination_nsp: number;
    hallucination_cr: number;
    max_subtitle_sec: number;
    min_display_sec: number;
  } | null>(null);
  const [turbo, setTurbo] = useState<any>(null);
  // [2026-10-25] ASR 引擎（whisper / sensevoice / paraformer）与 sherpa 模型就绪状态。
  // 引擎由 SUBAI_ASR_ENGINE 决定，进程启动时读取 —— 同样只读展示 + 重启提示。
  const [engine, setEngine] = useState<{
    engine: string;
    denoise: boolean;
    sensevoice_itn: boolean;
    sensevoice_language: string;
    sherpa_installed: boolean;
    models: { sensevoice: boolean; paraformer: boolean; vad: boolean; denoise: boolean };
    models_dir: string;
  } | null>(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const st = await getAsrModelStatus();
        if (alive) setTurbo(st);
      } catch { /* 忽略 */ }
    };
    void tick();
    const t = setInterval(() => { void tick(); }, 3000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  // ASR 引擎状态只读拉一次（进程级常量）
  useEffect(() => {
    let alive = true;
    getAsrEngine()
      .then((e) => { if (alive) setEngine(e); })
      .catch(() => { /* 失败静默：只读展示不该挡住设置页 */ });
    return () => { alive = false; };
  }, []);

  // 字幕质量开关只读拉一次（进程级常量，不会中途变）
  useEffect(() => {
    let alive = true;
    getSubtitleQuality()
      .then((q) => { if (alive) setQuality(q); })
      .catch(() => { /* 失败静默：这是只读展示，不该挡住整个设置页 */ });
    return () => { alive = false; };
  }, []);
  const [llm, setLlm] = useState<LlmStatus | null>(null);
  const [term, setTerm] = useState<TranslationSettings | null>(null);
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  // 五期：服务商预设（选一家就自动带出地址与模型，小白只需填 Key）
  const [providers, setProviders] = useState<any[]>([]);
  const [providerId, setProviderId] = useState('');
  const [providersError, setProvidersError] = useState('');
  // [2026-10-25] 服务商真实连通核验。预填地址 ≠ 可用：地址可能已变更、
  // 模型可能已下线、服务可能停服（实测 yi 返回 HTTP 410 已停服）。
  const [probing, setProbing] = useState(false);
  const [probeRows, setProbeRows] = useState<any[] | null>(null);
  const [probeError, setProbeError] = useState('');
  const [updateMsg, setUpdateMsg] = useState('');
  const [updateBusy, setUpdateBusy] = useState(false);
  const [pendingUpdate, setPendingUpdate] = useState<any>(null);
  const [testResult, setTestResult] = useState<any>(null);

  const [cloudUrl, setCloudUrl] = useState('');
  const [cloudModel, setCloudModel] = useState('');
  const [cloudKey, setCloudKey] = useState('');

  const load = useCallback(async () => {
    setMsg('');
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
    } catch {
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
      } catch {
        /* 旧后端无该接口时保持占位符即可 */
      }
      try {
      } catch {
        /* 同上 */
      }
    })();
  }, []);


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

  const runTest = async (mode?: 'local' | 'cloud' | 'hybrid') => {
    setTesting(true);
    setTestResult(null);
    try {
      setTestResult(await testLlm(mode ?? (llm ? llm.mode : undefined)));
    } catch (err: any) {
      const detail = err && err.response ? err.response.data.detail : null;
      setTestResult({ reachable: false, detail: typeof detail === 'string' ? detail : '测试失败' });
    } finally {
      setTesting(false);
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
            <Row
              label="增强识别模型"
              value={
                turbo?.installed
                  ? '已安装（large-v3-turbo）'
                  : turbo?.state === 'running'
                    ? '下载中 ' + Math.round((turbo.progress || 0) * 100) + '%'
                    : '未安装（当前用 small）'
              }
            />
            {turbo?.installed ? (
              <Row label="当前生效模型" value={String(turbo.active_model_dir || '-')} />
            ) : (
              <div className="set-row">
                <span className="k">下载增强模型</span>
                <span className="v">
                  <button
                    className="w-btn"
                    disabled={turbo?.state === 'running'}
                    onClick={async () => {
                      try {
                        if (turbo?.state === 'running') {
                          setTurbo(await cancelAsrModel());
                        } else {
                          setTurbo(await downloadAsrModel());
                        }
                      } catch {
                        /* 失败静默，状态轮询会反映 */
                      }
                    }}
                  >
                    {turbo?.state === 'running' ? '取消下载' : '下载（1.6 GB，比 small 更快更准）'}
                  </button>
                </span>
              </div>
            )}
            {turbo?.state === 'failed' && (
              <Row label="下载失败" value={String(turbo.error || '未知错误') + '（可重试，支持断点续传）'} />
            )}
            <div className="set-hint">
              判定规则：CTranslate2 支持 CUDA 且 能找到 CUDA DLL 且 空闲显存 ≥4GB，才会使用 GPU，否则安全回落 CPU。
              绿色版主包不含 CUDA 运行库（约 2.0 GB），可用 tools/build_gpu_pack.ps1 生成可选 GPU 包后放入安装目录。
            </div>
          </div>
        </div>

        <div className="table-card">
          <div className="table-head"><div className="t">语音识别引擎</div></div>
          <div className="set-body">
            <Row
              label="当前引擎"
              value={!engine ? '-' : ENGINE_LABELS[engine.engine] ?? ENGINE_LABELS.whisper}
            />
            <Row
              label="sherpa 运行时"
              value={engine ? (engine.sherpa_installed ? '已安装' : '未安装（pip install sherpa-onnx）') : '-'}
            />
            <Row
              label="SenseVoice 模型"
              value={engine ? (engine.models.sensevoice ? '已就绪' : '未安装') : '-'}
            />
            <Row
              label="Paraformer 模型"
              value={engine ? (engine.models.paraformer ? '已就绪' : '未安装') : '-'}
            />
            <Row
              label="Qwen3-ASR 模型"
              value={engine ? (engine.models.qwen3 ? '已就绪（936MB，多语言）' : '未安装（可选，占 936MB）') : '-'}
            />
            <Row
              label="FireRed-ASR 模型"
              value={engine ? (engine.models.firered ? '已就绪（739MB，含方言）' : '未安装（可选，占 739MB）') : '-'}
            />
            <Row
              label="Silero VAD"
              value={engine ? (engine.models.vad ? '已就绪' : '缺失（sherpa 引擎必需）') : '-'}
            />
            <Row
              label="GTCRN 降噪"
              value={
                !engine
                  ? '-'
                  : engine.denoise
                    ? engine.models.denoise
                      ? '已开启（可能引入新错字，仅噪声素材建议开）'
                      : '已开启但模型缺失'
                    : '关闭（默认）'
              }
            />
            {/* 说话人分离（2026-10-25） */}
            <Row
              label="说话人分离"
              value={
                !engine
                  ? '-'
                  : !engine.diarize
                    ? '关闭（默认，单人素材无需开）'
                    : engine.diarize_models?.segmentation && engine.diarize_models?.embedding
                      ? engine.diarize_speakers && engine.diarize_speakers > 0
                        ? `已开启（强制 ${engine.diarize_speakers} 人）`
                        : `已开启（自动判断人数，阈值 ${engine.diarize_threshold?.toFixed(2) ?? '-'}）`
                      : '已开启但模型缺失（models/sherpa/diarization）'
              }
            />
            {engine && engine.engine !== 'whisper' && (
              <Row
                label="时间轴精度"
                value="段级（来自 VAD 段边界，无词级时间戳）"
              />
            )}
            <div className="set-hint">
              切换引擎：设置环境变量 <code>SUBAI_ASR_ENGINE=sensevoice</code> 或 <code>paraformer</code> 后重启。默认 <code>whisper</code> 行为完全不变。
              <br />
              sherpa 引擎模型放在 <code>{engine?.models_dir || 'models/sherpa'}</code>：
              <code>sensevoice-small/</code>、<code>paraformer-zh/</code> 各需 <code>model.int8.onnx</code> + <code>tokens.txt</code>，
              另需 <code>silero_vad.onnx</code>（必需）与 <code>gtcrn_simple.onnx</code>（降噪才需要）。
              <br />
              取舍：sherpa 系中文识别更准、快 2~4 倍，但<b>没有词级时间轴</b>；对断句要求极高时仍建议用 whisper。
            </div>
          </div>
        </div>

        <div className="table-card">
          <div className="table-head"><div className="t">字幕质量（识别与显示）</div></div>
          <div className="set-body">
            <Row
              label="丢弃疑似幻觉"
              value={quality
                ? (quality.drop_hallucination
                    ? '已开启（no_speech ≥ ' + quality.hallucination_nsp + ' 或 压缩比 ≥ ' + quality.hallucination_cr + '）'
                    : '未开启（识别结果原样保留）')
                : '-'}
            />
            <Row
              label="单行最长显示"
              value={quality ? (quality.max_subtitle_sec + ' 秒') : '-'}
            />
            <Row
              label="单行最短显示"
              value={
                !quality
                  ? '-'
                  : quality.min_display_sec > 0
                    ? quality.min_display_sec + ' 秒（过短的行会延长，但不越过下一行起点）'
                    : '未启用'
              }
            />
            <Row
              label="断句方式"
              value="句末标点立即断；停顿标点（，；、）达软上限才断；超字数时回溯到词边界"
            />
            <div className="set-hint">
              以下要在 <code>.env</code> 里改，<b>改完需重启程序</b>：
              <br />
              <code>SUBAI_ASR_DROP_HALLUCINATION=1</code> —— 丢弃 whisper 凭空编的句子
              （低信噪比或 CPU int8 时会出现，证据：同一视频 GPU 版首行「没事我有大血包」，
              CPU 版却写成「而且卡不了星标」，用户人耳确认根本没说过）。
              <br />
              <code>SUBAI_MAX_SUBTITLE_SEC=8</code> —— 一行字幕最长挂几秒。
              VAD 判定「这段时间在说话」但只认出两三个字时，原来会一行挂 36 秒。
              <br />
              <code>SUBAI_MIN_DISPLAY_SEC=1.0</code> —— 一行字幕至少显示几秒。
              设 0 可关闭。实测：开启后 146 秒素材里 &lt;1 秒的碎片行从 27% 降到 17%，
              文本内容一字未改（只调时间轴）。
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
                  <option key={p.id} value={p.id}>
                    {p.group === '翻译专用' ? '▼ ' : ''}{p.name}
                  </option>
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
              {/* 翻译专用引擎（DeepL/Google）不是 OpenAI 协议，不能填 base_url + 模型名。
                  否则用户会填了地址却一直报 404 —— 因为它们根本没有 /chat/completions。 */}
              {(() => {
                const sel = providers.find((x) => x.id === providerId);
                const isDedicated = sel && sel.protocol && sel.protocol !== 'openai';
                if (!isDedicated) {
                  return (
                    <>
                      <input className="auth-input" placeholder="云端 API 地址（OpenAI 兼容）" value={cloudUrl} onChange={(e) => setCloudUrl(e.target.value)} />
                      <input className="auth-input" placeholder="云端模型名（如 gpt-4o）" value={cloudModel} onChange={(e) => setCloudModel(e.target.value)} />
                    </>
                  );
                }
                // [2026-10-25] 免费渠道：连 Key 都不用填。
                // 这是「什么都不申请就能出片」的唯一入口，提示要写明白。
                if (sel.protocol === 'tencent_free') {
                  return (
                    <div className="set-hint" style={{ marginTop: 6 }}>
                      <strong>{sel.name}</strong>：<b>不需要注册、不需要 Key</b>，
                      保存后即可直接翻译。适合先把流程跑通，之后想要更好的
                      译质再换 DeepL / LLM。
                      <div style={{ marginTop: 4 }}>
                        质量与上下文理解弱于大模型，但不会漏句、条数严格对齐。
                      </div>
                    </div>
                  );
                }
                return (
                  <div className="set-hint" style={{ marginTop: 6 }}>
                    <strong>{sel.name}</strong> 使用专用协议（不是 OpenAI 兼容接口），
                    无需填地址和模型名，填 Key 即可。
                    {sel.protocol === 'deepl' && (
                      <div style={{ marginTop: 4 }}>
                        Key 以 <code>:fx</code> 结尾走免费端点，否则走付费端点。
                      </div>
                    )}
                  </div>
                );
              })()}
              {/* 免费渠道不显示 Key 输入框，避免用户以为「还得填点什么」 */}
              {providers.find((x) => x.id === providerId)?.protocol !== 'tencent_free' && (
                <input className="auth-input" type="password" placeholder="云端 API Key（仅提交给后端，不回显）" value={cloudKey} onChange={(e) => setCloudKey(e.target.value)} />
              )}
            </div>
            <div className="set-actions">
              {/* 五期：服务商列表已含本地方案，三个模式按钮合并为一个「保存并使用」 */}
              <button
                className="btn"
                disabled={busy}
                onClick={async () => {
                  const sel = providers.find((x) => x.id === providerId);
                  const target: 'local' | 'cloud' = sel && sel.group === '本地' ? 'local' : 'cloud';
                  await switchMode(target);
                  // 五期：切完立刻测「刚切换的那个模式」，避免测到旧模式造成误解
                  await runTest(target);
                }}
              >
                保存并使用
              </button>
              <button className="btn" disabled={testing} onClick={() => void runTest()}>
                {testing ? '测试中…' : '测试连接'}
              </button>
              <button
                className="btn"
                disabled={probing}
                onClick={async () => {
                  setProbing(true);
                  setProbeError('');
                  try {
                    const r = await probeLlmProviders(cloudKey || undefined);
                    setProbeRows(r.results || []);
                  } catch (e: any) {
                    setProbeError(String(e?.response?.data?.detail || e?.message || '核验失败'));
                  } finally {
                    setProbing(false);
                  }
                }}
              >
                {probing ? '核验中…' : '核验全部服务商'}
              </button>
            </div>

            {probeError && (
              <div className="auth-msg error">{probeError}</div>
            )}

            {probeRows && (() => {
              // 只把「有信息量」的排前面：能用的和已停服的最需要看到，
              // 本机网络不通的一大堆堆在后面，避免淹没关键结论。
              const rank: Record<string, number> = {
                ok: 0, discontinued: 1, auth_failed: 2, forbidden: 2,
                not_found: 3, rate_limited: 3, no_key: 3,
                network_error: 8, not_probeable: 9,
              };
              const rows = [...probeRows].sort(
                (a, b) => (rank[a.verdict] ?? 5) - (rank[b.verdict] ?? 5));
              const label: Record<string, string> = {
                ok: '可用',
                no_key: '端点正常（未填 Key）',
                auth_failed: 'Key 无效',
                forbidden: '无权访问',
                discontinued: '已停服',
                not_found: '模型不存在',
                rate_limited: '限流',
                network_error: '本机不可达',
                not_probeable: '无需核验',
                bad_request: '请求被拒',
              };
              return (
                <div style={{ marginTop: 10 }}>
                  <div className="set-hint">
                    核验结果（{rows.length} 个）。预填地址不等于可用 ——
                    地址会变、模型会下线、服务会停服。
                  </div>
                  <div style={{
                    maxHeight: 220, overflowY: 'auto', marginTop: 6,
                    border: '1px solid rgba(255,255,255,.08)', borderRadius: 6,
                  }}>
                    {rows.map((r) => {
                      const bad = ['auth_failed', 'forbidden', 'discontinued',
                                   'not_found', 'network_error'].includes(r.verdict);
                      const good = r.verdict === 'ok';
                      return (
                        <div key={r.id} style={{
                          display: 'flex', gap: 8, padding: '5px 9px',
                          fontSize: 12.5,
                          borderTop: '1px solid rgba(255,255,255,.05)',
                        }}>
                          <span style={{ width: 150, flex: 'none', opacity: .9 }}>{r.name || r.id}</span>
                          <span style={{
                            width: 130, flex: 'none',
                            color: good ? '#7ee787' : bad ? '#ff9b9b' : 'inherit',
                            opacity: good || bad ? 1 : .65,
                          }}>
                            {label[r.verdict] || r.verdict || '-'}
                          </span>
                          <span style={{ opacity: .55, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {r.detail || ''}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })()}

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



      </div>
    </>
  );
}
