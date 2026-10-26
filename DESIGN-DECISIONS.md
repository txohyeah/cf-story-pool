# 方向 A：追踪器控制台

## 设计计划（实现前）
面向三人团队日常追踪需求、修复和验证。沿用现有工作流与 DOM hooks。

基础 palette 六色：Canvas 冷白 `#f6f8fb`、Surface 白 `#ffffff`、Graphite 石墨 `#202936`、Muted 蓝灰 `#647184`、Divider 分隔 `#dce2ea`、Action 钴蓝 `#315fbb`。语义色为独立的功能 token，见下表。

字体角色：标题用系统 UI sans，600–700 字重、紧凑字距；中文正文用 PingFang SC / Microsoft YaHei / sans-serif；机器信息用 ui-monospace / SFMono-Regular / Consolas。无字体下载。

布局：顶部横向入口与项目上下文，左侧个人工作项，右侧高密度筛选和需求行；窄屏列表先行，工作项随后。详情在右侧连续工作面打开，保留所有交互。

```
[需求池 | 需求 文档 版本 用例 导出 | 数据包 项目 账户]
[我的工作项  ] [项目 状态 类型 紧急 级别 标签 版本 搜索]
[待办/进行中 ] [#ID  标题                      · 状态]
[           ] [类型 / 标签 / 版本               日期]
```

Signature：需求行的等宽编号定位槽，悬停/键盘聚焦时出现细钴蓝左轨；服务于快速扫单和回到正在处理的行，不增加装饰模块。

## 实现前俗套自评
排除暖奶油＋衬线＋赤陶，排除近黑＋荧光绿，排除报纸式密集分栏与满屏细线。控制台的细线仅划分数据、控件和上下文；保留小圆角、中文无衬线、真实工作流。保留七种状态语义，避免把所有徽章统一成品牌蓝。

## 状态色映射
| 类/语义 | 前景 | 识别方式 |
| --- | --- | --- |
| st-submitted 待确认 | #986515 黄褐 | 空心圆点，需注意 |
| st-confirmed 已确认 | #315fbb 蓝 | 实心圆点，信息 |
| st-scheduled 已排期 | #6552aa 蓝紫 | 实心圆点，计划；承接原紫色 |
| st-fixed 已修复 | #137c78 青绿 | 实心圆点，待验证 |
| st-verified 已验证 | #267347 绿 | 实心圆点，成功 |
| st-closed 已关闭 | #526e5b 灰绿 | 实心圆点，完成；降低饱和度 |
| st-dup_closed 重复关闭 | #637083 灰 | 空心圆点，中性终结 |
| ty-bug / ug-urgent | #b5383d 红 | 细底边，危险 |
| ty-req / ty-opt | 蓝 / 灰 | 细底边 |
| severity 关键 / 重大 / 一般 / 观察 | #b91c1c / #c2410c / #a16207 / #64748b | 保留原映射，改为前景＋细底边 |
| rel-chip | #7052aa 紫 | 版本编码等宽 |
| tag-chip | 石墨/浅灰 | 次级标签 |

closed 从中性灰调为灰绿遵循本次成功系要求；重复关闭保持中性。状态文本始终存在，颜色不是唯一识别依据。

## 改动清单与范围决策
- `dist/style.css`：在公共样式尾部集中放置方向 A token 和组件层，覆盖旧样式；保留既有类名契约，避免散布选择器迁移。新增响应式、键盘焦点、reduced-motion；收紧圆角，移除顶栏、项目卡和抽屉的堆叠阴影。
- `dist/index.html`：筛选区含版本下拉全部保留；工作项侧栏、列表编号、分页、详情和事件统一视觉；严重级别以原颜色前景替代色块。只改渲染字符串内 markup，所有判断、API 和对象表达式不变。
- `dist/new.html`：增加提单页上下文标题和五个导航入口，表单、上传、压缩和 iframe 顶栏隐藏逻辑不变。
- `dist/releases.html` / `dist/testcases.html` / `dist/docs.html`：统一工具条和主导航，当前入口以 aria-current 标识；编码日期等宽。用例页样式收归公共 CSS，保留 `.detail.open` 展开契约。
- `dist/login.html`：移除渐变与阴影，使用同一套冷白、钴蓝、无衬线/mono；补充用户名/密码的可访问名称。登录脚本未改。
- `dist/app-common.js`：仅给三个弹窗的模板添加公共类。renderProjectBar、pool_project localStorage、项目切换、上传和确认回调代码完全不变。
- 去除 index、docs、testcases 的重复 app-common.js 标签，各自仅载入一次，避免重复注册全局监听。
- 次级页新增「导出」入口回到既有需求筛选/导出工作流；不复制 CSV 实现、不新增 API。需求页原直接导出按钮不变。登录页保留独立入口布局。
- 不新增外部依赖、不访问网络，不修改 worker、vendored JS、verify_live.py，不 commit。开始工作时已有的未跟踪数据和报告未改。

## DOM hooks 自审与 grep 证据
全站（包含未改动的 doc.html）扫描 `$()`、getElementById、querySelector(All)、classList 和 closest；对照 HEAD 的 ID 声明、动态 `.id =`、选择器引用。ID 集合没有删除，选择器引用集合完全相同；每个字面量 ID 均在同页模板或公共组件有对应声明。公共组件的 f-project / proj-sel 是既有跨页可选回退，两个目标分别由 index 和次级页提供。动态 containerId 通过各页 `renderProjectBar('g-bar', …)` 手工回查。

执行命令：
```sh
rg -n 'getElementById|querySelector|querySelectorAll|classList|closest\(' dist/app-common.js dist/*.html
rg -n 'app-common.js' dist/*.html
rg -n 'f-release|g-bar|pool_project|dr-prev|dr-next|dr-close|pinfo|ck-as|row-item' dist/app-common.js dist/index.html dist/testcases.html
```

第二条实际输出（去重后）：
```text
dist/index.html:205:<script src="/app-common.js"></script>
dist/testcases.html:55:<script src="/app-common.js"></script>
dist/releases.html:63:<script src="/app-common.js"></script>
dist/docs.html:48:<script src="/app-common.js"></script>
```

扫描/集合对照输出摘要（独立字面量 ID 数，非调用次数）：
```text
index.html     65 hooks  removed targets=0  unresolved=0  class hooks unchanged
new.html       20 hooks  removed targets=0  unresolved=0  class hooks unchanged
releases.html  15 hooks  removed targets=0  unresolved=0  class hooks unchanged
testcases.html 26 hooks  removed targets=0  unresolved=0  class hooks unchanged
docs.html       9 hooks  removed targets=0  unresolved=0  class hooks unchanged
login.html      4 hooks  removed targets=0  unresolved=0  class hooks unchanged
doc.html       22 hooks  removed targets=0  unresolved=0  class hooks unchanged
app-common.js  24 hooks  removed targets=0  unresolved=0  class hooks unchanged
```

关键 grep 人工回查：
- `f-release` 存在于静态 select、筛选事件数组、原有导出/列表/工作项参数以及版本选项渲染中，均未改。
- `g-bar` 在各主页面存在，renderProjectBar 调用和 PKEY=`pool_project` 原样保留。
- `dr-prev/dr-next/dr-close` 声明与 onclick 配对，`pinfo` 声明与分页 textContent 配对。
- 用例关联链接仍使用 `/testcases.html` 与 `/index.html?project=…&req=…` 原路径；未触动抽屉关联代码。
- `.x`、`.ck-as`、`.chk-dot`、`.todo/.doing/.done`、`.row-item`、`.open`、`.noscroll` 全部保留声明/模板与事件引用。
- API、JSON、FTS 防抖、筛选判断、分页参数、状态机、图片压缩等非 markup 代码逐段 diff 复核无改动。

## 自检结果
```sh
diff worker_src/_worker.js dist/_worker.js
# stdout: 空；exit 0

git diff --exit-code -- worker_src/_worker.js dist/_worker.js verify_live.py dist/marked.min.js dist/purify.min.js
# stdout: 空；exit 0

node --check dist/app-common.js
# stdout: 空；exit 0

git diff --check
# stdout: 空；exit 0
```
另将全站 HTML 的每个内联 script 提取到临时 JS，逐个 `node --check`，全部通过。未运行 verify_live.py：本任务无网络，且该文件仅覆盖 API，不承担视觉验收。

## 实现后自我批判与修正
1. 第一轮顶栏保留过多图标，削弱工程追踪器的扫描效率；已去除需求/文档/版本/用例/导出的装饰 emoji，保留明确要求的「📦 数据包」及既有数据语义图标。
2. 仅给编号等宽不够，日期、版本、分页、计数与关联编码也已接入 mono；不把全文切成等宽，保留中文阅读效率。
3. 第一轮未处理 380px 以下表单 min-width，已补小屏堆叠，长筛选区允许换行；顶栏窄屏取消 sticky，避免多行导航持续占据阅读面。
4. 状态七色保留并使用文字和圆点形态辅助识别；重复关闭与成功关闭不合并。闭环完成态采用低饱和灰绿，既满足成功语义，也压低已完成项权重。
5. 本轮使用系统字体，无网络字体和外部依赖；字体实际字形随操作系统变化，是有意接受的部署约束。
6. 视觉截图未完成：尝试本地 Chromium headless（file://，禁用后台网络，临时 profile），启动被沙箱 `setsockopt: Operation not permitted` 阻断。没有冒充浏览器验收；窄屏、实际数据下的溢出和抽屉操作仍建议由韩立或用户浏览器复核。以上通过项为静态审计和语法检查，不等同于端到端功能验证。
