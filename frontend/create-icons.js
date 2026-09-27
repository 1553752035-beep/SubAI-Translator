/**
 * 生成 SubAI Translator 应用图标
 * 使用 Canvas API 创建图标
 */

const { createCanvas } = require('canvas');
const fs = require('fs');
const path = require('path');

// 创建图标目录
const iconDir = path.join(__dirname, 'src-tauri', 'icons');
if (!fs.existsSync(iconDir)) {
    fs.mkdirSync(iconDir, { recursive: true });
}

// 创建 256x256 图标
const size = 256;
const canvas = createCanvas(size, size);
const ctx = canvas.getContext('2d');

// 绘制圆角矩形背景
const cornerRadius = 50;
ctx.beginPath();
ctx.moveTo(cornerRadius, 0);
ctx.lineTo(size - cornerRadius, 0);
ctx.quadraticCurveTo(size, 0, size, cornerRadius);
ctx.lineTo(size, size - cornerRadius);
ctx.quadraticCurveTo(size, size, size - cornerRadius, size);
ctx.lineTo(cornerRadius, size);
ctx.quadraticCurveTo(0, size, 0, size - cornerRadius);
ctx.lineTo(0, cornerRadius);
ctx.quadraticCurveTo(0, 0, cornerRadius, 0);
ctx.closePath();

// 绘制渐变背景
const gradient = ctx.createLinearGradient(0, 0, size, size);
gradient.addColorStop(0, '#3b82f6');
gradient.addColorStop(1, '#8b5cf6');
ctx.fillStyle = gradient;
ctx.fill();

// 绘制文字 "S"
ctx.fillStyle = '#ffffff';
ctx.font = 'bold 140px "Segoe UI", Arial, sans-serif';
ctx.textAlign = 'center';
ctx.textBaseline = 'middle';
ctx.fillText('S', size / 2, size / 2);

// 保存为 PNG
const outPath = path.join(iconDir, 'icon.png');
const out = fs.createWriteStream(outPath);
const stream = canvas.createPNGStream();
stream.pipe(out);
out.on('finish', () => console.log('✓ Created icon.png'));

// 生成不同尺寸的图标
const sizes = [32, 128];
sizes.forEach(s => {
    const smallCanvas = createCanvas(s, s);
    const smallCtx = smallCanvas.getContext('2d');
    smallCtx.drawImage(canvas, 0, 0, s, s);
    
    const fileName = s === 32 ? '32x32.png' : '128x128.png';
    const filePath = path.join(iconDir, fileName);
    const out = fs.createWriteStream(filePath);
    const stream = smallCanvas.createPNGStream();
    stream.pipe(out);
    out.on('finish', () => console.log(`✓ Created ${fileName}`));
});

console.log('\nIcons generated successfully!');
console.log(`Icon directory: ${iconDir}`);