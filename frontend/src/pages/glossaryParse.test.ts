import { describe, it, expect } from 'vitest';

// 词表解析：验证「←」变体写法与老写法兼容
// 这段逻辑原本内联在 WizardPage 里，这里抽出来单独测，避免 UI 测试成本过高
function parseGlossary(text: string) {
  return text
    .split('\n')
    .map((x) => x.trim())
    .filter(Boolean)
    .map((raw) => {
      const isGame = raw.startsWith('G:') || raw.startsWith('g:');
      const body = isGame ? raw.slice(2).trim() : raw;
      const arrow = body.split(/←|<-|<=/);
      const src = (arrow[0] || '').trim();
      const variants = arrow.length > 1
        ? arrow.slice(1).join(' ').split(/[,，、|]/).map((s) => s.trim()).filter(Boolean)
        : [];
      const term: { src: string; type: string; variants?: string[] } = {
        src, type: isGame ? 'game' : 'person',
      };
      if (variants.length) term.variants = variants;
      return term;
    })
    .filter((t) => t.src);
}

describe('词表解析', () => {
  it('老写法不变：人名与 G: 游戏名', () => {
    const r = parseGlossary('橘长\nG:怪猎');
    expect(r).toEqual([
      { src: '橘长', type: 'person' },
      { src: '怪猎', type: 'game' },
    ]);
  });

  it('单变体：甲修 ← 甲球', () => {
    const r = parseGlossary('甲修 ← 甲球');
    expect(r[0]).toEqual({ src: '甲修', type: 'person', variants: ['甲球'] });
  });

  it('多变体用逗号分隔', () => {
    const r = parseGlossary('甲修 ← 甲球,甲秋，甲求');
    expect(r[0].variants).toEqual(['甲球', '甲秋', '甲求']);
  });

  it('游戏名 + 变体可以组合', () => {
    const r = parseGlossary('G:碰瓷M7 ← possm7,POSSM7');
    expect(r[0]).toEqual({
      src: '碰瓷M7', type: 'game', variants: ['possm7', 'POSSM7'],
    });
  });

  it('没有变体时不产生 variants 字段（保持老数据形状）', () => {
    const r = parseGlossary('M7');
    expect(r[0]).toEqual({ src: 'M7', type: 'person' });
    expect('variants' in r[0]).toBe(false);
  });

  it('空行与纯空白被忽略', () => {
    const r = parseGlossary('\n  甲修 ← 甲球\n\n  \n');
    expect(r).toHaveLength(1);
  });

  it('← 两侧空格可有可无', () => {
    expect(parseGlossary('甲修←甲球')[0].variants).toEqual(['甲球']);
    expect(parseGlossary('甲修  ←  甲球')[0].src).toBe('甲修');
  });
});