# 校园头盔检测提醒助手 · 管理后台

Vue 3 + TypeScript + Vite 构建的校园骑行安全行为积分平台管理后台。

设计严格遵循 Apple HIG：素色背景、单一主色、清晰留白、无渐变、无毛玻璃、无花哨动效。

## 快速开始

```bash
npm install
npm run dev          # 开发服务器（默认 http://localhost:5173）
```

开发环境通过 Vite 代理把 `/api` 转发到后端 `http://127.0.0.1:8000`，
可在 `.env.local` 中通过 `VITE_API_PROXY_TARGET` 修改。

## 可用脚本

| 脚本 | 说明 |
| --- | --- |
| `npm run dev` | 启动开发服务器 |
| `npm run build` | 类型检查 + 生产构建 |
| `npm run preview` | 预览生产构建产物 |
| `npm run type-check` | `vue-tsc --noEmit` 类型检查 |
| `npm run lint` | ESLint 检查（零警告门槛） |
| `npm run lint:fix` | ESLint 自动修复 |
| `npm run format` | Prettier 格式化 |
| `npm run gen:api` | 从后端 `/openapi.json` 生成 TS 类型 |

## 目录结构

```
src/
├── api/            请求层：request.ts（Axios 拦截器）/ upload.ts / types.ts / auth.ts
├── components/     基础组件：StatCard / PageHeader / DataTable / EmptyState /
│                   EvidenceViewer / ErrorBoundary
├── layouts/        AppLayout.vue —— 侧边栏 + 顶栏 + 内容区
├── router/         路由表 + 权限守卫
├── stores/         Pinia：app（主题/侧边栏/点位）/ auth（令牌/用户/角色）
├── styles/         设计令牌 + 基础样式 + Element Plus 主题覆写
└── views/          页面：login / dashboard / events / reviews / points / settings / error
```

## 设计令牌

所有颜色、间距、圆角、字号、动效时长统一来自 `src/styles/design-tokens.scss`，
组件中禁止出现魔法值。暗色模式通过 `prefers-color-scheme` 自动生效，
也可在设置页手动切换（写入 `data-theme` 属性）。

核心色板：

| 令牌 | 值 | 用途 |
| --- | --- | --- |
| `--color-primary` | `#007AFF` | 选中、主按钮、链接 |
| `--color-success` | `#1F9D46` | 合规、已通过 |
| `--color-danger` | `#D92D20` | 违规、驳回、失败 |
| `--color-warning` | `#FF9500` | 待处理、提醒 |

中性灰阶：`--color-bg #F7F7F9` / `--color-surface #FFFFFF` /
`--color-surface-2 #F2F2F7` / `--color-text #1C1C1E` / `--color-text-2 #6E6E73`。

圆角：卡片 `18px`、按钮 `14px`、输入框 `10px`。
阴影仅一层：`0 1px 8px rgba(0,0,0,0.06)`。

## 请求层约定

- 后端统一响应包络 `{ code, data, message }`，拦截器自动解包 `data`
- `code !== 0` 或 HTTP 4xx/5xx 一律抛出 `ApiError`，携带 `traceId` 与字段级错误
- 401 自动触发刷新令牌并重放原请求；并发 401 共享同一个刷新 Promise
- 组件中禁止硬编码 API 路径，统一收敛到 `src/api/*.ts`

## 角色权限

| 角色 | 权限范围 |
| --- | --- |
| `super_admin` | 全部（`*`） |
| `admin` | 总览、事件、审批、积分 |
| `reviewer` | 总览、事件、审批 |
| `observer` | 总览、事件（只读） |

侧边栏菜单由路由表 `meta.roles` 自动过滤生成，未授权路由跳转 403。

## 类型生成

后端就绪后执行：

```bash
npm run gen:api
```

从 `http://127.0.0.1:8000/openapi.json` 生成 `src/api/generated/schema.ts`。
后端不可达时脚本优雅失败（exit 0），不阻塞开发。
