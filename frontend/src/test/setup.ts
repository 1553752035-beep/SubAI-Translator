import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// 每个用例后清理 DOM，避免相互污染
afterEach(() => {
  cleanup();
});
