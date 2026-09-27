import React from 'react';
import type { TaskMode, OutputFormat } from '../types';
import styles from '../styles/components.module.css';

interface ConfigPanelProps {
  mode: TaskMode;
  setMode: (mode: TaskMode) => void;
  sourceLang: string;
  setSourceLang: (lang: string) => void;
  targetLang: string;
  setTargetLang: (lang: string) => void;
  outputFormat: OutputFormat;
  setOutputFormat: (format: OutputFormat) => void;
  disabled?: boolean;
}

const ConfigPanel: React.FC<ConfigPanelProps> = ({
  mode,
  setMode,
  sourceLang,
  setSourceLang,
  targetLang,
  setTargetLang,
  outputFormat,
  setOutputFormat,
  disabled = false,
}) => {
  return (
    <div className={styles.configPanel}>
      <h3>⚙️ 参数配置</h3>
      
      <div className={styles.formGroup}>
        <label>识别模式</label>
        <div className={styles.radioGroup}>
          <label className={styles.radioLabel}>
            <input
              type="radio"
              checked={mode === 'asr'}
              onChange={() => setMode('asr')}
              disabled={disabled}
            />
            <span>语音识别 (ASR)</span>
          </label>
          <label className={styles.radioLabel}>
            <input
              type="radio"
              checked={mode === 'hardsub'}
              onChange={() => setMode('hardsub')}
              disabled={disabled}
            />
            <span>硬字幕OCR</span>
          </label>
        </div>
      </div>

      <div className={styles.formGroup}>
        <label htmlFor="sourceLang">源语言</label>
        <select
          id="sourceLang"
          value={sourceLang}
          onChange={(e) => setSourceLang(e.target.value)}
          disabled={disabled}
        >
          <option value="auto">自动检测</option>
          <option value="zh">中文</option>
          <option value="en">English</option>
          <option value="ja">日本語</option>
          <option value="ko">한국어</option>
        </select>
      </div>

      <div className={styles.formGroup}>
        <label htmlFor="targetLang">目标语言</label>
        <select
          id="targetLang"
          value={targetLang}
          onChange={(e) => setTargetLang(e.target.value)}
          disabled={disabled}
        >
          <option value="zh">中文</option>
          <option value="en">English</option>
          <option value="ja">日本語</option>
          <option value="ko">한국어</option>
          <option value="fr">Français</option>
          <option value="de">Deutsch</option>
          <option value="es">Español</option>
        </select>
      </div>

      <div className={styles.formGroup}>
        <label htmlFor="outputFormat">输出格式</label>
        <select
          id="outputFormat"
          value={outputFormat}
          onChange={(e) => setOutputFormat(e.target.value as OutputFormat)}
          disabled={disabled}
        >
          <option value="srt">SRT (字幕)</option>
          <option value="vtt">VTT (网页字幕)</option>
          <option value="ass">ASS (高级字幕)</option>
          <option value="json">JSON (数据)</option>
        </select>
      </div>
    </div>
  );
};

export default ConfigPanel;