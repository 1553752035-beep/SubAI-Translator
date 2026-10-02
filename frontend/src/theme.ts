// 五期：浅色 / 深色两套主题（首次进入问一次，记住后不再问）
export type Theme = 'light' | 'dark';

const KEY = 'subai_theme';

export const getSavedTheme = (): Theme | null => {
  try {
    const t = localStorage.getItem(KEY);
    return t === 'light' || t === 'dark' ? t : null;
  } catch {
    return null;
  }
};

export const saveTheme = (t: Theme): void => {
  try {
    localStorage.setItem(KEY, t);
  } catch {
    /* 隐私模式下写不进去，忽略 */
  }
};

export const applyTheme = (t: Theme): void => {
  document.documentElement.className = t;
};

export const systemTheme = (): Theme => {
  try {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  } catch {
    return 'dark';
  }
};

// 非 Tauri 环境（纯浏览器打开）没有本机令牌命令，做一次特征探测
export const isTauri = (): boolean => typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
