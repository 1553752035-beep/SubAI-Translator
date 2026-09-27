const fs = require('fs');
const path = require('path');

// 创建一个简单的 256x256 PNG 图标（蓝色渐变背景 + 白色文字 "S"）
function createSimpleIcon() {
  const size = 256;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');

  // 绘制渐变背景
  const gradient = ctx.createLinearGradient(0, 0, size, size);
  gradient.addColorStop(0, '#3b82f6');
  gradient.addColorStop(1, '#8b5cf6');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);

  // 绘制圆角
  const radius = 50;
  ctx.beginPath();
  ctx.moveTo(radius, 0);
  ctx.lineTo(size - radius, 0);
  ctx.quadraticCurveTo(size, 0, size, radius);
  ctx.lineTo(size, size - radius);
  ctx.quadraticCurveTo(size, size, size - radius, size);
  ctx.lineTo(radius, size);
  ctx.quadraticCurveTo(0, size, 0, size - radius);
  ctx.lineTo(0, radius);
  ctx.quadraticCurveTo(0, 0, radius, 0);
  ctx.closePath();
  ctx.fill();

  // 绘制文字 "S"
  ctx.fillStyle = '#ffffff';
  ctx.font = 'bold 140px "Segoe UI", sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('S', size / 2, size / 2);

  // 转换为 PNG Buffer
  canvas.toBlob((blob) => {
    const arrayBuffer = new ArrayBuffer(blob.size);
    const view = new Uint8Array(arrayBuffer);
    // 这里需要实际实现 blob 到 buffer 的转换
    console.log('Icon generated');
  });
}

// 由于浏览器 API 限制，我们创建一个简单的占位文件
console.log('请手动创建图标文件或使用以下命令：');
console.log('npx tauri icon');