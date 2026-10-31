import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getWaveform } from '../api';

/**
 * 校对台波形图。
 *
 * 解决的问题
 * ----------
 * 校对台原来只有播放器和字幕列表，用户看不出「这行字幕切在哪段声音上」。
 * 波形图把字幕行和音频对齐后：
 * - 字幕切早了/切晚了，一眼能看出来（文字块和声音块错位）
 * - 某段有明显声音却没有字幕块覆盖 —— 就是漏句（配合后端的未覆盖告警）
 *
 * 实现要点
 * --------
 * 1. 后端只给「每像素桶的 min/max」，前端纯画线，不做音频解码。
 *    浏览器解码 10 分钟音频要几十 MB 内存，且和已有 <video> 重复。
 * 2. 用 canvas 而非 DOM 元素：1000 个桶画成 DOM 会卡，canvas 一帧搞定。
 * 3. 画三层：波形（灰）→ 字幕覆盖区（半透明蓝）→ 播放头（红）。
 *    分层画是为了「字幕块」能被波形衬托出来，而不是把波形盖住。
 */
export interface WaveformSegment {
  start: number;
  end: number;
}

interface Props {
  /** 媒体文件绝对路径 */
  mediaPath: string;
  /** 时长（秒），未知时由后端返回的 duration 兜底 */
  duration?: number;
  /** 字幕时间段，用于画覆盖区 */
  segments?: WaveformSegment[];
  /** 当前播放位置（秒） */
  currentTime?: number;
  /** 点击波形跳转 */
  onSeek?: (sec: number) => void;
  /** 画布高度 */
  height?: number;
}

const COLORS = {
  wave: '#8a9bb0',
  seg: 'rgba(64, 158, 255, 0.28)',
  segEdge: 'rgba(64, 158, 255, 0.75)',
  head: '#e5484d',
  axis: '#d8dee8',
};

export const WaveformView = ({
  mediaPath,
  duration,
  segments = [],
  currentTime = 0,
  onSeek,
  height = 76,
}: Props) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [peaks, setPeaks] = useState<[number, number][]>([]);
  const [realDuration, setRealDuration] = useState(duration ?? 0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [width, setWidth] = useState(600);

  // 跟随容器宽度（用 ResizeObserver，窗口缩放时波形要跟着变宽而不是拉伸变形）
  useEffect(() => {
    const el = wrapRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect?.width ?? 0;
      if (w > 0) setWidth(Math.round(w));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // 拉波形：桶数跟画布像素宽度走，这样每个像素一个桶，不浪费也不失真
  useEffect(() => {
    if (!mediaPath) {
      setPeaks([]);
      return;
    }
    let alive = true;
    setLoading(true);
    setError('');
    getWaveform({ path: mediaPath, buckets: Math.max(200, width) })
      .then((d) => {
        if (!alive) return;
        setPeaks(d.peaks || []);
        if (d.duration > 0) setRealDuration(d.duration);
      })
      .catch((e: any) => {
        if (!alive) return;
        const detail = e?.response?.data?.detail;
        setError(typeof detail === 'string' ? detail : e?.message || '波形加载失败');
        setPeaks([]);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [mediaPath, width]);

  const total = useMemo(() => {
    const d = realDuration || duration || 0;
    return d > 0 ? d : 0;
  }, [realDuration, duration]);

  // 绘制
  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    const dpr = (typeof window !== 'undefined' && window.devicePixelRatio) || 1;
    const w = width;
    const h = height;
    cv.width = Math.round(w * dpr);
    cv.height = Math.round(h * dpr);
    cv.style.width = w + 'px';
    cv.style.height = h + 'px';
    const ctx = cv.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const mid = h / 2;

    // 1) 中线
    ctx.strokeStyle = COLORS.axis;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, mid);
    ctx.lineTo(w, mid);
    ctx.stroke();

    if (total <= 0) return;

    // 2) 字幕覆盖区（画在波形下面一层，用半透明避免盖住波形）
    for (const s of segments) {
      const x1 = (s.start / total) * w;
      const x2 = (s.end / total) * w;
      if (x2 < 0 || x1 > w) continue;
      ctx.fillStyle = COLORS.seg;
      ctx.fillRect(x1, 0, Math.max(1, x2 - x1), h);
      ctx.strokeStyle = COLORS.segEdge;
      ctx.beginPath();
      ctx.moveTo(x1, 0);
      ctx.lineTo(x1, h);
      ctx.stroke();
    }

    // 3) 波形（min/max 竖线；用 path 批量画，比逐条 stroke 快得多）
    if (peaks.length) {
      ctx.strokeStyle = COLORS.wave;
      ctx.lineWidth = 1;
      ctx.beginPath();
      const scale = (h / 2) * 0.92;
      for (let i = 0; i < peaks.length; i++) {
        const x = (i / peaks.length) * w;
        const [lo, hi] = peaks[i];
        ctx.moveTo(x + 0.5, mid - hi * scale);
        ctx.lineTo(x + 0.5, mid - lo * scale);
      }
      ctx.stroke();
    }

    // 4) 播放头
    if (currentTime > 0) {
      const x = Math.min(w, (currentTime / total) * w);
      ctx.strokeStyle = COLORS.head;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
  }, [peaks, segments, currentTime, total, width, height]);

  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (!onSeek || total <= 0) return;
      const rect = e.currentTarget.getBoundingClientRect();
      const ratio = (e.clientX - rect.left) / Math.max(1, rect.width);
      onSeek(Math.max(0, Math.min(total, ratio * total)));
    },
    [onSeek, total],
  );

  return (
    <div ref={wrapRef} style={{ width: '100%' }} data-testid="waveform-view">
      <canvas
        ref={canvasRef}
        onClick={handleClick}
        style={{ display: 'block', cursor: onSeek ? 'pointer' : 'default',
                 background: '#fafbfc', borderRadius: 4, border: '1px solid var(--border)' }}
        aria-label="音频波形"
      />
      {loading && <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>波形加载中…</div>}
      {error && <div style={{ fontSize: 12, color: '#f44336' }}>{error}</div>}
      {!loading && !error && peaks.length > 0 && (
        <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 2 }}>
          点击波形可跳转 · 蓝色区域为字幕覆盖段
        </div>
      )}
    </div>
  );
};
