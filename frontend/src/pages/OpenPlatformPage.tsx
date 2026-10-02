import { useCallback, useEffect, useState } from 'react';
import {
  createOpenApiKey,
  createWebhook,
  deleteWebhook,
  getOpenApiKeys,
  getWebhookDeliveries,
  getWebhooks,
  retryDelivery,
  revokeOpenApiKey,
  setKeyEnabled,
  setKeyRateLimit,
  setWebhookEnabled,
  testWebhook,
} from '../api';
import type { ApiKeyInfo, DeliveryInfo, WebhookInfo } from '../types';

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="set-row">
      <span className="k">{label}</span>
      <span className="v">{value}</span>
    </div>
  );
}

function describeLimit(value: number | null): string {
  if (value === null || value === undefined) return '默认';
  return value === 0 ? '不限' : String(value) + ' 次/分钟';
}

export function OpenPlatformPage() {
  const [keys, setKeys] = useState<ApiKeyInfo[]>([]);
  const [hooks, setHooks] = useState<WebhookInfo[]>([]);
  const [events, setEvents] = useState<string[]>([]);
  const [hookStats, setHookStats] = useState<any>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [keyName, setKeyName] = useState('');
  const [scopes, setScopes] = useState('translate,tasks,languages,transcode');
  const [rateLimit, setRateLimit] = useState('');
  const [newSecret, setNewSecret] = useState('');
  const [hookUrl, setHookUrl] = useState('');
  const [hookEvents, setHookEvents] = useState('');
  const [newHookSecret, setNewHookSecret] = useState('');
  const [deliveries, setDeliveries] = useState<DeliveryInfo[]>([]);
  const [deliveriesFor, setDeliveriesFor] = useState('');

  const load = useCallback(async () => {
    try {
      const [k, w] = await Promise.all([getOpenApiKeys(), getWebhooks()]);
      setKeys(k.keys || []);
      setHooks(w.webhooks || []);
      setEvents(w.events || []);
      setHookStats(w.stats || null);
    } catch {
      setError('加载失败：请确认后端已启动，且当前账号是管理员');
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const run = async (fn: () => Promise<unknown>, after?: () => void) => {
    setBusy(true);
    setError('');
    try {
      await fn();
      if (after) after();
      await load();
    } catch (e: any) {
      setError(String(e?.response?.data?.detail || e?.message || '操作失败'));
    } finally {
      setBusy(false);
    }
  };

  const doCreateKey = () => run(async () => {
    const result = await createOpenApiKey(
      keyName.trim() || '未命名密钥',
      scopes.split(',').map((s) => s.trim()).filter(Boolean),
      rateLimit.trim() === '' ? null : Number(rateLimit),
    );
    setNewSecret(result.secret);
    setKeyName('');
  });

  const doAddHook = () => run(async () => {
    const result = await createWebhook(
      hookUrl.trim(),
      hookEvents.split(',').map((s) => s.trim()).filter(Boolean),
    );
    setNewHookSecret(result.secret);
    setHookUrl('');
  });

  const doShowDeliveries = (id: string) => run(async () => {
    const result = await getWebhookDeliveries(id);
    setDeliveries(result.deliveries || []);
    setDeliveriesFor(id);
  });

  return (
    <div>
      <div className="table-card">
        <div className="table-head">
          <div className="t">API 密钥</div>
          <div className="cnt">{String(keys.length)} 个</div>
        </div>
        <div className="set-body">
          <div className="set-row">
            <input
              className="auth-input"
              placeholder="密钥名称（例如：我的脚本）"
              value={keyName}
              onChange={(e) => setKeyName(e.target.value)}
            />
            <input
              className="auth-input"
              placeholder="权限，逗号分隔"
              value={scopes}
              onChange={(e) => setScopes(e.target.value)}
            />
            <input
              className="auth-input"
              placeholder="限流（次/分钟，留空=默认，0=不限）"
              value={rateLimit}
              onChange={(e) => setRateLimit(e.target.value)}
            />
            <button className="btn" disabled={busy} onClick={() => void doCreateKey()}>
              创建密钥
            </button>
          </div>

          {newSecret && (
            <div className="auth-msg ok">
              新密钥（只显示这一次，请立即保存）：{newSecret}
            </div>
          )}
          {error && <div className="auth-msg error">{error}</div>}

          {keys.map((k) => (
            <div className="set-row" key={k.key_id}>
              <span className="k">{k.name + (k.enabled ? '' : '（已停用）')}</span>
              <span className="v">
                {k.prefix + ' · 调用 ' + String(k.call_count) + ' · 错误 ' + String(k.error_count)
                  + ' · 限流 ' + describeLimit(k.rate_limit)}
              </span>
              <button className="btn" disabled={busy} onClick={() => void run(() => setKeyEnabled(k.key_id, !k.enabled))}>
                {k.enabled ? '停用' : '启用'}
              </button>
              <button className="btn" disabled={busy} onClick={() => void run(() => setKeyRateLimit(k.key_id, 60))}>
                限流设 60
              </button>
              <button className="btn" disabled={busy} onClick={() => void run(() => revokeOpenApiKey(k.key_id))}>
                吊销
              </button>
            </div>
          ))}
          <div className="set-hint">
            服务端只保存密钥的 sha256，明文仅在创建时返回一次；被限流的请求返回 429 并计入错误数。
          </div>
        </div>
      </div>

      <div className="table-card">
        <div className="table-head">
          <div className="t">Webhook 回调</div>
          <div className="cnt">
            {hookStats
              ? (String(hooks.length) + ' 个 · 投递 ' + String(hookStats.deliveries ?? 0)
                 + ' · 成功率 ' + String(Math.round((hookStats.success_rate ?? 1) * 100)) + '%')
              : '-'}
          </div>
        </div>
        <div className="set-body">
          <div className="set-row">
            <input
              className="auth-input"
              placeholder="回调地址（http/https）"
              value={hookUrl}
              onChange={(e) => setHookUrl(e.target.value)}
            />
            <input
              className="auth-input"
              placeholder={'订阅事件，逗号分隔（可留空=全部）：' + (events.length ? events.slice(0, 2).join(',') + '…' : '')}
              value={hookEvents}
              onChange={(e) => setHookEvents(e.target.value)}
            />
            <button className="btn" disabled={busy || !hookUrl.trim()} onClick={() => void doAddHook()}>
              添加 Webhook
            </button>
          </div>

          {newHookSecret && (
            <div className="auth-msg ok">
              该回调的签名密钥（用于校验 X-SubAI-Signature）：{newHookSecret}
            </div>
          )}

          {hooks.map((h) => (
            <div className="set-row" key={h.webhook_id}>
              <span className="k">{h.url + (h.enabled ? '' : '（已停用）')}</span>
              <span className="v">{'事件：' + (h.events.length ? h.events.join(',') : '全部')}</span>
              <button className="btn" disabled={busy} onClick={() => void run(() => testWebhook(h.webhook_id))}>
                测试
              </button>
              <button className="btn" disabled={busy} onClick={() => void doShowDeliveries(h.webhook_id)}>
                投递记录
              </button>
              <button className="btn" disabled={busy} onClick={() => void run(() => setWebhookEnabled(h.webhook_id, !h.enabled))}>
                {h.enabled ? '停用' : '启用'}
              </button>
              <button className="btn" disabled={busy} onClick={() => void run(() => deleteWebhook(h.webhook_id))}>
                删除
              </button>
            </div>
          ))}

          {deliveriesFor && (
            <div>
              <Row label="投递记录" value={deliveriesFor} />
              {deliveries.length === 0 && <div className="set-hint">暂无投递记录</div>}
              {deliveries.map((d) => (
                <div className="set-row" key={d.delivery_id}>
                  <span className="k">{d.event}</span>
                  <span className="v">
                    {d.status + ' · 尝试 ' + String(d.attempts) + ' 次 · HTTP ' + String(d.status_code || '-')
                      + (d.error ? ' · ' + d.error : '')}
                  </span>
                  <button className="btn" disabled={busy} onClick={() => void run(() => retryDelivery(d.delivery_id))}>
                    重投
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="set-hint">
            只有 2xx 算投递成功，失败会退避重试（预算跨重启累计）；进程重启后会自动重投未完成的记录。
          </div>
        </div>
      </div>
    </div>
  );
}
