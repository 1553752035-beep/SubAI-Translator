import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// 前端组件测试配置：jsdom 环境 + Testing Library
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
  },
});
