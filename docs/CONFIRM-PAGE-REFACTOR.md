# 确认页（第二级页面）重构方案 —— 存档

> 状态：**已记录，暂不实施**（2026-10-17，用户要求先存档）
> 来源：外部 AI 建议（用户转述），下方「一、外部方案原文」为原样保存
> 相关待办：① 中文默认简体 ② 确认页层级/导航 ③ 确认页缺少取消按钮

---

## 一、外部方案原文（存档，未验证）

### 1. 根因判断

> `App.tsx` 用 `if (confirmTask) return` 强行中断了主界面渲染，而返回时只清了 `confirmTask`，没清 `activeTaskId` 和 Wizard 内部 step 状态，导致主界面重新渲染时向导组件以为还在「已完成」状态，于是再次把编辑器抛了出来。

### 2. 两套架构

| 方案 | 核心 | 改动量 | 优点 | 缺点 | 推荐 |
|---|---|---|---|---|---|
| **A 视图栈状态机** | App 顶层定义 `AppView = 'main' | 'confirm'`，用全局视图状态代替 `if(confirmTask) return` | 极小 | 0 依赖、逻辑极简、契合桌面端单任务流 | 无 URL、刷新丢视图 | ⭐⭐⭐⭐⭐ |
| **B 轻量 Hash 路由** | 监听 `location.hash`，`#/main/home`、`#/confirm/:taskId` | 中等 | 有明确 URL、可深链接、可恢复 | 心智负担、Tauri 刷新可能白屏 | ⭐⭐⭐ |

结论：推荐 **A**；将来需要深链接再平滑升级到 B。

### 3. 页面层级图

```text
App 根节点 (AppView 状态机)
├── [第一级] 主界面 (AppView === 'main')
│   ├── 左侧导航栏 (Sidebar)
│   └── 右侧内容区 (activeTab)
│       ├── 首页 (home) -> WizardPage (pick -> intent -> options -> running -> done)
│       ├── 任务列表 (tasks) -> TaskList
│       └── 其他 (settings 等)
└── [第二级] 确认页 (AppView === 'confirm' && activeTaskId)
    └── SimpleSubtitleEditor (独占全屏)
```

- 进入：WizardPage 的 done 点「改字幕」，或任务列表点「修改字幕」
- 返回：**必须重置** `AppView='main'` 且 `activeTaskId=null`

### 4. 代码骨架（外部建议）

```tsx
type AppView = 'main' | 'confirm';

const [appView, setAppView] = useState<AppView>('main');
const [activeTab, setActiveTab] = useState<string>('home');
const [activeTaskId, setActiveTaskId] = useState<string | null>(null);  // 单一数据源

const navigateToConfirm = (taskId: string) => { setActiveTaskId(taskId); setAppView('confirm'); };
const navigateBackToMain = () => { setAppView('main'); setActiveTaskId(null); };

if (appView === 'confirm' && activeTaskId) {
  return <SimpleSubtitleEditor taskId={activeTaskId} onBack={navigateBackToMain} />;
}
return <MainLayout activeTab={activeTab} setActiveTab={setActiveTab} onEditTask={navigateToConfirm} />;
```

要点：
- WizardPage 的 done 只展示结果与回调按钮，**内部不要再渲染编辑器**
- 确认页 props：`{ taskId, onBack, onGenerateVideo }`，只依赖 taskId 从后端拉数据

### 5. 外部列出的坑

1. **双重渲染与状态残留**：返回后确保 WizardPage 能感知 `activeTaskId` 为空并重置 step；或给主界面传 `key={activeTaskId || 'main'}` 强制重建
2. **卸载时并发任务**：点「生成视频」后返回，**不要中断后端请求**，任务在后台继续
3. **任务列表直达确认页**：TaskList 点任务直接 `navigateToConfirm(taskId)`；确认页只靠 taskId 拉数据
4. **刷新丢失**：方案 A 无 URL，刷新必回 main；若要恢复，可用 `sessionStorage` 存 `appView` + `activeTaskId`
5. **快捷键冲突**：确认页独占渲染时，`Ctrl+Z` 等监听要在 `useEffect` 里正确注册/卸载

---

## 二、我的核对（与当前真实代码的差异，实施前必读）

**1. 根因描述有一处偏差（结论仍正确）**

外部说「WizardPage 以为还在 done 状态、又把编辑器抛出来」。实际代码（App.tsx:352-367）是：

```tsx
{activeTab === 'home' && (
  <>
    <WizardPage onEditTask={(id) => { setActiveTaskId(id); setConfirmTask(id); }} ... />
    {activeTaskId && (
      <>
        <TaskProgress taskId={activeTaskId} />
        <div id="sub-editor"><SimpleSubtitleEditor taskId={activeTaskId} /></div>
      </>
    )}
  </>
)}
```

即：**主界面分支里显式写死了「有 activeTaskId 就再渲染一次编辑器」**，与 WizardPage 内部 step 无关。
返回时 `onClose={() => setConfirmTask(null)}` 只清 confirmTask，`activeTaskId` 残留 → 第二次渲染。
所以最小修复是 `onClose` 里同时 `setActiveTaskId(null)`；外部方案 A 的「单一数据源 + 统一返回函数」是更彻底的版本，方向一致。

**2. `MainLayout` 组件并不存在**

当前 App.tsx 是单文件内联渲染（titlebar / sidebar / content / statusbar 都写在同一返回值里）。
采用方案 A 时需要么把它提取成 `MainLayout`，么保留内联、只把 `appView` 判断放在最外层。**后者改动更小**。

**3. `key={activeTaskId || 'main'}` 这个「粗暴重建」要慎用**

它会连向导页里用户已选的参数、上传进度一起重建。当前场景可以接受（返回主界面本来就该是干净状态），
但若以后要「返回后继续上一次的向导选择」，就不能用 key 重建，得把向导状态提升到 App。

**4. 任务列表直达确认页 —— 目前 TasksPage 没有这个入口**

TasksPage 现在只有「详情 / 字幕」等操作，需要新增一个「改字幕」→ `navigateToConfirm(id)` 的接线；
这和「任务列表」页的 UI 一起改更合适。

---

## 三、待办切片（等用户拍板后执行，按依赖顺序）

- [ ] **T1 最小修复（半天内）**：`onClose` 同时清 `activeTaskId`；确认页返回后主界面不再堆叠
- [ ] **T2 单一数据源**：`appView` + `activeTaskId` 替代 `confirmTask`，抽出 `navigateToConfirm / navigateBackToMain`
- [ ] **T3 取消按钮**：确认页底部加「取消」= 放弃本任务（弹确认 → 归档进回收站，可恢复）→ 回主界面
- [ ] **T4 任务列表直达确认页**：TasksPage 增加「改字幕」入口，复用同一组件
- [ ] **T5 中文默认简体**：ASR 对 `zh` 加 initial_prompt；翻译目标为中文时提示词要求简体；`zh-TW` 保留为显式选项
- [ ] **T6（可选）刷新恢复**：`sessionStorage` 存 `appView` + `activeTaskId`

> T3/T5 与 T1/T2 无冲突，可并行；T4 依赖 T2 的统一跳转函数。

---

## 四、第二轮：可交互原型（外部 AI，2026-10-17，仍为存档）

### 原型要点

1. **纯净视图栈**：最外层 `appView === 'confirm' ? <确认页/> : <主界面/>`，彻底切断下层的 DOM 渲染树
2. **状态重置（核心）**：返回时除清 `activeTaskId`，还用 `key={wizardKey}` 强制重建 WizardPage
3. **统一入口**：向导完成态与任务列表两处都只调 `navigateToConfirm(taskId)`；确认页只靠 taskId 拉数据
4. **面包屑**：确认页顶部 `主界面 / 任务列表 / 确认字幕`
5. 技术栈：React 18 + Tailwind CDN + Babel 单文件 HTML（**仅供体验，未进入项目**）

### 核心状态机（摘录）

```tsx
const [appView, setAppView] = useState<'main' | 'confirm'>('main');
const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
const [wizardKey, setWizardKey] = useState(Date.now());

const navigateToConfirm = (id: string) => { setActiveTaskId(id); setAppView('confirm'); };
const navigateBackToMain = () => {
  setAppView('main');
  setActiveTaskId(null);
  if (activeTab === 'home') setWizardKey(Date.now());   // 强制重建向导页
};
```

### 我的核对（落地前必看）

| # | 问题 | 处理 |
|---|---|---|
| 1 | 原型用 Tailwind，项目用自定义 CSS（`.w-*` 类） | **只取结构，不搬样式** |
| 2 | 原型确认页是「假播放器 + 静态字幕行」 | 真实组件有词级时间戳 / 拆分 / 合并 / 撤销 / 播放器叠字 → **只换外层壳，不动编辑器内部** |
| 3 | 原型**仍然没有取消按钮** | T3 依然要做 |
| 4 | 面包屑写死「任务列表」 | 真实场景要按来源显示（向导 vs 任务列表） |
| 5 | `key` 重建 WizardPage 会丢向导状态 | 返回后向导回到 pick（可接受，但要写清楚） |
| 6 | 真实 App.tsx 没有 `MainLayout` 组件 | 落地只需在最外层加 `appView` 判断 + 清理 activeTaskId |

### 落地映射（真实代码位置，实施时照这个改）

| 现有代码 | 改成 |
|---|---|
| `App.tsx:281` `if (confirmTask) {` | `if (appView === 'confirm' && activeTaskId) {` |
| `App.tsx:285` `onClose={() => setConfirmTask(null)}` | `onClose={navigateBackToMain}` |
| `App.tsx:355` `onEditTask={(id) => { setActiveTaskId(id); setConfirmTask(id); }}` | `onEditTask={navigateToConfirm}` |
| `App.tsx:360-367` home 分支里的 `{activeTaskId && <><TaskProgress/><SimpleSubtitleEditor/></>}` | **整段删除**（这正是堆叠的直接来源） |
| `TasksPage` 无「改字幕」入口 | 新增按钮 → `onEditTask(task.id)` |

> 注意：`TaskProgress` 删除后，任务进度改由「任务列表」页或状态栏展示；确认页本身通过轮询 `getTaskStatus` 显示进度。

---

## 五、定稿原型（用户确认「基本是我想要的效果」，2026-10-17）

> 完整可交互文件：`docs/prototypes/confirm-page-final.html`（16.6 KB，双击浏览器打开）

### 它确定的交互（这就是要落地的目标）

1. **视图栈**：最外层 `appView === 'confirm' && activeTaskId ? <确认页/> : <主界面/>`，确认页独占渲染
2. **返回三重清理**：`appView='main'` + `activeTaskId=null` + `wizardKey(Date.now())` 强制重置向导
3. **统一入口** `navigateToConfirm(taskId)`：向导完成态「改字幕」、任务列表「修改字幕」都走它
4. **确认页只靠 taskId 拉数据**（不接收对象）
5. **面包屑**：`主界面 / 任务列表 / 确认字幕`，位于返回按钮右侧

### 原型没有覆盖的（实施时必须保留/补齐，别当成可以简化）

| 项 | 说明 |
|---|---|
| 取消按钮 | 原型确认页仍只有「保存草稿 / 确认无误，生成视频」→ T3 必须补 |
| 真实确认页能力 | 词级时间戳、拆分（Ctrl+Enter）、合并（并入上行/下行）、Action 栈撤销、播放器叠字与 seek、可疑行高亮 —— 原型是静态假行，**只换外层壳** |
| 侧边栏其余 5 项 | 原型只有「首页/向导」「任务列表」；真实项目还有 术语库 / 设置 / 插件 / 开放平台 / 帮助 |
| 任务列表现有功能 | 回收站、批量删除、拖动框选、撤销/彻底移除 —— 原型是极简表格，**不能因此删掉现有功能** |
| 运行时进度 | 原型用 setTimeout 模拟；真实由轮询 `/api/task/{id}` 驱动 |
| 状态栏 | 原型没有；真实有「后端服务运行中 · 队列 · 内存 · GPU」 |
| 样式体系 | 原型 Tailwind，项目自定义 CSS（`.w-*`）→ **只取结构，不搬样式** |

### 落地顺序（建议）

| 步 | 内容 | 依赖 |
|---|---|---|
| 1 | T2 视图栈：`appView` 取代 `confirmTask`；删掉 home 分支里重复渲染的 `TaskProgress + SimpleSubtitleEditor` | 无 |
| 2 | T1 返回三重清理（含 wizardKey） | 1 |
| 3 | T4 任务列表加「改字幕」→ `navigateToConfirm` | 1 |
| 4 | 面包屑（按来源显示） | 1 |
| 5 | T3 确认页「取消」按钮 | 1 |
| 6 | T5 中文默认简体（与本次重构无关，可并行） | 无 |
