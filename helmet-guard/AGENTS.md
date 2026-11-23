# AGENTS.md — 校园头盔检测提醒助手

## 项目一句话描述
面向师生的校园骑行安全行为积分平台：边缘侧 YOLOv8 检测骑行者头盔佩戴状态，
后端完成身份绑定与 AI 分级决策，管理员审批后生效，学生在小程序查看积分、申诉与奖励。

## 目录结构
    ```
helmet-guard/               # 后端 + 采集进程（Python），本仓库的发布主体
├── app/
│   ├── api/           # 路由层（v1）
│   ├── core/          # 配置、异常、依赖注入、日志、OpenAPI 元信息
│   ├── domain/        # 纯领域逻辑（无 I/O）
│   ├── services/      # 业务服务
│   ├── repositories/  # 数据访问
│   ├── models/        # ORM 模型
│   ├── schemas/       # Pydantic 出入参
│   ├── workers/       # Celery 异步任务
│   └── ai/            # 模型封装、LLM 客户端
├── tests/
├── scripts/           # 运维与文档导出脚本
├── migrations/        # Alembic 迁移
├── Sql/               # MySQL 建库脚本
├── docs文档/          # 设计与文档（含生成的接口文档.html）
├── .github/workflows/ # CI：ruff / mypy / pytest
├── pyproject.toml
└── AGENTS.md          # 本文件（项目宪法）
```

> **仓库范围**：本仓库仅发布后端 `helmet-guard/`。管理端（`admin-web/`）与
> 微信小程序（`miniprogram/`）源码保留在本地工作区，不进入版本库。
> `design.md`（前端视觉与交互规范）同理，随前端项目一并留在本地。
> 二者的前端改动仍须遵守本文件「前端视觉与交互（强制）」章节的全部约束。


## 文档体系（各司其职，冲突时按此优先级）

| 文档 | 职责 | 优先级 |
|---|---|---|
| `AGENTS.md`（本文件） | 项目宪法、不可违反原则、数据安全红线 | 🔴 最高，任何文档不得与之冲突 |
| `design.md` | 前端视觉与交互规范（色彩/排版/布局/组件/文案）；随前端项目留在本地 | 🔴 前端改动的前置必读 |
| `docs文档/校园头盔检测提醒助手-项目深度分析与研发设计说明书.md` | 需求、架构、数据模型、算法方案、路线图 | 🟠 业务与后端依据 |
| `docs文档/Cursor开发提示词全集.md` | 分阶段实现提示词 | 🟡 执行手册（视觉部分以 `design.md` 为准） |
| `docs文档/接口文档.html` | 可视化接口文档（由 `scripts/export_api_docs.py` 生成） | 🟡 对外交付物 |

## 不可违反的原则

1. **证据优先**：任何处罚必须绑定可追溯证据（帧 + 框 + 置信度 + 推理依据）。
2. **三态保守**：检测结果只有 `helmeted / bare / unknown`。证据不足一律 `unknown`，
   **绝不猜测**。行人裸头不得判 `bare`。
3. **人工兜底**：AI 决策全部进入审批队列。自动生效需白名单配置且受熔断器约束。
4. **身份不足不惩罚**：身份置信度 < 0.60 的事件不得进入处罚决策，只进待识别池。
5. **正向激励**：积分、排行、勋章、商城与惩罚同等重要，不得只做惩罚。
6. **隐私最小**：默认**不做人脸识别**。身份靠「车辆登记 + 账号绑定」。
  仅在学生明确点选、且仅在登录场景，可选用微信官方安全注册插件
  （provider `wxc7b7f914565de923`，类目 `工具->办公`，`manifest.json → mp-weixin.plugins.loginplugin`，
  用到登录的页面经 `pages.json → mp-weixin.usingComponents.login = plugin://loginplugin/login` 注册后，
  以 `<login :modal @success @fail @cancel>` 单入口承接授权）做头像昵称快速验证；
  插件只取必要字段（`avatarUrl / nickName` 仅展示预填，`openid / phone_code → 手机号` 仍走后端三件套），
  人脸 / 身份证影像不落库、不透传后端。证据图片仍加密存储、访问留痕、90 天自动过期删除。
  未点选插件时走自建官方三件套（`code2session / getPhoneNumber / checkSessionKey`）。
7. **学生可申诉**：每条处罚都有申诉入口，申诉需人工二次处理。
8. **最小权限**：学生只能看自己的数据；管理员分角色（RBAC）。

## 现有代码中必须保留的优秀实践（不要"顺手重构"掉）

- `app/vision.py` — 权重类别守卫（拒绝 COCO 通用权重），防止用错模型
- `app/selfcheck.py` — 模型 pin 单例；三层推理名额控制（非阻塞 + shield + 正确释放）
- `app/store.py:apply_review` — 条件 UPDATE + 幂等语义，并发安全
- `app/tracks.py` / `app/selfcheck.py:decide_status` — 纯函数判定逻辑
- `app/db.py` — 参数化 SQL + 短事务 + WAL
- `app/seed_demo.py` — live 库写入保护
- `app/main.py` — 心跳驱动的健康检查（不猜测文件状态）
- `miniprogram/src/pages/index/index.vue` — 严格状态机 + 请求序号防竞态
- `miniprogram/src/utils/selfcheck.ts` — 响应清洗（sanitize）与错误码映射
- `helmet-guard/dataset/` — **数据集是完整的，禁止删除/覆盖/重新解压**
  （原始 zip 在 `E:\AI办公比赛\bisai\数据集\`，同样禁止动）

## 数据安全红线（任何阶段都适用）

1. **绝不删除或覆盖** `E:\AI办公比赛\bisai\数据集\*.zip` 原始压缩包。
2. **绝不解压 zip 覆盖 `helmet-guard/dataset/`** —— 该目录数据完整
   （ebike_helmet_v2: train 1930 / valid 467 / test 289；
   roboflow_motorcycle: train 1110 / valid 105 / test 53），
   图片与标签一一对应。历史上曾误判其"已丢失"，导致重复解压风险。
3. 审计脚本对 `dataset/` **只读**，产物只能写入 `docs文档/` 与 `scripts/`。
4. `dataset/` 保持在 `.gitignore` 中，不入库（数据集体量大）。
5. `data.yaml` 的 split **目录名**为 `valid`（非 `val`），**不要改名**；
   但 `data.yaml` 内的 **键名** `val:` 是 YOLO 标准键，不得改成 `valid:`。
   两者指向同一目录，改任一处都会导致 YOLO 找不到数据。
6. 类别 id 映射已实测固化在 `data.yaml` 注释与 `docs文档/数据说明.md`：
   ebike_helmet_v2 = `0 Cyclists / 1 helmet / 2 no helmet`；
   roboflow_motorcycle = `0 helmet / 1 no helmet`。
   **两个数据集的 id 不可互换**，合并训练前必须重映射。
7. 训练冒烟测试必须写入 `runs/` 下的**新建**子目录，不得覆盖既有权重
   （`runs/` 已被 `.gitignore` 排除，产物不入库）。

## 开发流程要求

每个功能模块的实现必须遵循：
1. **先读**：动手前必须阅读相关既有代码，理解现有约定后再动手。
2. **先设计**：涉及多文件或跨层改动时，先输出设计方案（分层归属、接口签名、
   数据流、边界情况），确认后再写代码。
3. **小步提交**：每完成一个可验证单元就自检一次，不要一次写 2000 行再调试。
4. **配测试**：领域逻辑必须配套单元测试，测试与实现同时产出。
5. **自检**：完成后运行 ruff / mypy / pytest，必须全绿，并报告结果。
6. **汇报**：列出改动的文件、关键决策、取舍理由、遗留问题。

## 代码风格

- Python：类型注解齐全、ruff + mypy strict、异常分层、无裸 except
- 前端：TypeScript strict、组件 props/emits 完整、无 any、样式用设计令牌
- 注释只写「为什么」，不写「是什么」
- 禁止 `TODO` 占位、禁止注释掉的代码、禁止 `pass` 桩函数

## 前端视觉与交互（强制）

**本地工作区根目录 `design.md`（随前端项目保留在本地，不入库）是前端视觉与交互的唯一事实来源。**

涉及任何前端改动（`admin-web/` 与 `miniprogram/`）时，动手前必须先读 `design.md`，
并遵守以下硬性约束（摘要，详细规格见 `design.md`）：

1. **令牌唯一来源**：所有颜色 / 间距 / 圆角 / 字号 / 字重 / 动效时长必须引用
   `admin-web/src/styles/design-tokens.scss`（或小程序 `styles/tokens.scss`）中的变量，
   禁止在组件里写原始色值或魔法数值。
2. **一屏最多 3 种色相**（主色 + 1 状态色 + 中性）；状态色只用于小面积
   （色点 / 徽章 / 图标底 / 左边条），禁止大面积色块填充。
3. **禁止**：渐变（`linear-gradient` / `radial-gradient`）、多层阴影、毛玻璃
   （`backdrop-filter`）、`!important`、emoji 作为功能图标、
   超过 4 级的文字层级、移动端小于 44px 的触控目标、超过 350ms 的动画。
4. **文字层级最多 4 级**：大标题 32 / 卡片标题 17 / 正文 15 / 脚注 13
   （辅助标签 12）。
5. **三态必备**：每个页面与列表都必须有 loading（骨架屏）/ empty（空态组件）/
   error（重试）三态；空态文案不得出现「无数据」「null」等技术词。
6. **数值对齐**：所有指标、分值、置信度、百分比使用 `font-variant-numeric: tabular-nums`。
7. **组件内 `<style>` 块不超过 100 行**，超过必须抽到独立 `.scss`。
8. **领域配色与文案**（详见 `design.md` §11）：
 - 头盔 `unknown` 状态用**中性灰**，绝不用红色（未知不是错误）；
 - 指标卡趋势颜色由 `tone` 决定而非方向（佩戴率↑ 是好事，违规数↑ 是坏事）；
 - 学生端文案禁用「违规 / 处罚 / 罚款 / 扣钱 / 记过 / 通报批评个人」，
     统一用「待确认提醒 / 积分变动 / 安全记录」等表述。
9. **证据优先（与原则 1 呼应）**：审批与记录详情**必须展示证据帧 + 检测框叠加**，
   检测框使用归一化百分比定位，容器 `aspect-ratio` 必须等于后端返回的
   `image_width / image_height`（横竖图都要正确对齐）。
10. **小程序原生优先（2026-11-18 新增，2026-11-20 修订 v3）**：tab 三页（首页/头盔自查/我的）
  用 `navigationStyle: custom` 做沉浸式顶栏（原生「首页」大标题会压住问候语，故取消），
  页内首部必须放 `.nav-spacer` 占位（高度 = 状态栏 + 胶囊 + 8px，胶囊经
  `uni.getMenuButtonBoundingClientRect()` 动态避让、不硬编码）；
  `auth` 表单页保留原生导航栏（需要系统返回）；页面内仍**禁用品牌条 /
  大插画视觉区 / Hero 大标题 + 流式副标题 / Landing 页结构**；
  登录页只保留「步骤指示 + 功能卡片 + 协议行」；
  启动页（launch）由微信统一提供，**不自定义**（见微信设计指南 Launch Page Loading）；
  每页只讲一个重点、减少输入（优先 `getPhoneNumber` / `picker` / `chooseAvatar` 代替手输，
  禁止 Web 式登录页写法）；
  局部加载优先、谨慎使用全屏模态加载；触控目标 ≥44px（关键操作 ≥88rpx 点击区，
  视觉可小但热区不小）；底部固定操作必须用 `env(safe-area-inset-bottom)` 适配安全区，
  胶囊区用 `wx.getMenuButtonBoundingClientRect()` 动态避让、不硬编码；
  原生 `tabBar` 图标只用项目内本地 PNG（禁用网络图/SVG/iconfont/emoji），
  需超原生能力才用自定义 `tabBar`；字体只用系统字体（禁用远端/第三方字体）；
 禁用 `backdrop-filter` / 复杂 `clip-path` / `:has()` / 容器查询 / 滚动驱动动画 /
 Three.js/WebGL/GSAP/视差/鼠标 hover 式交互作为核心视觉；
 高级交互只允许 `design.md` §9.8.2 的 A–I（按压回弹/弹性开关/成功勾选/数字滚动/
 骨架落位/松手回弹/吸顶分类/滚动渐显/数据生长），视差头图/毛玻璃收起/下拉讲故事/
 水波/爆散/液态滑块/GSAP scrubbed 一律不做，用前必过 §9.8.1 三问；
 真机（Android + iPhone）与体验版为准，HTML 原型不得冒充最终效果；
  可选链 `?.` / `??` 与 TDesign `::after` 覆盖须按 `miniprogram-development/pitfalls.md` 预检。

### 五条高级感铁律（v1.1，强制）+ 高级交互库（v1.4，强制）

以下五条是「一眼看出高级」与「一眼看出普通」的分界线，任何前端改动不得违反
（详细规格见 `design.md` §1.5）：

| # | 铁律 | 硬性要求 | 章节 |
|---|---|---|---|
| ① | **微明色阶层级** | 卡片 / 面板 / 弹窗 / 抽屉 / 侧边栏 / 列表项**一律不得用 1px 边框表达层级**，改用 `surface` 色阶（相邻级明度差 ≥ 2%）。1px 边框白名单仅限：输入框、表格行、焦点环、Tooltip。 | §3.2 |
| ② | **暗色字重 -40** | `font-weight` 必须走 `var(--font-weight-*)` 令牌，禁止字面量。暗色模式下 semibold 600→500、bold 700→600（**最多降一档**），并加 `letter-spacing: +0.1px`。不得靠降低 opacity 减重。 | §4.3 |
| ③ | **流式输出逐字 blur** | AI 流式文本逐字从 `blur(4px)` 晕开（180ms，每字延迟 12–16ms），禁止整段淡入冒充流式。中文按字切分、英文按词切分；同时存在动画的字符节点 ≤ 200，超出降级为逐词。`prefers-reduced-motion` 下完全禁用 blur。 | §9.3 |
| ④ | **数字 tabular-nums 锁死** | 在 `reset.scss` 全局开启 `font-variant-numeric: tabular-nums` + `font-feature-settings: 'tnum' 1, 'lnum' 1`，**组件内不得关闭**。普通数字用正文字体 + tabular，**不得**用等宽字体渲染（仅 ID / 车牌 / 代码用等宽）。 | §4.4 |
| ⑤ | **双阻尼物理** | 吸附 / 抽屉 / 展开 / Tab 指示条 / 归位用**过阻尼** `--ease-overdamped`（无过冲）；点赞 / 收藏 / 审批通过 / 成功徽章用**欠阻尼** `--ease-underdamped`（回弹 scale ≤ 1.12、位移 ≤ 4px、只回弹 1 次）。禁止直接使用 `cubic-bezier` 字面量与默认 spring 参数。 | §9.2 |
| ⑥ | **高级交互库（仅 A–I）** | 可用动效只有 `design.md` §9.8.2 的 9 个（A 按压回弹 / B 弹性开关 / C 成功勾选 / D 数字滚动 / E 骨架落位 / F 松手回弹 / G 吸顶分类 / H 滚动渐显 / I 数据生长）。视差头图 / 毛玻璃收起 / 下拉讲故事 / 水波 / 爆散 / 液态滑块 / GSAP scrubbed 一律不做；用前必过 §9.8.1 三问；`reduced-motion` 下直接出终态。 | §9.8 |

新增前端组件或页面后，同步更新 `design.md` 的「与现有代码的对应关系」表。

## 交付要求

每个阶段交付时必须给出：
- 变更文件清单与职责说明
- 关键设计决策与取舍理由
- 测试覆盖情况（新增测试数、覆盖率变化）
- 已知的限制与后续计划
