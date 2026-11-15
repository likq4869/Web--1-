# 校园头盔检测提醒助手 —— Cursor AI 开发提示词全集

> 版本：v1.0
> 日期：2026-11-15
> 目标：使用 Cursor 逐阶段、逐步骤地实现本项目，达到**企业级工程水准**
> 配套文档：`校园头盔检测提醒助手-项目深度分析与研发设计说明书.md`（唯一事实来源）

---

## 目录

- [第 0 部分：使用说明（必读）](#第-0-部分使用说明必读)
- [第 1 部分：全局约束（所有提示词都生效）](#第-1-部分全局约束所有提示词都生效)
- [第 2 部分：项目宪法（AGENTS.md 全文）](#第-2-部分项目宪法agentsmd-全文)
- [第 3 部分：P0 阶段提示词（工程基座）](#第-3-部分p0-阶段提示词工程基座)
- [第 4 部分：P1 阶段提示词（身份识别）](#第-4-部分p1-阶段提示词身份识别)
- [第 5 部分：P2 阶段提示词（决策与积分）](#第-5-部分p2-阶段提示词决策与积分)
- [第 6 部分：P3 阶段提示词（Vue3 管理后台）](#第-6-部分p3-阶段提示词vue3-管理后台)
- [第 7 部分：P4 阶段提示词（小程序改造）](#第-7-部分p4-阶段提示词小程序改造)
- [第 8 部分：P5 阶段提示词（模型精度）](#第-8-部分p5-阶段提示词模型精度)
- [第 9 部分：P6 阶段提示词（通知触达）](#第-9-部分p6-阶段提示词通知触达)
- [第 10 部分：前端视觉规范（Apple HIG 设计系统）](#第-10-部分前端视觉规范apple-hig-设计系统)
- [第 11 部分：质量门禁与验收提示词](#第-11-部分质量门禁与验收提示词)
- [第 12 部分：排错与重构提示词](#第-12-部分排错与重构提示词)
- [附录 A：Cursor 工作流操作手册](#附录-a cursor-工作流操作手册)
- [附录 B：提示词速查表](#附录-b提示词速查表)

---

## 第 0 部分：使用说明（必读）

### 0.1 本文档的正确使用方式

1. **先建立项目宪法**（第 2 部分），把 `AGENTS.md` 放到仓库根目录。Cursor 会自动读取它，后续所有提示词都在这个约束下执行。
2. **按阶段顺序推进**，每个提示词框的内容**整段复制**到 Cursor Chat。
3. **一次只喂一个提示词框**。不要把多个模块的提示词一次性粘进去——Cursor 会串味，产出质量急剧下降。
4. **每次执行完一个提示词框，要求 Cursor 汇报**：
   > "列出本次改动的文件清单、每个文件的职责、关键设计决策、以及你做的取舍。不要省略。"
5. **验收不通过就重喂**，并在提示词前加：
   > "上一次实现存在以下问题：[具体描述]。请在保留正确部分的前提下修复，不要推倒重来。"

### 0.2 绝对禁止事项

| 禁止 | 原因 |
|---|---|
| ❌ 一次性让 Cursor "实现整个项目" | 必然产出垃圾代码，无法维护 |
| ❌ 不看 diff 就接受 AI 的代码 | 错误会累积，后期无法收拾 |
| ❌ 允许 Cursor 自行引入新依赖 | 依赖膨胀、版本冲突、审计困难 |
| ❌ 允许 Cursor 修改已通过测试的既有模块 | 回归风险 |
| ❌ 跳过 P0 直接做业务功能 | 基座不牢，后面全是返工 |
| ❌ 用 `TODO` / `pass` / `NotImplementedError` 占位 | "半成品"是最大的代码质量杀手 |

### 0.3 项目当前真实状态（务必让 Cursor 知道）

```yaml
现状:
  后端: FastAPI + SQLite + 裸 SQL，已实现 health/sources/stats/events/review/alerts/self-check
  采集: detect.py 单进程单摄像头，YOLOv8 track，跨帧投票判定，写 passes/events
  算法: tracks.py（纯函数）+ selfcheck.py（模型 pin + 三态判定 + 推理名额控制）
  前端: miniprogram/ = UniApp 微信小程序（Vue3 + TS），仅"拍照自查"单页
  缺失:
    - 无 Git 仓库
    - 无 requirements.txt / pyproject.toml
    - 无 README.md
    - 无 Vue3 管理后台（admin-web/ 不存在）
    - 无数据库业务表（仅 6 张表）
    - 无认证鉴权
    - 数据集图片/标签已丢失（仅剩 .cache）
  模型: YOLOv8n，20 epoch CPU 训练，mAP50=0.457 recall=0.425 precision=0.696
```

---

## 第 1 部分：全局约束（所有提示词都生效）

以下约束通过 `AGENTS.md` 注入，此处重复列出以便在单个提示词框内也能生效。

### 1.1 代码质量红线

```
【类型与静态检查】
- Python 3.11+，全部函数/方法必须带完整类型注解（含 -> 返回值）
- 禁止裸 except；必须 except SpecificError as e 且 e 必须被使用或记录
- 禁止 type: ignore 无注释理由；禁止 # noqa 无规则编号
- 使用 mypy strict 模式，必须零错误
- 使用 ruff，配置 select = ["E","F","W","I","N","UP","B","SIM","C4","RET","ARG"]
- 前端 TypeScript strict: true，禁止 any（确需时用 unknown + 类型守卫）

【分层架构（强制）】
router/api 层  →  只做 参数解析 + 权限校验 + 调用 service + 序列化响应
service 层     →  业务编排 + 事务边界 + 领域规则
repository 层  →  只做 SQL/ORM，禁止包含业务判断
domain 层      →  纯函数领域逻辑（判定、决策、融合），零 I/O，可单测
- 任何业务规则不得写在 router 函数体内
- 任何 SQL 不得出现在 service 层（除复杂聚合外，必须走 repository）

【命名】
- 模块/函数/变量：snake_case；类：PascalCase；常量：UPPER_SNAKE_CASE
- 布尔量用 is_/has_/can_/should_ 前缀
- 不要用无意义缩写（cfg 保留，tmp/env/db 可接受）

【注释】
- 只解释「为什么」，不解释「是什么」
- 每个公开模块顶部写明：职责、依赖、边界约束
- 被注释掉的代码必须删除
- docstring 用 Google 风格（Args/Returns/Raises）

【错误处理】
- 定义领域异常层级：AppError -> NotFoundError/ValidationError/ConflictError/
  PermissionDeniedError/ExternalServiceError
- API 层统一捕获并转 HTTP 响应，绝不把堆栈泄漏给客户端
- 错误信息对用户友好，对开发者可追溯（附 trace_id）
- 外部调用（LLM/OCR/微信 API）必须有超时 + 重试 + 降级路径

【并发与事务】
- 写操作使用显式事务边界，失败必须回滚
- 积分台账（ledger）只增不改，纠错通过反向流水
- 幂等接口使用 Idempotency-Key
- 锁的获取/释放必须在同一函数内，用 try/finally 保证释放
- 跨线程/跨进程共享状态用 Redis，不可用进程内字典

【安全】
- 所有 SQL 参数化，禁止字符串拼接（WHERE 子句拼值必须用占位符）
- 用户输入一律 Pydantic 校验 + 长度/格式/范围约束
- 文件上传：校验 magic bytes（不用后缀名）、限大小、限像素数、随机化存储名
- 敏感字段（手机号/身份证/车牌）在日志中脱敏
- 密钥/密码用 pydantic-settings 从环境变量读，绝不硬编码
- 越权检查必须在 service 层强制，不能只靠前端隐藏
- 审计日志覆盖所有写操作 + 所有证据访问

【测试】
- 新增业务逻辑必须同时提交单元测试
- 领域层目标覆盖率 ≥ 90%，整体 ≥ 70%
- 测试命名：test_<单元>_<场景>_<期望>
- 测试必须确定性（固定随机种子、禁止真实网络调用）
- 禁止 sleep 等待，用事件/条件变量
"""

### 1.2 前端专项约束

```
【Apple HIG 风格（强制）】
- 克制：不用渐变、不用阴影堆叠、不用毛玻璃、不用花哨动效
- 层级靠留白和字重建立，不靠颜色堆砌
- 色彩：中性灰阶为主，仅用 1 个主色 + 3 个语义色
- 圆角统一（卡片 18px / 按钮 14px / 输入 10px），禁止随意圆角
- 阴影：最多 1 层，y=1 blur=8 opacity=0.06
- 动效：只用于状态切换，时长 200-300ms，缓动 cubic-bezier(0.4,0,0.2,1)
- 禁止：emoji 堆砌、渐变文字、霓虹色、玻璃拟态、巨大圆角、气泡按钮
- 所有触控目标 ≥ 44×44pt
- 文字层级最多 4 级（大标题 32 / 标题 17 / 正文 15 / 脚注 13）
- 支持深色模式（prefers-color-scheme），颜色用 CSS 变量

【组件规范】
- 禁止在 .vue 文件里写超过 100 行的 <style>（必须抽到独立 scss + 变量）
- 禁止使用 !important（除非第三方样式覆盖，用 :deep + 特异性别名）
- 所有颜色/间距/圆角必须来自设计令牌变量，禁止魔法值
- 组件必须：明确 props 类型 + 默认值 + emits 声明 + slot 声明
- 列表用 key，长列表用虚拟滚动（> 100 项）
- 所有请求必须处理 loading / empty / error 三态
- 表单必须：字段级校验 + 提交中禁用 + 失败保留输入
- 所有异步操作必须防竞态（请求序号 / AbortController）

【工程化】
- TypeScript strict，禁 any
- 统一请求层：拦截器处理 token 刷新、错误码映射、trace_id
- 统一错误处理：ErrorBoundary + 全局 toast
- API 类型从后端 OpenAPI 自动生成（openapi-typescript），不手写重复类型
- 组件命名用 PascalCase，文件名与组件名一致
- 禁止在组件中直接写死 URL 常量
"""
```

---

## 第 2 部分：项目宪法（`AGENTS.md` 全文）

> **操作**：在仓库根目录创建 `AGENTS.md`，内容为以下全文。Cursor 会自动加载并长期遵循。

```markdown
# AGENTS.md — 校园头盔检测提醒助手

## 项目一句话描述
面向师生的校园骑行安全行为积分平台：边缘侧 YOLOv8 检测骑行者头盔佩戴状态，
后端完成身份绑定与 AI 分级决策，管理员审批后生效，学生在小程序查看积分、申诉与奖励。

## 目录结构
```
e:/AI办公比赛/bisai/
├── helmet-guard/          # 后端 + 采集进程（Python）
│   ├── app/
│   │   ├── api/           # 路由层（v1）
│   │   ├── core/          # 配置、异常、依赖注入、日志
│   │   ├── domain/        # 纯领域逻辑（无 I/O）
│   │   ├── services/      # 业务服务
│   │   ├── repositories/  # 数据访问
│   │   ├── models/        # ORM 模型
│   │   ├── schemas/       # Pydantic 出入参
│   │   ├── workers/       # Celery 异步任务
│   │   └── ai/            # 模型封装、LLM 客户端
│   ├── tests/
│   ├── scripts/
│   ├── pyproject.toml
│   └── alembic/
├── admin-web/             # Vue3 管理后台
├── miniprogram/           # UniApp 微信小程序（学生端）
├── 数据集/                 # 原始数据集（不进 Git LFS 主体）
└── docs文档/               # 设计与文档
```

## 不可违反的原则

1. **证据优先**：任何处罚必须绑定可追溯证据（帧 + 框 + 置信度 + 推理依据）。
2. **三态保守**：检测结果只有 `helmeted / bare / unknown`。证据不足一律 `unknown`，
   **绝不猜测**。行人裸头不得判 `bare`。
3. **人工兜底**：AI 决策全部进入审批队列。自动生效需白名单配置且受熔断器约束。
4. **身份不足不惩罚**：身份置信度 < 0.60 的事件不得进入处罚决策，只进待识别池。
5. **正向激励**：积分、排行、勋章、商城与惩罚同等重要，不得只做惩罚。
6. **隐私最小**：**不做人脸识别**。身份靠「车辆登记 + 账号绑定」。
   证据图片加密存储、访问留痕、90 天自动过期删除。
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

## 交付要求

每个阶段交付时必须给出：
- 变更文件清单与职责说明
- 关键设计决策与取舍理由
- 测试覆盖情况（新增测试数、覆盖率变化）
- 已知的限制与后续计划
```

---

## 第 3 部分：P0 阶段提示词（工程基座）

> **目标**：把现有原型升级为企业级工程基座。**不要写业务功能。**
> **预计产出**：Git 仓库、依赖管理、配置体系、异常体系、数据库迁移工具、测试基座、admin-web 骨架。

### 3.1 P0-1：工程基座初始化

```
【任务】为 helmet-guard 后端项目建立企业级工程基座。本阶段不实现任何新业务功能。

【执行步骤】
1. 先完整阅读 helmet-guard/app/ 下所有 .py 文件，理解现有代码风格与约定。
2. 检查 E:/AI办公比赛/bisai 是否为 Git 仓库。若不是，执行 git init，
   并创建 .gitignore（必须排除）：
     runs/、data/、*.pt、*.db、*.db-wal、*.db-shm、node_modules/、dist/、
     .venv/、__pycache__/、.pytest_cache/、.mypy_cache/、.ruff_cache/、
     dataset/（大数据集不进 Git）、.env、*.log、.DS_Store
   .gitignore 中为 .env 与 *.pt 添加说明注释。
3. 创建 helmet-guard/pyproject.toml：
   - [project] 元数据、requires-python = ">=3.11"
   - 依赖：fastapi、uvicorn[standard]、pydantic>=2、pydantic-settings、
     sqlalchemy>=2.0、alembic、aiosqlite、psycopg[binary]、redis、
     python-jose[cryptography] 或 pyjwt、passlib[bcrypt]、
     python-multipart、pillow、opencv-python、ultralytics、numpy、
     httpx、celery、minio、structlog、tenacity、pytest、pytest-asyncio、
     pytest-cov、ruff、mypy、types-*
   - [tool.ruff] 严格配置，target-version = "py311"
   - [tool.ruff.lint] select = ["E","F","W","I","N","UP","B","SIM","C4","RET","ARG"]
     并对 tests/ 放宽 ARG
   - [tool.mypy] strict = true，warn_unreachable = true
   - [tool.pytest.ini_options] testpaths、asyncio_mode = "auto"
   - [tool.coverage.run] source = ["app"]
4. 创建 helmet-guard/.env.example（列出所有配置项及说明，**不含真实值**）：
   APP_ENV、APP_DEBUG、DATABASE_URL、REDIS_URL、JWT_SECRET、JWT_ALGORITHM、
   ACCESS_TOKEN_EXPIRE_MINUTES、REFRESH_TOKEN_EXPIRE_DAYS、CORS_ORIGINS、
   HELMET_GUARD_MODE、HELMET_GUARD_DB、HELMET_GUARD_WEIGHTS、
   HELMET_GUARD_SELFCHECK_WEIGHTS、HELMET_GUARD_HEARTBEAT_EXPIRE、
   HELMET_GUARD_ALERTS_ENABLED、MINIO_ENDPOINT、MINIO_ACCESS_KEY、
   MINIO_SECRET_KEY、MINIO_BUCKET、LLM_API_KEY、LLM_BASE_URL、LLM_MODEL
5. 创建 helmet-guard/app/core/ 包：
   - config.py：基于 pydantic-settings 的 Settings 类（单例 lru_cache），
     字段分组（App/Database/Redis/JWT/CORS/Storage/LLM/Model），
     提供 @property 派生属性（如 is_production）
   - logging.py：structlog 配置，JSON 格式（生产）/ Console（开发），
     提供 get_logger(name)；日志自动带 request_id/context
   - errors.py：领域异常层级 AppError(基类) → NotFoundError、ValidationError、
     ConflictError、PermissionDeniedError、RateLimitError、ExternalServiceError、
     ModelNotReadyError；每个异常带 code（机器可读）与 message（用户可读）
   - security.py：JWT 签发/校验、密码哈希（bcrypt）、当前用户依赖
   - middleware.py：RequestContextMiddleware（生成 trace_id、计时、注入日志上下文）、
     ErrorHandlerMiddleware（领域异常 → 统一 JSON 响应）
   - deps.py：FastAPI 依赖注入工厂（get_db_session、get_current_user、
     require_roles(*roles)）
6. 创建 helmet-guard/app/schemas/ 包：
   - common.py：分页响应 Page[T]、ErrorResponse、分页查询参数基类
   - 预留 health.py 等后续模块的 schema 骨架（先只建 common）
7. 创建 helmet-guard/tests/conftest.py：
   - fixture: tmp_db（每个测试用独立临时 SQLite 文件）
   - fixture: client（FastAPI TestClient，lifespan 内建表）
   - fixture: seeded_data（最小可用的演示数据）
   - 所有 fixture 可重复执行且互不干扰（测试间隔离）
8. 运行 `ruff check .` 与 `mypy app` 与 `pytest`，把当前所有问题修复到全绿。
   修复时**允许修改 app/ 下既有代码**，但必须保持行为不变（除修复真实 bug），
   且不得删除 §2 中列出的优秀实践。

【约束】
- 不得新增任何业务表或业务接口
- 不得改动 detect.py 的采集逻辑与 selfcheck.py 的推理逻辑
- 既有代码风格不一致时，以**新代码的高标准为准**，逐步迁移而非一次性大改
- 所有新增代码必须有类型注解，ruff/mypy 必须零错误

【验收】
- `ruff check .` 零错误
- `mypy app` 零错误
- `pytest` 全部通过且有覆盖率报告
- `pip install -e .` 可成功安装
- 目录结构符合 §2

【汇报】
输出：目录树、依赖清单及版本、异常层级说明、配置项说明、
      修复了哪些既有代码问题（逐条列出原因）、测试结果与覆盖率。
```

### 3.2 P0-2：数据库迁移与仓储基座

```
【任务】引入 Alembic 迁移体系与 Repository 基座，把现有裸 SQL 逐步收敛到仓储层。

【执行步骤】
1. 现状梳理：阅读 app/db.py 与 app/store.py，列出当前 6 张表
   （sources / passes / events / reviews / heartbeats / alerts）的建表语句与用途。
2. 安装并配置 Alembic：
   - alembic init alembic
   - alembic.ini 中 sqlalchemy.url 从 app/core/config.py 的 Settings 读取
     （不要硬编码路径）
   - env.py 支持离线/在线两种模式，target_metadata 从 models 导入
3. 创建 app/models/ 包：
   - base.py：DeclarativeBase + 通用 Mixin（created_at / updated_at）
   - 使用 SQLAlchemy 2.0 风格（Mapped / mapped_column）
   - 为现有 6 张表建立 ORM 模型，**字段与现有 SQLite 表完全一致**
     （可空性、默认值、CHECK 约束、UNIQUE 约束都要还原）
   - 注意：events.status 的 CHECK、passes.rider_status 的 CHECK、
     alerts.status 的 CHECK 必须用 Enum 或 CheckConstraint 表达
4. 用 Alembic 生成**基线迁移**（baseline migration）：
   - 第一条迁移 = 现有 6 张表的 CREATE TABLE（供新环境建库）
   - 之后每条迁移只做增量变更
   - 迁移文件必须可回滚（downgrade 完整）
5. 创建 app/repositories/ 包：
   - base.py：BaseRepository，提供通用 CRUD（get_by_id / list / create /
     update / delete），所有 SQL 参数化
   - 先实现 EventRepository、PassRepository、ReviewRepository、AlertRepository
   - 每个方法带完整类型注解与 docstring
   - 复杂查询使用 SQLAlchemy Core 表达式，不拼接字符串
6. 把 app/store.py 中的逻辑迁移到仓储层，**保留 store.py 作为兼容层**
   （内部转调仓储），保证既有 detect.py / main.py 调用不破坏。
   - apply_review 的并发安全语义必须**逐字保留**：
     BEGIN IMMEDIATE + 条件 UPDATE WHERE status='pending' + 幂等 + 409 冲突
   - 这部分必须补一个并发测试（多线程同时复核同一事件，只有一个成功）
7. 编写迁移测试：
   - 测试从空库 upgrade 到 head 成功
   - 测试 downgrade 到 base 再 upgrade 成功
   - 测试迁移后表结构与 ORM 模型一致

【约束】
- 本阶段**不新增业务表**，只做现有表的 ORM 化与迁移基建
- 不修改既有 API 的请求/响应格式
- 迁移文件不得手写 CREATE TABLE 之外的危险操作（禁止 DROP 非空表）

【验收】
- alembic upgrade head 可在空库成功执行
- alembic downgrade base 成功
- 既有 pytest 全绿
- 新增并发复核测试通过

【汇报】
输出：迁移文件清单、ORM 模型映射表、Repository 方法清单、
      store.py 的兼容策略、并发测试的实现方式与结果。
```

### 3.3 P0-3：管理后台骨架（Vue3 + TS）

```
【任务】从零创建 admin-web/（Vue3 管理后台），只搭骨架不做业务页面。

【执行步骤】
1. 用 Vite 创建项目：npm create vite@latest admin-web -- --template vue-ts
   目录位置：E:/AI办公比赛/bisai/admin-web
2. 安装依赖：
   - 运行时：vue-router@4、pinia、axios、echarts、vue-echarts、
     element-plus、@element-plus/icons-vue、dayjs、nprogress
   - 开发：unplugin-auto-import、unplugin-vue-components、
     @vitejs/plugin-vue、sass、eslint、prettier、eslint-plugin-vue、
     @typescript-eslint/parser、@typescript-eslint/eslint-plugin、
     vue-tsc、unplugin-vue-define-options
3. 配置 vite.config.ts：
   - @ 指向 src/
   - 代理：/api → http://127.0.0.1:8000（开发环境）
   - sass additionalData 自动注入 design-tokens.scss
4. 创建设计令牌体系（src/styles/design-tokens.scss）：
   - 严格采用 Apple HIG 风格色板（详见第 10 部分完整规范）
   - 颜色、间距、圆角、阴影、字号、字重、动效时长全部令牌化
   - 支持亮色/暗色（CSS 变量 + [data-theme]）
   - **禁止任何魔法值**，所有样式必须引用 var(--xxx)
5. 创建 src/styles/ 基础样式：
   - reset.scss（现代 reset）
   - typography.scss（文字层级工具类）
   - utilities.scss（间距/布局工具类，基于令牌）
6. 配置 ESLint + Prettier：
   - ESLint：eslint-plugin-vue（flat config）+ TypeScript 规则
   - 规则必须包含：vue/multi-word-component-names、vue/require-default-prop、
     @typescript-eslint/no-explicit-any、@typescript-eslint/consistent-type-imports
   - Prettier：printWidth 100、singleQuote、semi false、trailingComma all
7. 创建 src/api/ 基座：
   - request.ts：Axios 实例，拦截器处理
     (a) 请求：注入 Authorization Bearer token（从 Pinia auth store 取）
     (b) 响应：统一解包 { code, data, message }；401 → 刷新 token → 重放；
         403/404/409/422/429/500 映射为业务错误类型；错误携带 trace_id
     (c) 上传：单独封装 upload 实例，带进度回调与大小/类型前置校验
   - types.ts：定义 ApiResponse<T>、PageResult<T>、ApiError
   - 后续业务 API 文件按模块划分（decisions.ts / events.ts / students.ts ...），
     本阶段只建 request.ts 与 types.ts
8. 创建 src/stores/：
   - app.ts（侧边栏折叠、主题、当前点位）
   - auth.ts（token、用户信息、角色、登录/登出/刷新）
9. 创建 src/router/：
   - 路由表 + 路由守卫（未登录跳登录；按角色过滤菜单；标题设置）
   - 布局路由用嵌套路由 + Layout 组件
10. 创建 src/layouts/：
    - index.vue：侧边栏 + 顶栏 + 主内容区 + 标签页
    - 侧边栏菜单从路由 meta 自动生成（支持权限过滤）
    - 顶栏：面包屑、点位切换器、通知铃铛、用户菜单
    - **样式严格遵循 Apple HIG**：无渐变、无阴影堆叠、克制用色
11. 创建 src/views/login/index.vue：
    - 简洁居中卡片，Apple 风格；表单校验；加载态；错误提示
12. 创建 src/views/error/404.vue 与 403.vue
13. 创建 src/components/ 基础组件：
    - StatCard.vue（指标卡：标签/数值/趋势/图标）
    - PageHeader.vue（页面标题 + 描述 + 右侧操作区）
    - DataTable 封装（基于 el-table，统一空态/加载态/分页样式）
    - EmptyState.vue（Apple 风格空态：图标 + 文案 + 可选操作）
    - EvidenceViewer.vue（证据图 + 检测框叠加 —— **核心组件**，见 P3 提示词）
14. 配置类型生成：scripts/gen-api-types.sh（从后端 /openapi.json 生成
    src/api/generated/schema.ts），在 package.json 加 "gen:api" 脚本。
    后端未就绪时该脚本优雅失败，不阻塞开发。

【约束】
- Element Plus 主题必须通过 SCSS 变量覆写为 Apple 风格色板，
  不使用其默认主题（默认主题太"蓝"且圆角偏大）
- 禁止在任何 .vue 文件中写超过 100 行的 <style> 块
- 禁止 !important
- 禁止在组件中硬编码 API URL
- 禁止使用 any

【验收】
- npm run dev 可启动，登录页正常渲染
- npm run type-check（vue-tsc --noEmit）零错误
- npm run lint 零错误
- 侧边栏菜单根据登录角色动态变化
- 深浅色主题切换正常
- 视觉风格：素色背景、单一主色、清晰留白、无渐变无花哨动效

【汇报】
输出：目录树、设计令牌完整清单、Axios 拦截器处理流程、
      路由权限矩阵、Element Plus 主题覆写方式、截图或效果描述。
```

### 3.4 P0-4：数据集抢救与 Git LFS

```
【任务】数据集图片/标签已丢失，需要从原始 zip 恢复并建立数据版本管理。

【执行步骤】
1. 现状确认：检查 helmet-guard/dataset/ebike_helmet_v2/{train,valid,test}，
   确认只有 .cache 文件、无图片与标签。
2. 原始压缩包位于 E:/AI办公比赛/bisai/数据集/：
   - -------2023-3-19.v2i.yolov8.zip（约 2.97GB）
   - Motorcycle helmet.v1-helmet_detection_v1.yolov8.zip（约 121MB）
3. 恢复步骤（**必须解压到 E:/AI办公比赛/bisai/数据集/extracted/，
   不要解压到 dataset/ 下，避免污染仓库**）：
   - 逐个解压，输出每个 zip 的目录结构（前 3 层）与图片数量、标签数量
   - 识别出哪个是 ebike_helmet_v2 对应的源数据
   - 统计每个 zip 的类别分布（从标签文件解析 class id 计数）
4. 建立 dataset/ebike_helmet_v2/ 的标准 YOLOv8 目录：
   images/train, images/valid, images/test
   labels/train, labels/valid, labels/test
   （把 valid 改名为 val 要保持与现有 data.yaml 一致 —— 先读现有
     dataset/ebike_helmet_v2/data.yaml 确认用的是 val 还是 valid）
5. 编写脚本 scripts/audit_dataset.py：
   - 统计各 split 的图片数、标签数、每类实例数、空标签比例
   - 检查类别 id 是否越界（对照 data.yaml 的 names）
   - 检查图片与标签是否一一对应（有图无标 / 有标无图）
   - 检查坐标是否越界（x,y,w,h 必须归一化在 [0,1]）
   - 检测数据泄漏风险：按图片内容哈希找出 train/val 重复图
   - 输出 Markdown 报告到 docs文档/数据集审计报告.md
6. 在 data.yaml 中补充说明：类别 id 0=Cyclists, 1=helmet, 2=no helmet
   （从标签实际内容核实，不要凭记忆写）
7. 配置 Git LFS（可选但推荐）：
   - git lfs install
   - git lfs track "*.jpg" "*.png" "*.txt"（或按需）
   - .gitattributes 写入
   - 如果数据量过大不适合入库，则在 .gitignore 排除 dataset/ 并在
     docs文档/ 数据说明.md 写清恢复步骤

【约束】
- **绝对不要删除或覆盖原始 zip 文件**
- 解压过程可能耗时较长，注意磁盘空间
- 报告必须用真实统计数字，不能是估计值

【验收】
- 数据集恢复完整，图片数与标签数匹配
- 审计报告包含真实统计
- 训练能读取 data.yaml 并正常开始（跑 1 个 epoch 验证）

【汇报】
输出：两个 zip 的完整结构与统计、恢复后的数据集规模、
      类别分布表、审计发现的问题清单、训练冒烟测试结果。
```

---

## 第 4 部分：P1 阶段提示词（身份识别）

> **目标**：回答"这是谁的车"。这是项目的核心竞争力，分 4 个子阶段。

### 4.1 P1-1：身份域数据模型

```
【任务】新增身份识别相关的数据模型与迁移。

【执行步骤】
1. 先阅读说明书 §7.2 与 §4.7 的建表 SQL，以及 P0 已建立的 ORM 模型风格。
2. 用 Alembic 生成迁移，新增以下 6 张表（字段以说明书为准，但要做工程化增强）：
   - users（登录账号：user_id PK, openid UNIQUE, unionid, username, phone,
     role, status, last_login_at, created_at, updated_at）
   - students（学生档案：student_id PK=学号, user_id UNIQUE FK,
     name, gender, college, class_name, grade, dorm_id, phone, avatar,
     status, created_at, updated_at）
   - vehicles（车辆档案：vehicle_id PK, plate_no UNIQUE, plate_type,
     owner_id FK->students, owner_bind_type, confidence, color_hist JSON,
     embedding BLOB, first_seen, last_seen, status, created_at, updated_at）
   - identity_resolutions（每次通行的身份判定：id PK, event_id, vehicle_id,
     subject_id, method, confidence, plate_conf, appearance_conf,
     cooccur_conf, matched_count, snapshot_id, created_at）
   - pending_identities（待绑定车辆池：id PK, vehicle_id, pass_count,
     first_seen, last_seen, location, snapshot_id, status, created_at）
   - vehicle_cooccurrence（车辆共现矩阵：vehicle_a + vehicle_b 复合主键,
     window_count, jaccard, updated_at）
3. 工程化增强（在说明书基础上补充）：
   - 所有表加 created_at / updated_at（PostgreSQL 用 server_default=func.now()）
   - 所有枚举字段用 PostgreSQL Enum 类型（SQLite 下用 VARCHAR + CheckConstraint）
   - 加 Alembic autogenerate 的准确率检查，避免手写迁移与模型漂移
   - 为高频查询建索引：vehicles(owner_id)、vehicles(plate_no)、
     identity_resolutions(event_id)、identity_resolutions(subject_id)、
     identity_resolutions(vehicle_id)、pending_identities(status)
4. 新建 app/schemas/identity.py：Pydantic 出入参模型
   - VehicleCreateRequest / VehicleResponse
   - IdentityResolutionResponse
   - PendingIdentityResponse
   - BindVehicleRequest（vehicle_id + student_id + method + note）
5. 新建 app/repositories/vehicle.py、identity.py：
   - VehicleRepository: create / get_by_id / get_by_plate / list_by_owner /
     update_owner / touch_seen / find_similar_by_embedding(余弦相似度)
   - IdentityRepository: create_resolution / get_by_event /
     list_by_subject / upsert_pending / list_pending / resolve_pending
   - 注意 SQLite 没有向量索引，embedding 相似度查询用 Python 层计算并
     在注释中说明生产应换 pgvector
6. 迁移测试 + Repository 单元测试。

【约束】
- 迁移必须可回滚
- 迁移后必须验证 alembic upgrade head 与 downgrade base 都成功
- 不写业务逻辑，只建数据访问层

【验收】
- 迁移成功且可回滚
- ORM 模型与迁移一致（用 alembic check 验证无漂移）
- Repository 单元测试通过

【汇报】
输出：新增表结构说明、与说明书 SQL 的差异及原因、索引设计理由、
      Repository 方法签名清单、测试结果。
```

### 4.2 P1-2：车辆外观特征提取

```
【任务】实现车辆外观特征（128 维 embedding）的提取与相似度匹配。

【执行步骤】
1. 领域层（纯函数，无 I/O）：创建 app/domain/vehicle_appearance.py
   - extract_color_histogram(image_crop) -> np.ndarray[64]
     在 HSV 空间做 8×8 直方图（H:8, S:8，合并 64 维），H 归一化到 [0,179]/180
   - extract_shape_signature(rider_box) -> np.ndarray[16]
     宽高比、框内上/中/下三段的宽占比、垂直梯度分布等
   - compute_embedding(color_hist, shape_sig) -> np.ndarray[128]
     L2 归一化；拼接后压缩到 128 维（PCA 或简单线性投影 + 归一化）
   - cosine_similarity(a, b) -> float
   - match_candidates(query_emb, candidates: list[tuple[str, np.ndarray]],
     threshold: float, margin: float) -> MatchResult
     规则：最高相似度 ≥ threshold 且 与次高差值 ≥ margin 才返回；
     否则返回 None（歧义）。**必须写清楚这个 margin 规则的理由**
2. 服务层：创建 app/services/identity/appearance.py
   - extract_vehicle_embedding(frame, rider_box) -> np.ndarray[128]
     从 Cyclists 框裁剪车辆区域（框下部 60%），算直方图+形状
   - 这层依赖 cv2/numpy，属于有 I/O 的服务层
3. 仓储集成：VehicleRepository 增补
   - list_embeddings_by_owner(owner_id) -> list[(vehicle_id, embedding)]
   - update_embedding(vehicle_id, embedding)
   - add_embedding_sample(vehicle_id, embedding)（多样本，匹配时取平均）
4. 单元测试（app/domain/vehicle_appearance.py）：
   - 同一张图的两次裁剪 → 相似度 > 0.99
   - 不同颜色的车 → 相似度 < 0.7
   - match_candidates 的 margin 规则测试（构造相似度接近的候选）
   - 维度校验：输入非 128 维必须报错
5. 集成测试：构造 3 辆车（红/蓝/黑）的仿真图像，
   验证第 1 次登记后，第 2/3 次通行能正确匹配回同一 vehicle_id。

【约束】
- 领域层不得 import cv2/numpy 以外的 I/O 模块（numpy 做数值计算允许）
- 相似度阈值必须定义为常量并在文档中说明取值依据
- 所有函数带类型注解

【验收】
- 单元测试全绿
- 同色不同车场景下不误匹配（margin 规则生效）
- 仿真集成测试通过

【汇报】
输出：特征提取算法说明（含为何选 HSV 而非 RGB、为何取下部 60%）、
      阈值与 margin 的取值依据、match_candidates 的判定逻辑、
      单元测试清单与结果。
```

### 4.3 P1-3：多证据身份融合

```
【任务】实现车牌/二维码/外观/共现多证据的身份置信度融合。

【执行步骤】
1. 领域层：创建 app/domain/identity_fusion.py（纯函数，必须可单测）
   - 定义 EvidenceMethod 枚举：PLATE / QR / NFC / APPEARANCE /
     COOCCUR / MANUAL / NONE
   - 定义 Evidence dataclass：method, confidence, detail（可读证据说明）
   - 定义 IdentityOutcome dataclass：
     vehicle_id, subject_id, confidence, method（主方法）,
     evidence（全部证据）, decision（BIND / SUGGEST / UNBOUND）, reason
   - fuse_evidence(evidences: list[Evidence], policy: FusionPolicy)
       -> IdentityOutcome
     算法：对数似然比加权融合
       logit = Σ wᵢ · log(pᵢ/(1-pᵢ))，再 sigmoid
     权重与先验概率来自 FusionPolicy（可注入，便于测试与调参）
     **必须处理 p=0 或 p=1 的边界**（clamp 到 [1e-6, 1-1e-6]）
     **必须处理证据冲突**（同一车多个 method 指向不同 subject → 强制 UNBOUND）
   - 默认策略常量：
       AUTO_BIND_THRESHOLD = 0.85
       SUGGEST_THRESHOLD   = 0.60
       低于 SUGGEST → UNBOUND（进待识别池）
   - 一个专门的解释函数 explain_outcome(outcome) -> str
     生成人话，如"车牌识别置信度 0.95，匹配到已登记车辆（皖A12345）"
2. 服务层：创建 app/services/identity/resolver.py
   - resolve_identity(event, frame, rider_box) -> IdentityOutcome
     编排：车牌证据 → 二维码证据 → 外观证据 → 共现证据 → 融合
   - plate_evidence(...)：调用车牌 OCR 服务（接口先 stub，
     P1-4 实现，用 Protocol 定义以解耦）
   - appearance_evidence(...)：调用 appearance 服务
   - cooccur_evidence(...)：查询共现矩阵
   - 每类证据都失败 → 返回 UNBOUND + NONE 证据
3. 定义 Protocol（app/services/identity/protocols.py）解耦 OCR：
   - class PlateReader(Protocol): async def read(frame, box) -> PlateResult
   - 提供 DefaultPlateReader（返回未识别）与后续真实实现
4. 单元测试（重点，必须覆盖边界）：
   - 仅车牌 0.95 → BIND
   - 仅外观 0.72 → SUGGEST
   - 仅共现 0.45 → UNBOUND
   - 车牌 0.95 + 外观 0.3 → BIND（强证据主导）
   - 车牌指向学生 A + 外观指向学生 B → UNBOUND（冲突）
   - 空证据列表 → UNBOUND
   - p=1.0 的证据（clamp 不崩溃）
   - 融合结果置信度在 [0,1]
   - 阈值边界：恰好 0.85 → BIND；0.5999 → UNBOUND
5. 集成测试：用 resolver + stub PlateReader 验证端到端决策流。

【约束】
- 领域层必须零 I/O，纯函数，输入输出可序列化
- 融合算法必须可解释（每个证据的贡献可在日志与 UI 中展示）
- 阈值必须是模块级常量并写明依据

【验收】
- 单元测试覆盖所有边界且全绿
- 冲突场景正确返回 UNBOUND
- 置信度分布合理（不是所有情况都接近 1）

【汇报】
输出：融合公式推导、权重表与依据、阈值依据、
      完整测试用例表（含每个用例的输入输出）、冲突处理说明。
```

### 4.4 P1-4：车牌 OCR 接入

```
【任务】实现车牌检测与识别（可先做可插拔封装 + 真实实现骨架）。

【执行步骤】
1. 先评估依赖可行性：如果 paddleocr 在当前环境安装困难，
   则用 Protocol 定义抽象 + 提供 OpenCV/传统 OCR 的降级实现，
   并在文档中说明生产建议用 PaddleOCR PP-OCRv4。
   **不要因为装不上依赖就放弃整个功能。**
2. 创建 app/services/identity/plate_ocr.py：
   - PlateResult dataclass：text, confidence, bbox, plate_type
     （plate_type: BLUE / SCHOOL / UNIVERSITY / NONE）
   - CampusPlateConstrainer：
     校园号牌模式正则集合（东门037 / 南门A12 / 纯5位数字 等），
     constrain(candidates) -> 打分排序后的最优候选
   - normalize_plate(text) -> 统一化（去空格、全角转半角、大写）
   - PlateOCRService：检测车牌区域 → 透视矫正 → 识别 → 约束后处理
     （检测部分先用可插拔的 detector Protocol，默认实现为
      基于 Cyclists 框上部区域的启发式裁剪 + 预留 YOLO plate 类接入点）
3. 领域层 app/domain/plate.py：
   - is_valid_plate(text) -> bool
   - guess_plate_type(text) -> PlateType
   - campus_plate_score(text) -> float（符合校园模式的加分）
   - 这些是纯函数，易测
4. 单元测试：
   - normalize_plate 的各种脏输入
   - campus_plate_score 对 "东门037" / "A12345" / "XYZ" 的打分
   - is_valid_plate 边界
5. 集成到 resolver：当 PlateReader 返回结果时，
   走 plate 证据路径，并用 VehicleRepository.get_by_plate 查已登记车辆。

【约束】
- OCR 结果必须经过约束后处理才可使用，原始 OCR 文本仅作参考
- 识别失败必须优雅降级（返回空结果，不抛异常中断采集）
- 车牌文本在日志中脱敏（保留前 2 后 2，中间打码）

【验收】
- 单元测试全绿
- 校园号牌模式的约束打分生效
- 集成后 resolver 能产出 plate 证据

【汇报】
输出：车牌处理流水线图、约束规则表、降级策略、
      与生产级 PaddleOCR 方案的差异说明、测试结果。
```

### 4.5 P1-5：车辆共现图谱与匹配

```
【任务】实现基于时空共现的车辆归属推断（纯软件兜底方案）。

【执行步骤】
1. 领域层 app/domain/cooccurrence.py（纯函数）：
   - build_windows(timestamps: list[datetime], window_minutes=5)
       -> list[int]（时间窗口索引）
   - jaccard(a: set, b: set) -> float
   - compute_cooccurrence(vehicle_windows: dict[str, set[int]])
       -> dict[tuple[str,str], CooccurrenceStats]
     统计两车共现窗口数、Jaccard 相似度、置信度
     置信度公式需说明：结合共现比例与绝对共现次数，
     例如 conf = jaccard * min(1, shared_count / 3)
   - resolve_by_graph(known: dict[vehicle_id, student_id],
     cooc: dict, min_conf=0.60)
     -> dict[vehicle_id, (student_id, confidence)]
     用贪心 + 匈牙利算法（scipy.optimize.linear_sum_assignment）做
     带权二部图最大匹配，保证一车一人、一人车
     **必须处理 scipy 不可用的情况**（提供纯 Python 贪心降级）
2. 服务层 app/services/identity/cooccurrence.py：
   - update_cooccurrence(conn)：增量更新共现矩阵
     （新增通行后，把该车与最近 N 分钟内出现的其他车配对，累加窗口数）
   - rebuild_cooccurrence(conn)：全量重算（离线任务）
   - 这层做 IO，领域层保持纯函数
3. 仓储扩展 VehicleCooccurrenceRepository：
   - upsert / list_for_vehicle / list_all
4. 定时任务接入（Celery beat，或先用 scripts/ 下的手动脚本）：
   - 每日凌晨全量重算
5. 单元测试：
   - build_windows 的边界（跨小时、跨天）
   - jaccard 边界（空集合）
   - compute_cooccurrence：两车总是一起出现 → 高相似度
   - resolve_by_graph：一车不能被分配给两个学生
   - 三个车互相冲突时的分配结果
   - scipy 缺失时的降级路径
6. 集成测试：模拟 3 个学生各 1 车，其中 1 车无牌，
   验证能通过共现推断归属。

【约束】
- 领域层必须可脱离数据库单测
- 匹配算法必须保证一对一约束（有单元测试证明）
- 共现数据只用于"身份辅助"，不能单独作为高置信度证据

【验收】
- 单元测试全绿（含 scipy 降级路径）
- 一对一约束被测试覆盖
- 集成测试能推断出无牌车归属

【汇报】
输出：共现计算公式与置信度依据、时间窗口划分策略、
      匹配算法说明（含降级路径）、测试结果。
```

### 4.6 P1-6：身份管理 API 与后台页面

```
【任务】暴露身份管理 API，并实现对应的 Vue3 后台页面。

【后端步骤】
1. 创建 app/api/v1/identity.py：
   - GET    /api/v1/admin/identities/pending       待识别车辆池（分页+筛选）
   - POST   /api/v1/admin/identities/{vehicle_id}/bind  绑定到学生
   - POST   /api/v1/admin/identities/{vehicle_id}/ignore 忽略
   - GET    /api/v1/admin/vehicles                  车辆档案列表
   - GET    /api/v1/admin/vehicles/{id}             车辆详情（含匹配历史）
   - GET    /api/v1/admin/students                  学生列表
   - GET    /api/v1/admin/students/{id}             学生详情
   - POST   /api/v1/admin/students/import           批量导入（Excel）
   - GET    /api/v1/admin/students/template         下载导入模板
2. 权限：
   - 绑定/忽略操作需要 super_admin 或 league_officer 角色
   - 学生列表对 counselor 角色只返回其所带班级
   - 所有操作写 audit_logs
3. Excel 导入：
   - 用 openpyxl 生成模板（列：学号/姓名/性别/学院/班级/年级/宿舍/手机号）
   - 导入时逐行校验（学号格式、必填、重复），返回逐行错误报告
   - 大文件用后台任务处理，返回任务 ID
4. 所有列表接口统一分页参数 page/page_size/sort 白名单/keyword
5. 编写 API 测试（TestClient）：认证、权限、越权、分页、导入

【前端步骤】
6. 创建 admin-web/src/views/identities/：
   - Pending.vue（待识别车辆池）
     · 表格列：车辆缩略图/出现次数/首次出现/最近出现/最近点位/候选学生/操作
     · 「查看证据」打开 EvidenceViewer 抽屉
     · 「绑定学生」弹窗：学生搜索选择器（远程搜索）+ 确认
     · 批量操作：多选后批量忽略
     · 空态、加载态、失败重试
   - Vehicles.vue（车辆档案）
     · 列表 + 详情抽屉（车牌/绑定方式/置信度/匹配历史时间线/最近通行）
   - Students.vue（学生档案）
     · 列表（学号/姓名/班级/积分/等级/近30天佩戴率/违规次数）
     · 详情抽屉（基本信息 + 车辆 + 记录 + 积分流水）
     · 导入按钮 → 上传 Excel → 展示逐行校验结果
7. 创建 admin-web/src/api/identity.ts 与 students.ts（类型从 OpenAPI 生成）
8. 创建 admin-web/src/components/StudentPicker.vue
   （远程搜索学生选择器，被多处复用）
9. 样式遵循 Apple HIG：素色表格、清晰分隔线、无花哨。

【约束】
- 后端：任何列表查询必须有默认排序与分页上限
- 后端：越权返回 404 而非 403（避免资源存在性泄露）
- 前端：不使用 any，所有 loading/empty/error 三态齐全
- 前端：远程搜索组件必须防抖 + 取消旧请求

【验收】
- API 测试全绿（含越权测试）
- 3 个页面功能完整
- vue-tsc 与 eslint 零错误
- 导入错误报告清晰可用

【汇报】
输出：API 清单（含权限矩阵）、Excel 模板字段说明、
      三个页面的功能与交互说明、测试结果、越权防护验证方式。
```

---

## 第 5 部分：P2 阶段提示词（决策与积分）

> **目标**：实现「AI 自动决策 + 人工审批 + 积分闭环」。这是项目的核心创新。

### 5.1 P2-1：积分域数据模型与积分服务

```
【任务】建立积分账户、积分台账（只增不改）、积分规则。

【执行步骤】
1. Alembic 迁移新增 3 张表（字段依说明书 §7.2，工程化增强同 P1-1）：
   - score_accounts（student_id PK, balance, total_deducted, total_awarded,
     level, streak_days, compliance_rate, updated_at）
   - score_ledger（ledger_id PK, student_id, change, balance_after,
     reason_code, reason_text, event_id, decision_id, operator,
     effective_at, created_at）
     **关键约束：只增不改。禁止 UPDATE/DELETE 流水。**
   - score_rules（rule_id PK, rule_type, name, condition_json,
     score_change, priority, enabled, created_at, updated_at）
2. 领域层 app/domain/scoring.py（纯函数）：
   - 计算等级：level_from_score(score) -> 'S'|'A'|'B'|'C'|'D'
   - 计算连续合规天数：compute_streak(daily_compliance: list[bool]) -> int
     （今天还没判定时，从昨天往前算）
   - 计算滚动佩戴率：compliance_rate(passes, violations, window_days) -> float
   - 应用规则：apply_rules(rules, context) -> ScoreEffect
     condition_json 是一个受限 DSL（不是任意表达式！）：
       {"field":"violation_count_30d","op":">=","value":1,
        "all":[{"field":"model_confidence","op":">=","value":0.7}]}
     必须写一个**安全的 DSL 求值器**（白名单字段 + 白名单操作符），
     **绝不能用 eval()**
   - 规则测试要覆盖：单条件、多条件 all/any、字段缺失、无效规则
3. 服务层 app/services/scoring/ledger.py：
   - LedgerService.apply(student_id, change, reason_code, reason_text,
     event_id, decision_id, operator)
     流程（必须在单个事务内）：
       1. SELECT ... FOR UPDATE 锁定 score_accounts 行（SQLite 下用 BEGIN IMMEDIATE）
       2. 校验：积分不能低于下限（默认 0），不能超过上限（默认 100）
       3. 计算 balance_after
       4. 插入 score_ledger 流水
       5. 更新 score_accounts（balance, total_deducted/total_awarded,
          streak_days, compliance_rate）
       6. 提交
     **并发安全**：同一学生的并发扣分必须串行化，不出现余额错误或流水丢失
   - LedgerService.revert(ledger_id, reason)：申诉成立时，
     **不修改原流水**，而是插入一条反向流水（change 取反）
   - get_balance(student_id) -> int
   - list_ledger(student_id, 分页) -> list
4. 仓储：ScoreAccountRepository / ScoreLedgerRepository / ScoreRuleRepository
5. 一致性不变量测试（必须写）：
   - 任意流水序列后，balance == sum(change)
   - revert 后 balance 回到原值，且流水条数 +1
   - 并发扣分 20 次 × -1 分，最终 balance 与流水条数一致
   - 余额不会为负（触发下限保护并抛业务异常）
6. 记录每次积分变更都会写 review/audit 日志。

【约束】
- LedgerService 的事务边界必须在函数内明确，异常必须回滚
- 绝不允许 UPDATE score_ledger（除了测试中验证这一点）
- DSL 求值器必须有字段白名单与操作符白名单

【验收】
- 一致性不变量测试全部通过
- 并发扣分测试通过
- DSL 求值器无法被恶意输入绕过（补测试）

【汇报】
输出：积分台账的事务流程图、DSL 规范与安全边界、
      一致性不变量测试清单、并发测试的实现方式与结果。
```

### 5.2 P2-2：AI 决策引擎（核心）

```
【任务】实现确定性的规则决策引擎——本项目最核心的算法模块。

【执行步骤】
1. 领域层 app/domain/decision.py（**必须是纯函数，零 I/O，可完整单测**）：
   - 枚举 DecisionLevel：L0/L1/L2/L3/L4
   - 枚举 DecisionAction：NONE/REMIND/DEDUCT_SCORE/NOTIFY/REPORT/AWARD
   - 枚举 ReasonCode：字符串枚举，至少包含
     NO_TARGET / LOW_CONFIDENCE / NOT_BARE / IDENTITY_UNCERTAIN /
     FIRST_OFFENSE / REPEAT_WITHIN_30D / REPEAT_WITHIN_7D /
     REPEAT_SAME_POINT / HIGH_FREQUENCY / STREAK_BONUS / AWARD_EXCELLENT ...
   - dataclass Fact：模型置信度、身份置信度、头盔状态、30天/7天/1小时违规数、
     30天通行数、连续合规天数、当前积分、是否高峰时段、
     是否同点位重复、历史申诉成立次数、历史申诉提交次数
   - dataclass Factor：name, value, weight, evidence（可解释因子）
   - dataclass DecisionResult：level, action, score_delta, reason_code,
     confidence, factors, message, needs_human_review
   - dataclass DecisionPolicy（可注入，便于调参与模拟）：
     min_model_confidence, min_identity_confidence, l1/l2/l3_score,
     repeat_window_days, high_frequency_threshold,
     require_human_review_levels, auto_approve_levels,
     max_auto_score_delta, risk_gates
   - **核心函数** decide(fact: Fact, policy: DecisionPolicy) -> DecisionResult
     判定顺序（严格按此顺序，每一步都要写进 factors）：
       1. 风险闸门（先于一切）：
          - helmet_status != 'bare'            → L0/NONE，reason=NOT_BARE
          - identity_confidence < policy.min_identity_confidence
                                                   → L0/NONE，reason=IDENTITY_UNCERTAIN
          - model_confidence < policy.min_model_confidence
                                                   → L0/NONE，reason=LOW_CONFIDENCE
       2. 档位判定：
          - 30天违规 >= 3 或 7天违规 >= 2 或 同点位1小时内>=2
                                                   → L3/REPORT
          - 30天违规 >= 1 或 7天违规 >= 1
                                                   → L2/DEDUCT_SCORE
          - 否则                                        → L1/REMIND
       3. 奖励判定（与违规互斥，仅在合规时）：
          - 连续合规 >= 30 天                           → L4/AWARD
       4. 因子计算：每个命中规则贡献一个 Factor（含权重与证据文本）
       5. 置信度：综合模型置信度与身份置信度的加权几何平均
     **所有阈值必须来自 policy，不允许硬编码魔法数**
2. 决策回放领域函数：
   - replay_decision(original: DecisionResult, new_fact: Fact,
     new_policy: DecisionPolicy) -> ReplayDiff
     输出：original / replayed / changed / diff_reason
     用于策略模拟器
3. 规则注册表 app/domain/decision_rules.py：
   - 规则以 (name, predicate_fn, factor_builder) 三元组注册
   - 提供 rule_registry，便于后台可视化展示"当前启用了哪些规则"
4. 熔断器 app/domain/circuit_breaker.py（纯函数判定）：
   - dataclass BreakerState：today_punishments, max_student_daily_delta,
     active_model_map, recent_dismiss_rate, identity_bind_rate
   - evaluate(state, thresholds) -> BreakerVerdict(tripped, rule, reason)
     5 条规则（依说明书 §8.8）
   - **特别注意 high_dismiss_rate 规则**：人工驳回率过高说明模型/策略失效
5. 单元测试（**必须覆盖完整决策矩阵**，按说明书 §13.2）：
   - 全部 9 条决策引擎测试用例
   - 每个风险闸门单独测（身份不足 / 模型不足 / 非 bare）
   - 边界值：count_30d 恰好为 1 / 3；confidence 恰好等于阈值
   - 因子完整性：每个非 L0 结果至少有一个 Factor
   - 权重总和合理性断言
   - 熔断器 5 条规则各自触发测试
   - 回放函数：策略变更导致档位变化时能正确产出 diff
   - **属性测试（可选 hypothesis）**：随机 Fact 输入下，
     结果的 level 必须是合法枚举，score_delta 在 [-3, +2] 范围内
6. 领域层零 I/O 校验：grep 确认 domain/decision.py 不 import
   任何数据库/网络模块。

【约束】
- decide() 必须是纯函数：同样的输入永远得到同样的输出
- 不允许在 domain 层出现 datetime.now()（时间由 Fact 传入）
- 阈值全部来自 DecisionPolicy，policy 有合理的 default_factory
- 每个 Factor 的 evidence 必须是可读中文，能直接展示给管理员

【验收】
- 全部单元测试通过
- domain 层无 I/O 依赖（用测试断言或静态检查证明）
- 决策矩阵 100% 覆盖
- 每个非 L0 结果都有可解释因子

【汇报】
输出：决策流程图（含每个闸门与因子贡献）、
      完整决策矩阵测试表、熔断器规则表、
      可解释因子示例（3 个不同场景）、回放 diff 示例。
```

### 5.3 P2-3：决策服务与审批流程

```
【任务】实现决策编排、审批工作流、申诉流程（服务层 + 仓储 + API）。

【执行步骤】
1. Alembic 迁移新增 3 张表：
   - decisions（说明书 §7.2 字段：decision_id PK, event_id, student_id,
     level, action, score_delta, reason_code, message, confidence,
     factors JSON, evidence_refs JSON, policy_version, status,
     auto_approved, reviewed_by, reviewed_at, review_note,
     original_level, effective_at, due_at, created_at, updated_at）
     status 枚举：PENDING_REVIEW / APPROVED / REJECTED / ADJUSTED /
     AUTO_APPROVED / APPEALING / APPEAL_UPHELD / APPEAL_REJECTED / EXPIRED
   - review_logs（id PK, decision_id, action, from_status, to_status,
     from_level, to_level, note, operator, created_at）
   - appeals（appeal_id PK, decision_id, student_id, reason, attachments JSON,
     status, handler, handle_note, resolved_at, created_at, updated_at）
2. 服务层 app/services/decision/engine.py：
   - DecisionEngine.decide_for_event(event_id) -> DecisionResult | None
     编排：
       1. 加载事件 + 身份解析结果 + 积分账户 + 风险聚合窗口统计
       2. 构建 Fact
       3. 调用 domain.decide()
       4. 计算 factor 与 message（message 优先用模板，LLM 为可选增强）
       5. 判定是否自动生效（auto_approve_levels + 熔断器检查）
       6. 创建 decisions 记录（status=PENDING_REVIEW 或 AUTO_APPROVED）
       7. 若自动生效 → 调用 LedgerService.apply() 扣/加分
       8. 写 audit 日志
   - 时间窗口统计查询（1h/24h/7d/30d）用 repository 聚合方法，
     SQL 用条件聚合一次性查出，避免 N+1
3. 审批服务 app/services/decision/review.py：
   - approve(decision_id, operator, level=None, note=None)
     - **沿用 store.apply_review 的并发安全模式**：
       BEGIN IMMEDIATE + 条件 UPDATE WHERE status='pending'
     - level 可降不可升（L3 不能被升到 L4）；降档需记录 original_level
     - 批准后调用 LedgerService.apply()
     - 幂等：重复批准同结果返回 200；冲突（已驳回又批准）返回 409
   - reject(decision_id, operator, reason)
     - reason 必填
     - **驳回的决策必须写入 feedback_samples 表**（回流训练集）
   - batch_approve(decision_ids, operator)
     - 单条失败不影响整批，返回逐条结果
   - expire_overdue(now)
     - 超时未审批的自动失效（L1/L2 逾期自动通过，L3 逾期升级通知）
4. 申诉服务 app/services/appeal/service.py：
   - submit(decision_id, student_id, reason, attachments)
   - resolve(appeal_id, handler, upheld: bool, note)
     - upheld → 调 LedgerService.revert() 插入反向流水 + 决策状态改 APPEAL_UPHELD
     - 写 feedback_samples（来源=appeal_upheld）
5. API app/api/v1/decisions.py、app/api/v1/appeals.py：
   - GET  /api/v1/admin/decisions                列表（多维筛选）
   - GET  /api/v1/admin/decisions/{id}           详情（含因子/证据/审批历史）
   - POST /api/v1/admin/decisions/{id}/approve   批准（可调档）
   - POST /api/v1/admin/decisions/{id}/reject    驳回
   - POST /api/v1/admin/decisions/batch-approve  批量批准
   - POST /api/v1/admin/policies/{id}/simulate   策略模拟（用 replay）
   - GET  /api/v1/me/records                     学生端记录
   - POST /api/v1/me/appeals                     学生发起申诉
   - GET  /api/v1/me/appeals                     我的申诉
6. 权限与审计：
   - L3 决策必须 league_officer 或 super_admin 才能批准
   - counselor 只能处理 L1/L2 且限于本班学生
   - 每次审批写 review_logs + audit_logs
7. 测试：
   - 领域层决策测试（已在 P2-2）
   - 服务层集成测试：事件 → 决策 → 审批 → 积分变动 全链路
   - 并发审批测试（多线程批同一决策，只有一个成功）
   - 幂等测试（重复 approve 返回相同结果）
   - 申诉回滚测试（积分正确回滚且流水 +1）
   - 越权测试（counselor 批 L3 → 403）

【约束】
- 审批并发安全必须用条件 UPDATE，不能用「先查后写」
- 自动生效路径必须经过熔断器检查
- 任何涉及积分的路径都必须走 LedgerService，不得直接改 balance
- 驳回必须回流训练集（这是模型迭代的闭环）

【验收】
- 全链路集成测试通过
- 并发审批只有一个成功
- 积分变更全部通过 LedgerService（代码审查确认无旁路）
- 越权测试通过

【汇报】
输出：决策→审批→积分全链路时序图、审批状态机图、
      权限矩阵表、并发控制实现细节、测试结果。
```

### 5.4 P2-4：LLM 话术生成（可选增强）

```
【任务】用 LLM 生成面向学生的个性化提醒文案，**只做解释，不做决策**。

【执行步骤】
1. 创建 app/ai/llm_client.py：
   - LLMClient：封装 OpenAI 兼容 API（httpx），带超时 + 重试（tenacity）
     + 降级（失败返回 None）
   - 严格约束：
     - 超时 10s，最多重试 2 次，指数退避
     - 失败不抛异常给调用方，返回 None
     - 记录 prompt 与 response 到结构化日志（不含个人信息）
     - **禁止把学生姓名、手机号、学号、身份证等传给 LLM**
2. 创建 app/ai/prompts/decision_message.py：
   - SYSTEM_PROMPT 严格按说明书 §8.5 的 6 条要求
   - 输入只包含：level、action、score_delta、factors 的 name/value、
     streak_days、score_balance、appeal_count（都是脱敏的结构化数据）
3. 创建 app/services/decision/message.py：
   - generate_message(fact, result) -> str
     - **先查模板**：如果 level 对应的模板文案存在，直接用模板（**默认走这条**）
     - LLM 仅在配置了 LLM_API_KEY 且显式开启时调用
     - LLM 输出必须经过校验：
       · 长度 ≤ 120 字
       · 敏感词过滤（词表：罚款/扣钱/处罚/记过/通报批评个人 等）
       · 禁止出现 URL、电话、邮箱、外部联系方式
       · 校验失败 → 回退模板
     - 生成结果必须落库（decisions.message），便于回溯
4. 创建 app/services/decision/templates.py：
   - 至少 20 条模板文案，按 level × 场景（首次/重复/严重）分类
   - 文案风格：客观陈述事实 + 具体改进建议 + 正向出口，不指责人格
   - 每条 ≤ 80 字
5. 单元测试：
   - 模板覆盖所有 level
   - 敏感词过滤生效（构造含敏感词的假 LLM 返回，验证被替换为模板）
   - 超长输出被拒绝
   - LLM 不可用时回退模板
   - **Prompt 中不含任何 PII**（用 fake client 捕获 prompt 断言）

【约束】
- **LLM 绝不参与 level/action/score_delta 决策**（代码结构上保证：
  domain/decide 不 import ai/ 任何东西）
- LLM 失败不影响主流程
- Prompt 里不出现学生身份信息
- 所有 LLM 调用必须有超时

【验收】
- 无 LLM key 时全流程正常（走模板）
- 有 LLM key 时生成文案并通过校验
- 敏感词测试通过
- Prompt 无 PII 测试通过

【汇报】
输出：模板文案清单（至少 20 条）、LLM 校验规则、
      Prompt 全文（脱敏后）、降级路径说明、测试结果。
```

---

## 第 6 部分：P3 阶段提示词（Vue3 管理后台）

> **目标**：实现管理后台的核心页面。**风格严格遵循 Apple HIG。**

### 6.1 P3-1：Dashboard 总览

```
【任务】实现管理后台总览页（Dashboard）。

【后端步骤】
1. 创建 app/api/v1/dashboard.py：
   - GET /api/v1/admin/dashboard/overview
     返回：今日通行总数、今日违规数、今日佩戴率（%）、待审批数、
           本月佩戴率趋势（30 点）、今日违规趋势（按小时，24 点）、
           点位在线数/总数、活跃学生数
   - GET /api/v1/admin/dashboard/trends?metric=&granularity=&days=
   - GET /api/v1/admin/dashboard/point-health
     返回每个点位：名称、状态、FPS、最近心跳、最后事件时间、今日事件数
   - **查询性能**：所有聚合用单条 SQL + 条件聚合，避免 N+1
   - 加响应缓存（Redis，TTL 30s，key 含参数）
2. 统一响应格式：所有 API 返回 { code: 0, data: ..., message: "" }
   （与 P0 建立的 Axios 拦截器对齐）

【前端步骤】
3. 创建 admin-web/src/views/dashboard/Index.vue：
   布局（Apple HIG 风格）：
   ┌─────────────────────────────────────────────┐
   │  指标卡片行（4 个，横向等宽，间距 20px）      │
   │  ┌──────┐┌──────┐┌──────┐┌──────┐          │
   │  │佩戴率││今日违规││待审批││在线点位│         │
   │  │ 87.3%││  42   ││  23  ││ 3/4   │         │
   │  │↑2.1% ││  ↑5   ││      ││      │          │
   │  └──────┘└──────┘└──────┘└──────┘          │
   ├─────────────────────────────────────────────┤
   │  左：佩戴率趋势（面积图）  右：今日违规时段柱状图 │
   ├─────────────────────────────────────────────┤
   │  点位健康度列表                                │
   └─────────────────────────────────────────────┘
4. 创建 admin-web/src/components/StatCard.vue：
   - props: label, value, unit?, trend?（{value, direction}）, icon?, tone?
   - 趋势：上升用主色（蓝），下降用中性灰（**不滥用红色**，
     因为佩戴率上升是好事，违规数上升才是坏事 —— 语义由 tone 决定）
   - 字号：数值 32px semibold，标签 13px 次要色
   - 卡片：白底、圆角 18px、1px 极浅边框或无边框+极轻阴影
5. ECharts 配置：
   - 统一色板（只用设计令牌中的色值）
   - 网格线：1px #F2F2F7
   - 无渐变填充（面积图用 8% 透明度纯色）
   - 坐标轴：无轴线，标签 12px #8E8E93
   - tooltip：白底 + 轻阴影 + 圆角 10px
   - 动画：只做 300ms 淡入，不做炫技动画
6. 创建 admin-web/src/views/dashboard/PointHealth.vue
7. 状态管理：Pinia dashboard store，30s 自动轮询 + 页面失焦暂停
   （document.visibilitychange）
8. 处理三态：loading（骨架屏，不用 spinner 旋转菊花）/
   empty（EmptyState 组件）/ error（重试按钮）

【约束】
- 卡片数值用 tabular-nums 字体特性，避免跳动
- 空态用 EmptyState 组件，不要空白
- 轮询必须可取消，组件卸载时清理定时器
- 图表容器必须有明确高度，不能用百分比撑开导致布局抖动

【验收】
- 页面渲染正确，数据来自真实 API
- 无数据时有友好空态
- 轮询在页面隐藏时暂停
- 视觉：无渐变、无阴影堆叠、留白充足、色板统一

【汇报】
输出：API 响应结构、页面布局说明、StatCard 组件 API、
      ECharts 主题配置、轮询实现、截图描述。
```

### 6.2 P3-2：审批中心（**答辩最重要页面**）

```
【任务】实现 AI 决策审批中心。这是整个后台最核心、最常被演示的页面。

【后端步骤】
1. 扩展 GET /api/v1/admin/decisions 支持筛选：
   status, level, point_id, student_id, date_from, date_to,
   min_confidence, sort（白名单：created_at/desc、confidence/desc、level/asc）
2. GET /api/v1/admin/decisions/{id} 返回完整详情：
   - decision 全部字段
   - factors（可解释因子数组）
   - event 详情 + snapshot URL + 检测框
   - identity_resolution（身份判定方法与置信度）
   - student 基本信息 + 当前积分 + 近30天佩戴率 + 历史违规
   - review_logs 历史审批记录
   - risk_hints（风险提示数组，如"该学生历史申诉成立 2 次，建议降档"）
3. GET /api/v1/admin/decisions/pending-count
4. POST /api/v1/admin/decisions/batch-approve
   body: { decision_ids: [...], note?: string }

【前端步骤】
5. 创建 admin-web/src/views/decisions/List.vue
   布局（双栏，这是效率关键）：
   ┌──────────────────────┬────────────────────────────┐
   │ 筛选栏 + 决策队列      │  决策详情                   │
   │ (可滚动列表, 约 380px) │  (flex: 1)                 │
   │                      │                             │
   │ [L1][L2][L3][全部]   │  ┌───────────────────────┐  │
   │ ───────────────      │  │ 证据帧 + 检测框叠加    │  │
   │ ● L3 严惩  0.91      │  └───────────────────────┘  │
   │   东校门 08:12       │  决策因子（带权重条）        │
   │   张同学 · 车牌匹配   │  风险提示                   │
   │   近30天第4次        │  建议话术（可编辑）          │
   │ ───────────────      │  [批准][降档][驳回][批量]    │
   │ ● L2 记分  0.88      │                             │
   └──────────────────────┴────────────────────────────┘
   - 左栏：级别筛选 Tab、决策卡片（级别色点 + 置信度 + 摘要）
   - 选中态：左侧 2px 主色竖条 + 浅色底
   - 右栏：EvidenceViewer + FactorList + 风险提示 + 操作区
6. 创建 admin-web/src/components/EvidenceViewer.vue（**核心组件**）
   - props: snapshotUrl, boxes[], imageWidth, imageHeight, annotations?[]
   - 功能：
     * 原图上叠加归一化检测框（按 label 着色，与小程序 boxColor 规则一致）
     * 框标签显示 label + 置信度
     * **坐标系一致性**：容器 aspect-ratio 用后端返回的 image_width/height，
       与归一化框同坐标系（参考现有 miniprogram/src/pages/index/index.vue
       的处理方式，必须避免横竖图错位）
     * 支持点击框高亮、显示详情
     * 支持放大镜（点击查看原图）
     * 加载中显示占位骨架
   - 颜色规则与小程序保持一致（helmet=绿, no helmet=红, 其他=蓝）
7. 创建 admin-web/src/components/FactorList.vue
   - 每个因子：名称 + 值 + 权重条（细长条，主色）+ 证据文本
   - 权重条宽度按 weight 归一化，动画 200ms
8. 创建 admin-web/src/components/DecisionCard.vue（列表项）
9. 创建 admin-web/src/components/RiskHint.vue（风险提示条）
   - 用浅橙底 + 橙色左边框，不刺眼
10. 操作交互：
    - 批准：直接生效（乐观更新 + 失败回滚）
    - 降档：弹出 level 选择器（L3→L2/L1），说明会如何改变分值
    - 驳回：必须填理由（至少 10 字），提交后回流训练集
    - 批量：多选后批量批准，逐条返回结果并展示成功/失败统计
11. 键盘快捷键（提高审批效率，答辩亮点）：
    - J / ↓：下一条；K / ↑：上一条
    - Enter：批准；X：驳回；D：降档；/：聚焦搜索
    - 快捷键在输入框聚焦时必须禁用
    - 页面顶部显示快捷键提示条（可折叠）
12. WebSocket 实时：新决策到达时，在队列顶部插入并高亮闪烁 2 次
    （**克制，不要花哨**），同时更新待审批计数
13. 空态设计：
    - 无待审批：EmptyState + "✅ 全部处理完毕" + 今日处理统计
    - 筛选无结果：EmptyState + 清除筛选按钮

【约束】
- 严禁花哨：不要渐变、不要 3D 卡片效果、不要连续动画、不要彩色边框
- 级别色只用 3 个：L1 橙(#FF9500)、L2 橙深/红橙、L3 红(#D92D20)、
  且只在色点和小面积使用，大面积仍用白底
- 证据查看是**必须**的，不能只显示文字结论
- 所有操作按钮必须有 loading 态与禁用态
- 乐观更新失败必须回滚并提示

【验收】
- 双栏布局工作正常，键盘快捷键生效
- 检测框与图片严格对齐（横竖图都测试）
- 批准/降档/驳回/批量全部可用
- 越权时按钮隐藏（前端）+ 后端二次校验
- 视觉克制、与 Apple HIG 一致

【汇报】
输出：页面布局图（ASCII）、组件清单与职责、快捷键表、
      检测框叠加的坐标系处理说明、乐观更新实现、
      实时推送接入方式。
```

### 6.3 P3-3：事件列表、积分管理、策略配置、申诉处理

```
【任务】批量实现后台剩余核心页面。

【页面清单与要点】
1. views/events/Index.vue（事件检索）
   - 多维筛选：点位/时间范围/状态/头盔状态/模型置信度区间/身份置信度区间/
     是否有证据/是否已决策
   - 表格列：时间、点位、状态、模型置信度、身份置信度、学生、决策状态、快照缩略图
   - 支持点击行打开详情抽屉（EvidenceViewer + 关联决策）
   - 支持导出 CSV（后端流式生成）
   - 排序：点击列头切换（白名单）
   - 分页：每页 20/50/100

2. views/scores/Ledger.vue（积分流水）
   - 表格：学生、时间、变动值（+绿/-红）、变动后余额、原因、来源、操作人
   - 顶部筛选：学生、日期、变动方向、reason_code
   - 变动值用等宽字体 + 正负号，颜色语义化
   - 支持按学生查看完整流水时间线

3. views/scores/Rules.vue（积分规则配置）
   - 规则列表（拖拽排序 priority）+ 内联编辑
   - 条件编辑器：字段下拉 + 操作符下拉 + 值输入（**不用 eval 式自由输入**）
   - 新增/编辑规则用 Drawer 抽屉
   - 每个规则显示"当前命中人数"（实时统计，帮助调参）
   - **修改规则前提示影响范围**（先调用 simulate 接口预估）

4. views/decisions/Policy.vue（决策策略配置）★重要
   - 分区展示 DecisionPolicy 的所有字段（带中文标签与说明）
   - 分级自治配置：每个 level 的自动生效开关、最大扣分、自动放行条件
   - 风险闸门配置：5 条熔断规则的阈值
   - 策略版本历史（每次保存生成新版本，附变更对比）
   - **策略模拟器**（高价值功能）：
     - 选择时间范围 + 修改参数 → 调 /admin/policies/{id}/simulate
     - 展示：受影响事件数、档位分布变化、预计扣分总额变化、
              与当前策略的 diff 列表（前 20 条 + 完整导出）
     - **必须醒目提示**："此操作仅推演，不会真实生效"

5. views/appeals/Index.vue（申诉处理）
   - 表格：学生、关联决策、申诉理由、提交时间、状态、附件数、处理人
   - 处理抽屉：左证据右理由 + 裁决按钮（成立/不成立）
   - 成立时提示"将撤销处罚并返还积分 X 分"
   - 必须填写处理意见

6. views/models/Index.vue（模型管理）
   - 模型版本列表：task、version、mAP/precision/recall、状态、部署时间
   - 激活切换（需二次确认 + 提示影响）
   - 反馈样本池（误判回流）：数量、来源分布、导出训练集
   - 模型质量趋势图

7. views/system/AuditLogs.vue（审计日志）
   - 只读表格：时间、操作人、角色、动作、对象、IP、结果
   - 筛选：操作人、动作类型、时间范围
   - **不可删除、不可编辑**（后端也不提供这两个接口）

8. views/system/Users.vue（用户与角色）
   - 用户列表、角色分配、启停用、密码重置
   - 角色权限矩阵展示（只读矩阵表）

【通用要求（所有页面）】
- 统一使用 PageHeader + 筛选栏 + DataTable + 分页 的结构
- 每个页面都要有 loading / empty / error 三态
- 表格操作列固定在右侧（fixed="right"）
- 危险操作（驳回、激活模型、重置密码）必须二次确认
- 筛选条件同步到 URL query（刷新不丢失、可分享链接）
- 表单校验：失败时聚焦第一个错误项
- 所有金额/分值用 tabular-nums

【约束】
- 不引入新的 UI 库（只用 Element Plus + 自研组件）
- 不使用 any
- 不写超过 100 行的 <style> 块
- 每个页面拆分为多个组件，单文件不超过 400 行

【验收】
- 8 个页面全部功能可用
- 策略模拟器能正确展示 diff
- 审计日志页无任何修改入口
- vue-tsc + eslint 零错误

【汇报】
输出：页面清单与每个页面的组件拆分、策略模拟器的实现与输出示例、
      筛选条件 URL 同步的实现方式、测试/自检结果。
```

### 6.4 P3-4：实时监控大屏

```
【任务】实现实时监控大屏（点位视频 + 检测框叠加 + 实时违规流）。

【后端步骤】
1. app/api/v1/monitor.py：
   - WS /api/v1/admin/ws/live
     推送类型：violation_detected / decision_created / device_status /
     stats_update / point_alert
     消息格式（依说明书 §10.4）
     实现要点：连接管理、断开清理、心跳 ping/pong、
     **按点位/角色过滤（counselor 只能收到本班相关事件）**
   - GET /api/v1/admin/monitor/points/{id}/snapshot  最新帧
   - GET /api/v1/admin/monitor/points/{id}/stream  视频流地址（预留）
2. 创建 app/services/realtime/hub.py：
   - ConnectionManager：注册/注销连接、按角色与点位过滤、广播
   - 线程安全（asyncio.Lock）
   - 慢客户端处理（发送队列满时丢弃最旧消息而非阻塞）

【前端步骤】
3. 创建 admin-web/src/views/monitor/Live.vue
   布局：
   ┌────────────────────────────────────────────────────┐
   │ 点位状态栏（名称、在线/FPS、佩戴率）    [点位切换]   │
   ├──────────────────────────┬─────────────────────────┤
   │                          │  实时违规流              │
   │   视频 + 检测框叠加      │  08:12 L3 张同学 -3分    │
   │                          │  08:11 L1 王同学 提醒    │
   │                          │  ─────────────────────  │
   │                          │  今日统计               │
   └──────────────────────────┴─────────────────────────┘
   - 视频区：优先 HLS（hls.js），失败回退 MJPEG（img 标签），
     都不通则显示占位与"设备离线"提示
   - 检测框叠加：与 EvidenceViewer 同一套渲染逻辑
     （**抽取为共享组件 src/components/DetectionOverlay.vue**）
   - 违规流：新事件从顶部插入，**只做一次淡入（200ms），不闪烁**，
     最多保留 50 条
   - 点位切换：切换时重置视频与叠加层
4. 创建 src/composables/useWebSocket.ts
   - 自动重连（指数退避 1s→30s）
   - 心跳（30s ping）
   - 页面隐藏时断开，可见时重连
   - 消息类型安全（TS 判别联合）
   - 组件卸载时完全清理
5. 创建 src/views/monitor/PointConfig.vue（ROI 可视化标定）★差异化功能
   - 上传或截取当前帧 → 在图上拖拽画框设定 ROI
   - 拖拽设定计数线（横向）
   - 实时预览检测结果叠加，验证 ROI 是否正确
   - 保存到 camera_points 表
   - 坐标归一化（0-1）存储
   - **必须处理缩放**：用容器实际尺寸换算归一化坐标

【约束】
- WebSocket 断线不影响页面其他功能
- 检测框叠加必须与图像严格对齐（同坐标系）
- 违规流不自动滚动打断用户阅读
- 视频失败要有明确降级提示，不能白屏
- 大屏页面在 1920×1080 下布局不溢出

【验收】
- WebSocket 断线自动重连成功
- 检测框与视频对齐
- ROI 标定可保存并生效
- 1920×1080 与 1366×768 下布局正常

【汇报】
输出：WebSocket 消息协议、ConnectionManager 实现要点、
      视频降级策略链、检测框叠加的坐标系方案、
      ROI 标定的坐标换算实现、布局适配说明。
```

---

## 第 7 部分：P4 阶段提示词（小程序改造）

> **目标**：把只有"拍照自查"的小程序扩展为完整的学生端。
> **风格**：**必须与现有 `index.vue` 的 Apple 风格完全一致**，绝不破坏现有审美。

### 7.1 P4-1：请求层与登录

```
【任务】建立小程序请求层、登录流程、状态管理。

【执行步骤】
1. 创建 miniprogram/src/utils/api.ts：
   - 基于 uni.request 的请求封装
   - 自动注入 Authorization Bearer token（从 storage 取）
   - 统一解包 { code, data, message }
   - 401 → 用 refresh token 静默刷新 → 重放原请求（**只重放一次**，
     防无限循环）
   - 错误码映射（复用 selfcheck.ts 的 detailToText 思路，
     但扩展到业务错误码）
   - 请求超时 15s
   - **并发刷新锁**：多个请求同时 401 时，只发一个刷新请求，
     其余等待同一个 Promise
2. 创建 miniprogram/src/utils/auth.ts：
   - token 存储（uni.setStorageSync）
   - login()：uni.login → 拿 code → 调 /api/v1/auth/login → 存 token
   - 首次登录需绑定学号 → /api/v1/auth/bind-student
   - logout()：清 token + 调后端登出
   - getProfile()
3. 创建 miniprogram/src/stores/（用轻量 composable 而非引入 Pinia，
   保持小程序包体小）：
   - useUserStore.ts：用户信息、登录态、角色
   - useScoreStore.ts：积分、等级、排名、连续合规
   - useNoticeStore.ts：未读通知数
   每个 store 提供 readonly 状态 + 显式 refresh 方法
4. 创建 miniprogram/src/pages/auth/auth.vue（登录/绑定学号页）
   - 步骤：微信授权登录 → 输入学号 → 绑定成功 → 跳转首页
   - 学号校验：8-12 位数字
   - **知情同意书**：首次进入必须展示《校园骑行安全监测知情同意书》
     （勾选才能继续），内容涵盖采集目的、范围、保留期、权利
   - Apple 风格：简洁、留白、无花哨
5. 更新 miniprogram/src/pages.json：
   - 添加 auth / home / records / record-detail / appeal / vehicle /
     vehicle-list / rank / mall / profile 页面
   - 设 tabBar（4 个：首页 / 记录 / 排行 / 我的）
   - globalStyle 统一为现有配色（#F7F7F9）
6. 更新 miniprogram/src/manifest.json（若需要）：
   - 微信小程序 appid 走环境变量或 .env，不硬编码
   - 权限说明：scope.camera、scope.userLocation（按需）

【约束】
- 现有 `src/pages/index/index.vue` 与 `src/utils/selfcheck.ts` **不得破坏**
  （自查功能是重要资产）
- 保持 uni.setStorageSync 的 BaseURL 逻辑不变（开发时需要连本地后端）
- 小程序不使用 Pinia（包体考虑），用 composable 即可
- 所有页面必须处理 loading / empty / error
- 网络失败必须有明确文案 + 重试按钮

【验收】
- 登录 → 绑定学号 → 进首页 全流程通
- token 刷新并发安全
- 知情同意不可跳过
- 现有自查功能不受影响（回归测试）

【汇报】
输出：请求层架构图、token 刷新并发锁实现、
      知情同意书全文、pages.json 与 tabBar 配置、自检结果。
```

### 7.2 P4-2：首页（积分总览）

```
【任务】实现小程序首页 —— 激励导向，不做惩罚感。

【设计要求（Apple HIG 风格，严格遵守）】
- 使用现有 index.vue 的设计令牌（#F7F7F9 背景、18px 卡片圆角、
  #1C1C1E 主文字、#8E8E93 次文字、#F2F2F7 分隔线）
- **禁止**：渐变、阴影堆叠、花哨动效、彩色大块、emoji 装饰
- 卡片用白底 + 无边框或 1px #F2F2F7 极浅边框 + 圆角 18px
- 层级靠留白与字重建立

【页面结构】
┌─────────────────────────────────┐
│  早上好，同学              🔔(3)│   ← 顶栏 32px 大标题
├─────────────────────────────────┤
│  ┌───────────────────────────┐  │
│  │  文明积分                    │  │   ← 主卡：白色，18px 圆角
│  │  95                          │  │      数值 40px semibold
│  │  等级 A · 超过全校 82%      │  │      辅助信息 13px 次要色
│  │  ▓▓▓▓▓▓▓▓░░                │  │      进度条 4px 高，8px 圆角
│  │  连续安全骑行 12 天          │  │
│  │  ┌─────────┬─────────┐    │  │
│  │  │30天佩戴率│ 本期排名 │    │  │   ← 两个次级指标，2列网格
│  │  │  96.4%   │ 第128名 │    │  │
│  │  └─────────┴─────────┘    │  │
│  └───────────────────────────┘  │
├─────────────────────────────────┤
│  ┌───────────────────────────┐  │
│  │  ⚠ 您有一条待确认提醒        │  │   ← 提醒卡：浅橙底 #FEF3C7
│  │  08:12 东校门 检测到未佩戴头盔│  │      左侧 3px 橙色竖条
│  │  查看详情           去申诉  │  │      两个文字按钮并列
│  └───────────────────────────┘  │
├─────────────────────────────────┤
│  我的工具                        │
│  ┌────┬────┬────┬────┐        │   ← 2×2 or 1×4 网格
│  │拍照 │车辆 │排行 │商城 │        │      图标用 CSS 绘制（不引图标库）
│  │自查 │绑定 │榜   │    │        │
│  └────┴────┴────┴────┘        │
├─────────────────────────────────┤
│  近期记录（最近 3 条）      查看全部│
│  · 11-14  未佩戴头盔      -1 分   │
│  · 11-10  连续合规奖励    +2 分   │
│  · 11-08  未佩戴头盔      提醒     │
└─────────────────────────────────┘

【实现步骤】
1. 创建 miniprogram/src/components/score-card/ScoreCard.vue
   - props: score, level, percentile, streakDays, complianceRate, rank
   - 进度条：宽度 = percentile%，4px 高，8px 圆角，主色
2. 创建 miniprogram/src/components/notice-banner/NoticeBanner.vue
   - props: level, title, subtitle, actions[]
   - 配色：L1 浅橙 #FEF3C7 + #B54708 文字；L2/L3 浅红 #FDECEA + #7A2E0E
   - **注意**：不用"违规"字样，用"待确认提醒"
3. 创建 miniprogram/src/components/record-item/RecordItem.vue
   - 左侧：类型图标（CSS 绘制）+ 标题 + 时间
   - 右侧：分值变动（+ 绿 #1F9D46 / - 红 #D92D20 / 提醒 灰 #8E8E93）
   - 底部 1px #F2F2F7 分隔线（最后一项无）
4. 创建 miniprogram/src/pages/home/home.vue
   - onShow 时刷新数据
   - 下拉刷新
   - 数据加载失败：显示重试（不用空白）
5. 创建 miniprogram/src/utils/format.ts
   - formatDate / formatRelativeTime（"3分钟前"/"昨天 08:12"）
   - formatScoreDelta（带符号）
   - maskName（"张*"/"李**"，注意：这与后端的脱敏策略要一致）
6. API：GET /api/v1/me/score、GET /api/v1/me/records?limit=3

【约束】
- 严格复用现有设计令牌，不引入新色（除状态色）
- 不引入图标库（用 CSS/Unicode 几何图形绘制，风格统一）
- 首页第一屏必须是正面的分数与排名，不是扣分记录
- 提醒文案不得使用"处罚""罚款""违规"字样
- 触控目标 ≥ 44px

【验收】
- 首页渲染正确，数据来自 API
- loading / empty / error 三态
- 视觉与现有 index.vue 完全同源（同一套令牌与节奏）
- 触控区域足够大

【汇报】
输出：页面结构说明、组件清单与 props、配色方案表（每个元素对应的令牌）、
      与现有 index.vue 的一致性说明、截图描述。
```

### 7.3 P4-3：记录详情与申诉流程

```
【任务】实现记录详情页与申诉提交流程。

【页面 1：records/records.vue（我的记录）】
- 分栏切换：全部 / 扣分 / 提醒 / 加分 / 申诉
- 列表复用 RecordItem
- 分页：触底加载更多（onReachBottom）
- 筛选：时间范围（近7天/近30天/全部）
- 空态："还没有记录" + "去拍照自查"引导

【页面 2：record-detail/detail.vue（记录详情）】
结构：
┌─────────────────────────────────┐
│  ← 返回                详情      │
├─────────────────────────────────┤
│  ┌───────────────────────────┐  │
│  │  ⚠ 未佩戴头盔              │  │   ← 状态卡（按类型着色）
│  │  2026-11-14 08:12          │  │
│  │  东校门 · 出校方向          │  │
│  └───────────────────────────┘  │
│  ┌───────────────────────────┐  │
│  │  证据                       │  │
│  │  [证据图 + 检测框叠加]      │  │
│  │  说明：本记录由 AI 初步判定   │  │
│  │  并经管理员复核确认         │  │
│  └───────────────────────────┘  │
│  ┌───────────────────────────┐  │
│  │  扣分明细                   │  │
│  │  变动   -1 分               │  │
│  │  余额   95 → 94             │  │
│  │  原因   近30天第2次未佩戴    │  │
│  │  时间   2026-11-14 09:03    │  │
│  └───────────────────────────┘  │
│  ┌───────────────────────────┐  │
│  │  申诉状态                   │  │
│  │  ● 已提交申诉  等待处理      │  │
│  │  提交于 2026-11-14 10:20    │  │
│  └───────────────────────────┘  │
│  [ 发起申诉 ]  或  [ 查看申诉进度 ]│
└─────────────────────────────────┘

【页面 3：appeal/appeal.vue（提交申诉）】
- 表单：
  · 申诉类型（下拉：拍摄角度问题 / 当时未骑车 / 车辆不属于我 /
                系统识别错误 / 其他）
  · 说明（多行文本，必填，≥15 字，最多 500 字，带字数计数）
  · 附件（最多 3 张图片，可拍照或相册）
  · 提交后不可修改（提示）
- 提交前提示："申诉将由学生工作部门人工复核，通常 3 个工作日内答复"
- 提交成功：明确告知后续流程与查询入口

【组件】
- evidence-viewer：复用 DetectionOverlay 逻辑（与后台同一套，
  但小程序版本独立实现，坐标系处理必须一致）
- appeal-form：表单组件

【关键逻辑】
- 处罚中（pending_review）的记录**不允许申诉**（还没生效）
  → 显示"该提醒尚未确认，暂无需申诉"（这符合"待确认提醒"的产品语义）
- 已生效的记录在申诉窗口期内（默认 7 天）可申诉
- 超出窗口期按钮禁用 + 说明

【约束】
- 图片上传前压缩（宽度不超过 1280，单张 < 300KB）
- 上传前校验类型与大小
- 表单字段级校验 + 提交中禁用
- 失败保留用户已填内容
- 文案不得指责学生

【验收】
- 三个页面流程完整
- 申诉窗口期逻辑正确
- 图片压缩有效
- 失败时输入保留

【汇报】
输出：三页面结构、申诉窗口期规则实现、
      图片压缩方案、校验规则清单。
```

### 7.4 P4-4：车辆绑定、排行榜、商城、个人中心

```
【任务】实现剩余小程序页面。

【页面 1：vehicle/vehicle.vue（车辆绑定）】★核心
- 表单：
  · 车牌号（输入，校验：省份简称+字母+5位，或校园号牌格式）
  · 车辆类型（下拉：电动自行车 / 电动摩托车 / 校内部电动车 / 其他）
  · 行驶证照片（必传，1 张）
  · 车辆照片（必传，1 张，含车牌）
  · 车牌特写照片（选填）
- 提交后进入"待审核"状态，页面展示审核进度
- 我的车辆列表（vehicle-list.vue）：展示已绑定车辆 + 审核状态
  · 待审核：灰色卡片 + "审核中"
  · 已通过：正常卡片 + 车牌号 + 绑定方式（登记/二维码/自动匹配）
  · 被驳回：浅红卡片 + 驳回原因 + "重新提交"按钮
- **未匹配车辆的确认**：首页/记录页出现"疑似是你的车辆"时，
  提示"这是你的车吗？"→ 确认/否认（调 /me/vehicles/{id}/confirm）
  这是降低绑定成本的关键设计

【页面 2：rank/rank.vue（排行榜）】
- 切换：班级榜 / 年级榜 / 全校榜 / 合规榜（连续天数）
- 列表：排名、前三名特殊展示（不用奖杯 emoji，用数字徽章）、
  姓名（脱敏）、班级、积分/合规天数
- 当前用户所在行高亮
- 我的排名固定在顶部（即使不在榜单内）
- 说明文字："排名仅在院系内公开"

【页面 3：mall/mall.vue（积分商城）】
- 商品列表：图片、名称、所需积分、库存、状态
- 兑换流程：确认弹窗 → 扣积分 → 生成兑换记录
- 我的兑换记录
- **积分不足时**：显示"还差 X 分"，不置灰不可点，给出获取途径
- 商品分类：头盔 / 防护用品 / 文创 / 优惠券

【页面 4：profile/profile.vue（个人中心）】
- 头像 + 姓名（脱敏） + 学号（部分掩码） + 班级
- 积分与等级入口
- 菜单列表（iOS 风格分组列表）：
  我的记录 / 我的申诉 / 我的车辆 / 我的兑换 / 消息通知 / 隐私政策 /
  知情同意书 / 通知设置 / 关于我们 / 退出登录
- 退出登录：二次确认
- 隐私政策与知情同意书：完整可滚动文本页

【通用要求】
- 全部 Apple HIG 风格，复用设计令牌
- 每个页面独立 loading / empty / error
- 图片上传统一走同一个工具（压缩 + 校验 + 进度）
- 不引入新依赖

【约束】
- 排行榜不展示完整学号
- 商城扣分必须通过后端接口，前端不计算余额
- 车辆绑定上传的图片要压缩到 < 500KB
- 退出登录清理所有本地状态

【验收】
- 5 个页面功能完整
- 车辆绑定全流程通（含审核状态展示）
- 排行榜脱敏正确
- 商城扣分与服务端一致

【汇报】
输出：五页面结构、组件复用情况、
      车辆绑定的状态机、商城扣分一致性保证方式。
```

---

## 第 8 部分：P5 阶段提示词（模型精度）

### 8.1 P5-1：数据审计与两阶段训练准备

```
【任务】审计数据集并为两阶段重构准备数据。

【执行步骤】
1. 运行 P0-4 建立的 scripts/audit_dataset.py，生成审计报告。
2. **数据泄漏排查**：
   - 用感知哈希（pHash）找出 train/val/test 之间的重复图
   - 用同一视频的连续帧检测（相邻帧 SSIM > 0.95）
   - 有泄漏 → **重新按 session 分组划分**（不是随机划分）
3. 类别分布分析：
   - 统计每个 split 的每类实例数、每图目标数分布
   - 计算类别不均衡比
   - 特别检查 no helmet 的数量与质量
4. 建立 data.yaml（YOLOv8 格式）：
   - 确认类别顺序与实际标签一致（从标签统计得出，不靠记忆）
   - train/val/test 路径用相对路径（保证可移植）
5. **构建头部分类数据集**（两阶段法的关键）：
   编写 scripts/build_head_dataset.py：
   - 从 YOLO 标注自动生成头部 ROI：
     步骤 1：读标注，找 Cyclists 框
     步骤 2：裁剪头部 ROI（上部 45%，横向 25%-75%）
     步骤 3：找与该 ROI 相关的 helmet / no helmet 框
             （中心落在 ROI 内 → 对应标签）
     步骤 4：无关联标签 → 标 ambiguous 或丢弃（统计丢弃率）
     步骤 5：分 split 划分（**必须沿用检测集的 session 分组**，防泄漏）
   - 目录结构：
     dataset/head_cls/
       train/helmet/  train/no_helmet/  train/ambiguous/  train/other/
       val/...  test/...
   - 输出统计报告：各 split 各类的数量、丢弃率、
     **并用同样的划分逻辑在检测集 val 上做一次人工抽检（50 张）验证正确率**
6. 训练集增强脚本 scripts/augment_dataset.py：
   - copy-paste 增强 no helmet（稀有类）
   - 光照/运动模糊/压缩增强（校园场景差异大）
   - **增强后的样本必须写入新目录，不污染原数据集**
7. 编写 scripts/validate_dataset.py：
   - 每次训练前自动运行，校验通过才允许训练
   - 校验项：图片可读、标签格式、坐标范围、类别越界、空标签率、
     **split 间 pHash 重复率**、类别分布
   - 不通过则退出码非 0

【约束】
- 不修改原始数据集文件
- 所有脚本幂等（可重复运行）
- 所有脚本有 --help 与参数校验
- 划分必须确定性（固定随机种子，记录种子值）

【验收】
- 审计报告完整（真实数字）
- 泄漏检查通过或已重新划分
- 头部分类数据集生成成功，人工抽检正确率 ≥ 90%
- validate_dataset.py 可阻止有问题的训练

【汇报】
输出：审计报告摘要、泄漏排查结果、重新划分方案、
      头部分类数据集统计与抽检结果、增强脚本说明、
      validate 校验项清单。
```

### 8.2 P5-2：两阶段模型训练与集成

```
【任务】训练头部分类器并集成到采集管线。

【训练部分】
1. 训练头部分类器：
   - 模型：mobilenet_v3_small（预训练，10MB，边缘友好）
   - 输入：128×128，归一化用 ImageNet 统计量
   - 增强：RandomResizedCrop(128)、水平翻转、RandomRotation(10°)、
           ColorJitter(0.3/0.3/0.2/0.05)、RandomErasing(p=0.2)
   - 损失：CrossEntropyLoss(label_smoothing=0.05)
   - 优化：AdamW(lr=3e-4, weight_decay=1e-4) + CosineAnnealingLR
   - 早停：val loss 连续 10 epoch 不降则停（patience=10）
   - 指标：accuracy / macro-F1 / **每类 recall** / 混淆矩阵
   - **必须做温度标定**（Temperature Scaling），
     使 conf=0.7 真正对应 70% 正确率（否则置信度阈值不可用）
2. 训练两阶段检测器（可选优化）：
   - 若 head_cls 精度达标，可把检测模型简化为只检测 Cyclists
     （训练一个二类检测器，或从原权重中筛出 Cyclists 类）
   - 好处：召回率可到 95%+，且省掉两个极小目标类别
   - 与原三分类模型做 A/B 对比（用同一测试集）
3. 保存产物：
   - weights/head_cls_best.pt（含类别映射与温度参数）
   - 附带 model_card.json：架构、输入尺寸、类别、指标、
     温度标定值、训练数据摘要、限制说明

【集成部分】
4. 创建 app/services/inference/head_classifier.py：
   - HeadClassifier 类（线程安全单例，参考 selfcheck.py 的 pin 机制）
     - 加载模型 + 温度标定
     - classify(roi: np.ndarray) -> HeadVerdict
       返回 label（helmet/no_helmet/ambiguous/other）、
             confidence（已温度标定）、raw_confidence
     - **必须做输入校验**：尺寸、空图、非 ndarray 都要明确报错
     - 加载失败要给出清晰原因（不暴露绝对路径，
       参考 selfcheck._weights_display）
   - 批量接口 classify_batch(rois) 提升吞吐
5. 创建 app/domain/head_roi.py（纯函数）：
   - extract_head_roi(rider_box, image_shape, top_ratio=0.45) -> np.ndarray
     纯几何计算，便于单测
   - 必须在**裁剪前**校验坐标在图像范围内，非法时返回 None
     （不得产生越界切片）
6. 改造 app/tracks.py：
   - 新增证据来源：FrameEvidence.head 现在可以来自分类器
   - **保持 decide_pass 的接口与语义不变**（跨帧投票逻辑完全复用）
   - 增加 ambiguous 的处理：ambiguous 视为"无证据"，
     但**不计入 riding 票数的分母**（避免 ambiguous 把人排除掉）
7. 改造 app/detect.py 的推理分支：
   - 流程：YOLO 检测 Cyclists → 追踪 → 裁剪头部 ROI →
           分类器判定 → 跨帧投票
   - **必须保留**：权重类别守卫、模型 pin、心跳上报、
     三态保守判定、幂等写入
   - 增加：可配置的头部分类器权重路径（环境变量）
   - 推理耗时统计（分别记录检测与分类耗时）
8. 单元测试：
   - extract_head_roi 的各种边界（框贴边、超出图像、零面积）
   - HeadClassifier 的输入校验
   - ambiguous 不影响 riding 票数分母
   - decide_pass 在新证据来源下的行为（复用旧测试 + 新增）
9. 集成测试：
   - 用 _smoke/bus.jpg 或采集的样例跑完整管线
   - 验证输出三态合理

【约束】
- 温度标定必须做，且温度值要记录在 model_card 里
- HeadClassifier 的模型加载失败必须有清晰降级路径
  （可退回原三分类检测模式）
- 不破坏 tracks.py 现有 API
- detect.py 的心跳与权重守卫逻辑不得改动

【验收】
- 头部分类器测试集 macro-F1 ≥ 0.85，no_helmet recall ≥ 0.80
- 温度标定后 ECE（Expected Calibration Error）< 0.05
- 集成管线跑通，三态输出合理
- 单元测试全绿

【汇报】
输出：分类器训练配置与结果（含混淆矩阵与每类 recall）、
      温度标定值与校准曲线、model_card 内容、
      两阶段 vs 原三分类的 A/B 对比、
      集成后管线的时序与耗时数据。
```

### 8.3 P5-3：推理性能优化与边缘部署

```
【任务】把推理优化到可边缘部署。

【执行步骤】
1. 推理优化（按收益排序，逐项实施并测量）：
   - ONNX 导出与 Runtime 推理（提供 export_onnx.py 脚本）
   - FP16 推理（GPU）/ INT8 量化（提供量化脚本 + 精度对比）
   - 抽帧到 10-15 FPS（骑行判定不需要全帧率）
   - ROI 裁剪后再推理（只处理通道区域）
   - 推理与写库解耦（队列 + 工作线程）
   - 模型蒸馏：yolov8m → yolov8s（提供蒸馏脚本或说明）
2. 建立基准测试脚本 scripts/benchmark.py：
   - 输入：测试集图片 or 视频
   - 输出：FPS、平均延迟、P95 延迟、CPU 占用、内存占用
   - 支持 --device cpu/cuda、--precision fp32/fp16/int8、--backend onnx/torch
   - **给出 CPU 目标平台的基准结果**（这是答辩要的数字）
3. 目标性能：
   - CPU（普通 x86）：≥ 8 FPS @ 640
   - 边缘盒子（RK3588/Jetson）：≥ 15 FPS @ 640
   - 端到端延迟（帧 → 事件落库）：< 300ms
4. 采集管线重构 app/detect.py：
   - 改为类 Pipeline 的结构：
     CaptureStage（读帧 + 抽帧）
       → InferenceStage（检测 + 追踪 + 分类）
       → EventStage（判定 + 去重 + 落库）
       → AlertStage（提醒调度）
   - 各阶段用有界队列解耦
   - 队列满时的策略：推理阶段丢帧（保实时），
     事件阶段阻塞（保数据）—— 必须写清理由
   - **心跳仍由采集主循环上报**，反映真实 FPS
5. 多点位支持：
   - app/capture/worker.py：单点位 worker（一个进程）
   - app/capture/scheduler.py：多点位调度（进程池）
   - 每个点位独立心跳与独立配置（从 DB 读点位配置）
   - 单点位崩溃不影响其他点位
6. 点位配置 DB 化（替换 config.py 硬编码）：
   - camera_points 表已建，需补齐 ROI/计数线/提醒区的读取逻辑
   - config.py 保留但改为「从 DB 读取 + 本地缓存 + 环境变量覆盖」的三级优先级
   - 保留 get_point_config(point_id) 兼容签名
7. 单元测试：
   - Pipeline 各阶段的队列行为
   - 队列满时的丢弃/阻塞策略符合预期
   - 多点位隔离（一个点位异常不影响另一个）

【约束】
- 重构后心跳、权重守卫、幂等写入、三态判定全部保留
- 性能优化必须实测数据支撑，不能只说"应该更快"
- 采集进程在无 GPU 的机器上要能跑

【验收】
- 基准脚本产出真实数据表
- 达到上述 FPS 目标（或明确说明差距与原因）
- 多点位可并行运行
- 既有测试全绿

【汇报】
输出：优化项收益对照表（优化前/后 FPS 与延迟）、
      Pipeline 架构图与队列策略说明、
      各目标平台的基准数据、配置三级优先级的实现、
      测试结果。
```

---

## 第 9 部分：P6 阶段提示词（通知触达）

```
【任务】实现通知服务抽象与多渠道触达。

【执行步骤】
1. 创建 app/services/notification/ 抽象层：
   - BaseChannel（Protocol）：
     send(notification: NotificationPayload) -> SendResult
     统一接口，所有渠道实现同一契约
   - NotificationPayload：receiver, template_code, title, content,
     data（业务数据）, level, expires_at
   - SendResult：success, channel_message_id, error, retryable
   - NotificationDispatcher：
     - 按 channel 分发
     - 失败重试（指数退避，渠道可声明是否可重试）
     - 幂等（同一 notification_id 不重复发）
     - 记录投递状态到 notifications 表
2. 渠道实现：
   - InAppChannel（站内信，必做）：直接写 notifications 表
   - WeChatSubscribeChannel（微信订阅消息）：
     * 调微信 API（httpx，带 access_token 缓存与刷新）
     * **订阅消息配额管理**：subscribe_messages 表记录剩余次数
     * 用户未授权时返回明确失败原因（不是报错）
   - SmsChannel（短信）：
     * 抽象 SmsProvider（预留对接服务商）
     * 默认实现 NoopSmsProvider（记录日志不真发）
     * **默认关闭**，需显式配置启用
   - WeComChannel（企业微信/钉钉机器人）：
     * Webhook 推送（httpx + 超时 + 重试）
     * 用于管理员通知（审批积压、熔断告警）
3. 模板系统 app/services/notification/templates.py：
   - 模板用 Python 字符串 + {占位符}
   - 每种通知类型一个模板（violation_detected / score_changed /
     appeal_submitted / appeal_resolved / award_granted /
     approval_pending / system_alert）
   - 模板渲染用 str.format_map + 严格占位符检查
     （缺占位符或多余变量要抛错，不静默失败）
4. 触发点接入：
   - 决策生效后 → 站内信 + 订阅消息（通知学生）
   - 申诉提交后 → 站内信 + 企业微信（通知处理人）
   - 申诉裁决后 → 站内信（通知学生）
   - 审批积压 > 阈值 / 熔断触发 → 企业微信（通知管理员）
   - 奖励发放 → 站内信 + 订阅消息
5. 通知偏好与免打扰：
   - students 表加 notification_preferences JSON 字段
   - 免打扰时段内的事件延迟到时段结束发送（延迟队列）
   - 频控：同类型通知每人每天最多 N 条
6. 定时任务（Celery）：
   - beat 任务：延迟通知发送、审批超时扫描、证据过期清理、
     共现矩阵重算、报表生成
7. 测试：
   - 模板渲染（正常 + 缺占位符 + 多余变量）
   - 各渠道的 mock 测试
   - 微信配额扣减与耗尽行为
   - 免打扰延迟逻辑
   - 频控

【约束】
- 所有渠道调用必须有超时
- 通知内容不得包含证据图片 URL 之外的敏感信息
- 学生通知不得直接暴露"其他学生"信息
- 短信默认关闭
- 通知失败不能影响主业务（决策生效成功即成功，通知失败只记录）

【验收】
- 各渠道 mock 测试通过
- 免打扰与频控生效
- 通知失败不影响主流程
- 定时任务可配置与可观测

【汇报】
输出：渠道抽象设计图、模板清单、触发点接入表、
      免打扰与频控规则、配额管理实现、测试结果。
```

---

## 第 10 部分：前端视觉规范（Apple HIG 设计系统）

> **本部分是所有前端提示词的强制附录，可单独复制给 Cursor。**

```
【任务】为 admin-web 与 miniprogram 建立统一的 Apple HIG 风格设计系统。
只做设计系统与基础组件，不做业务页面。

═══════════════════════════════════════
一、设计原则（不可违背）
═══════════════════════════════════════
1. 克制 —— 内容优先，装饰最后。界面应让人专注于数据与操作，而非界面本身。
2. 清晰 —— 层级靠留白、字重、对比度建立，不靠颜色堆砌或装饰。
3. 一致 —— 相同含义用相同表达；同一控件在不同页面表现一致。
4. 效率 —— 高频操作要快（快捷键、批量、记忆位置）。

═══════════════════════════════════════
二、色彩（严格使用以下令牌，禁止在组件里写原始色值）
═══════════════════════════════════════
【语义色】每类只给 1 个主色 + 少量必要变体
  --color-primary:        #007AFF   /* 主色：选中、主按钮、进度、链接 */
  --color-primary-hover:  #0A84FF
  --color-primary-active: #0062CC
  --color-primary-tint:   rgba(0,122,255,0.10)

  --color-success:        #1F9D46   /* 合规、已通过、增长 */
  --color-success-tint:   rgba(31,157,70,0.10)
  --color-danger:         #D92D20   /* 违规、驳回、失败、下降 */
  --color-danger-tint:    rgba(217,45,32,0.10)
  --color-warning:        #FF9500   /* 待处理、提醒 */
  --color-warning-tint:   #FEF3C7   /* 浅底 */
  --color-warning-text:   #B54708   /* 浅底上的文字色 */

【中性色阶】
  --color-bg:        #F7F7F9   /* 页面背景 */
  --color-surface:   #FFFFFF   /* 卡片/面板背景 */
  --color-surface-2: #F2F2F7   /* 次级填充、输入框底、hover */
  --color-sep:       #F2F2F7   /* 分隔线 */
  --color-sep-strong:#E5E5EA   /* 强分隔线（表格行分隔）*/
  --color-text:      #1C1C1E   /* 主文字 */
  --color-text-2:    #6E6E73   /* 次要文字 */
  --color-text-3:    #8E8E93   /* 三级文字/占位 */
  --color-text-4:    #C7C7CC   /* 禁用文字 */
  --color-border:    #E5E5EA   /* 输入框边框 */
  --color-overlay:   rgba(0,0,0,0.4) /* 遮罩 */

【暗色模式】（prefers-color-scheme: dark）
  --color-bg:        #000000
  --color-surface:   #1C1C1E
  --color-surface-2: #2C2C2E
  --color-sep:       #38383A
  --color-text:      #F2F2F7
  --color-text-2:    #AEAEB2
  --color-text-3:    #8E8E93
  --color-primary:   #0A84FF

【用色纪律】
- 一个视图内**最多 3 种色相**同时出现（主色 + 1 状态色）
- 状态色只用于小面积（色点、图标、徽章、左边条），不用大面积填充
- 表格、表单、导航等结构区域一律用中性色
- 红色仅用于真正的失败/违规/危险操作，出现即需注意
- 不用红绿对（色盲不友好）—— 状态必须同时有图标或文字

═══════════════════════════════════════
三、字体与排版
═══════════════════════════════════════
字体族：
  -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC",
  "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif
等宽（编号、置信度、坐标）：
  ui-monospace, "SF Mono", "JetBrains Mono", Consolas, monospace

字号层级（最多 4 级）：
  --text-large-title: 32px / 40px / 700 / -0.6px    /* 页面大标题 */
  --text-title:       22px / 28px / 600 / -0.3px    /* 区块标题 */
  --text-headline:    17px / 22px / 600 / -0.2px    /* 卡片标题 */
  --text-body:        15px / 21px / 400             /* 正文 */
  --text-subhead:     15px / 21px / 600             /* 强调正文 */
  --text-footnote:    13px / 18px / 400             /* 辅助说明 */
  --text-caption:     12px / 16px / 400             /* 标签/计数 */

数字对齐：所有数值型内容使用 font-variant-numeric: tabular-nums

═══════════════════════════════════════
四、间距与布局
═══════════════════════════════════════
间距刻度（4 的倍数，只用这些）：
  --space-1: 4px   --space-2: 8px   --space-3: 12px
  --space-4: 16px  --space-5: 20px  --space-6: 24px
  --space-8: 32px  --space-10: 40px --space-12: 48px

圆角：
  --radius-sm: 8px    /* 输入框、小标签 */
  --radius-md: 10px   /* 徽章、tooltip */
  --radius-lg: 14px   /* 按钮 */
  --radius-xl: 18px   /* 卡片 */
  --radius-full: 999px /* 头像、进度条 */

阴影（最多一层，非常轻）：
  --shadow-card: 0 1px 8px rgba(0,0,0,0.06)
  --shadow-pop:  0 4px 20px rgba(0,0,0,0.10)
  （不要用 2px 描边 + 阴影 + 渐变这种"立体卡片"）

页面边距：20px（移动端）/ 24px（后台内容区）
卡片内边距：16-18px
卡片间距：12-14px

═══════════════════════════════════════
五、组件规范
═══════════════════════════════════════
按钮：
  - 主按钮：主色实底、白字、圆角 14px、高 44px（移动）/ 36px（桌面）、
            字号 17px/600（移动）或 14px/500（桌面）
  - 次按钮：--color-surface-2 底、主色字、同尺寸
  - 危险按钮：--color-danger 底、白字
  - 禁用：opacity 0.4
  - 加载：文字替换为 spinner（用 CSS 边框旋转，不要用图标库）
  - 最小点击区 44×44px

输入框：
  - 高度 44px（移动）/ 36px（桌面）
  - 圆角 10px，底色 --color-surface-2，边框 1px --color-border
  - focus：边框主色 + 3px primary-tint 外发光
  - error：边框 danger + 下方 12px 错误文案

列表/表格：
  - 行高 48px（移动）/ 44px（桌面）
  - 行分隔线 1px --color-sep-strong，最后一行无分隔线
  - 表头 12px --color-text-3，不加粗到 600 以外
  - hover：--color-surface-2
  - 选中：primary-tint 底 + 左侧 2px 主色条（移动端列表用）

卡片：
  - 白底 + --radius-xl + --shadow-card（或无阴影加 1px 极浅边框，二选一，全局统一）
  - 标题 17px/600 + 说明 13px/--color-text-2

空状态：
  - 图标（CSS 绘制的简单几何形，48px，--color-text-4）
  - 主文案 15px/600 + 补充说明 13px/--color-text-2
  - 可选操作按钮

徽章/标签：
  - 高 22px，圆角 --radius-full，内边距 0 8px，字号 12px
  - 浅底 + 深字（如 warning: #FEF3C7 底 + #B54708 字）

进度条：
  - 高 4px（或 6px），圆角 --radius-full，轨道 --color-surface-2
  - 填充主色

═══════════════════════════════════════
六、动效
═══════════════════════════════════════
时长：--duration-fast: 150ms   --duration-base: 250ms   --duration-slow: 350ms
缓动：--ease-standard: cubic-bezier(0.4, 0, 0.2, 1)
     --ease-decel:    cubic-bezier(0, 0, 0.2, 1)

允许的动效（仅这些）：
  - 状态切换（hover、active、focus）
  - 折叠/展开（高度 + 透明度）
  - 列表项进入（淡入 + 4px 上移，200ms）
  - 数字变化（淡出淡入，不用滚动动画）

禁止：
  - 弹跳、旋转、缩放、3D、粒子、视差
  - 循环动画（loading 指示器除外）
  - 超过 350ms 的过渡
  - 页面切换的滑动转场（保持简单淡入或无转场）

prefers-reduced-motion: reduce 时全部禁用

═══════════════════════════════════════
七、禁止清单（Code Review 时逐条检查）
═══════════════════════════════════════
❌ 渐变（linear-gradient / radial-gradient）—— 除纯遮罩
❌ 多层阴影（box-shadow 里多个 offset）
❌ 毛玻璃（backdrop-filter: blur）
❌ !important
❌ 魔法数值（颜色/间距/圆角/字号必须用 var())
❌ emoji 作为功能图标
❌ 超过 4 级的文字层级
❌ < 44px 的触控目标（移动端）
❌ 纯色块大面积填充（除非是明确的选中态或状态卡）
❌ 动画超过 350ms
❌ 组件内硬编码 URL 或 API 路径
❌ any 类型
❌ 组件内 > 100 行的 <style> 块
❌ 颜色只靠红绿区分

═══════════════════════════════════════
八、交付物
═══════════════════════════════════════
1. admin-web/src/styles/design-tokens.scss    完整令牌（含暗色）
2. admin-web/src/styles/reset.scss
3. admin-web/src/styles/typography.scss        文字层级工具类
4. admin-web/src/styles/utilities.scss         间距/布局工具类
5. admin-web/src/styles/mixins.scss            常用 mixin（滚动条、截断、多行省略）
6. miniprogram/src/styles/tokens.scss          小程序版令牌（与后台同源）
7. miniprogram/src/styles/common.scss          小程序通用类
8. Element Plus 主题覆写（scss 变量方式，不用 CSS 变量覆盖）
9. 基础组件清单（后台 + 小程序）：
   后台：StatCard / PageHeader / DataTable / EmptyState /
         EvidenceViewer / FactorList / DecisionCard / RiskHint /
         StatusBadge / TrendChart / LevelTag / ScoreDelta
   小程序：ScoreCard / NoticeBanner / RecordItem / StatusBadge /
           EmptyState / SectionHeader / ActionSheet
10. 一个「设计规范速查卡」页面（内部工具，展示所有令牌与组件示例）

【验收】
- 令牌文件被全局使用，grep 检查无魔法色值/间距
- 暗色模式切换正常
- 基础组件全部有 props 类型定义与用法示例
- reduced-motion 生效
- 无渐变、无多层阴影、无 !important（用 grep 验证）

【汇报】
输出：令牌完整清单（CSS 变量名 → 值 → 用途）、
      组件清单与 props 签名、Element Plus 主题覆写清单、
      grep 违规检查结果、组件预览效果描述。
```

---

## 第 11 部分：质量门禁与验收提示词

### 11.1 持续集成配置

```
【任务】建立 CI 质量门禁，保证代码质量不随开发退化。

【后端】
1. 创建 .github/workflows/backend.yml（或 .gitlab-ci.yml）：
   - job: lint      → ruff check + ruff format --check
   - job: typecheck → mypy app（strict）
   - job: test      → pytest --cov=app --cov-report=xml
                     覆盖率门槛：整体 ≥ 70%，app/domain/ ≥ 90%
                     pytest-cov 的 fail_under 配置
   - job: security  → pip-audit + bandit（排除低危误报）
   - job: migration→ alembic upgrade head + alembic downgrade base + upgrade head
   - 所有 job 在 push 与 PR 时触发
2. 创建 .pre-commit-config.yaml：
   ruff / ruff-format / mypy / detect-secrets / check-added-large-files
   大文件阈值 5MB（.pt 权重与数据集除外）
3. Makefile / scripts/dev.ps1：
   make lint / format / typecheck / test / coverage / migrate / seed / dev

【前端】
4. admin-web/.github 或主 workflow 增加 frontend job：
   - npm ci
   - npm run type-check（vue-tsc --noEmit）
   - npm run lint（eslint --max-warnings 0）
   - npm run build
   - **加入设计规范检查脚本**：
     scripts/check-design-tokens.mjs
     · 扫描 src/**/*.vue 与 *.scss
     · 禁止出现 hex 颜色字面量（除 design-tokens.scss）
     · 禁止出现 !important
     · 禁止出现 linear-gradient / radial-gradient
     · 禁止出现 backdrop-filter
     · 违规则退出码非 0
5. miniprogram 同样加 type-check job

【验收】
- 本地一条命令可跑完全部检查
- CI 配置语法正确
- 设计规范检查脚本能抓到违规样例

【汇报】
输出：CI 流程图、各 job 配置说明、
      设计规范检查脚本的规则清单、Makefile 命令说明。
```

### 11.2 阶段验收提示词

```
【任务】对当前阶段成果做一次严格的质量审计。**不要修复，先报告。**

【审计维度】
1. 代码正确性
   - 有无逻辑错误、边界遗漏、空值处理缺失
   - 异常路径是否都处理了（不是只处理 happy path）
   - 事务边界是否正确（失败是否回滚）
   - 并发安全（是否用条件 UPDATE / 锁 / 幂等）
2. 安全
   - SQL 注入（是否有字符串拼接）
   - 越权（是否在 service 层强制，而非只靠前端）
   - 敏感信息泄露（日志、错误响应、API 返回）
   - 文件上传（类型/大小/路径）
   - 依赖漏洞
3. 性能
   - N+1 查询
   - 缺失索引
   - 同步阻塞调用（async 函数里做同步 IO）
   - 无界队列 / 无超时
4. 可维护性
   - 命名是否表意
   - 函数长度 / 圈复杂度 / 文件长度
   - 是否有重复代码
   - 注释是否解释"为什么"
   - 是否有魔法数字
5. 测试
   - 覆盖率与关键路径覆盖
   - 是否有 flaky 测试
   - 是否测了边界与错误路径
6. 规范符合度
   - 类型注解完整性
   - lint / format 是否通过
   - 是否有 TODO / 注释掉的代码 / pass 桩

【执行方式】
1. 运行所有检查命令，报告真实输出
2. 逐文件阅读本次改动的代码（不要只看 diff，要看完整文件）
3. 交叉验证关键设计：
   - 积分是否只有 LedgerService 能改（grep 确认）
   - 决策是否真的只由 domain 层决定（grep 确认）
   - 学生数据是否在 service 层做了归属校验
   - LLM 是否完全隔离于决策链路
4. 按严重程度分级：
   🔴 阻塞（正确性/安全/数据损坏）
   🟠 重要（性能/可维护性明显问题）
   🟡 建议（可读性/风格）

【输出格式】
每条问题：
  [严重度] 文件:行号 — 问题描述 — 影响 — 修复建议（具体到代码）
最后给出：
  - 统计：阻塞 X 个 / 重要 X 个 / 建议 X 个
  - 本阶段是否可以进入下一阶段（明确结论）
  - 如果不能，最优先要修的 3 个问题

【约束】
- 只报告不修改（除非我明确说"修"）
- 不要为了显得认真而吹毛求疵，聚焦真实问题
- 每条问题必须能定位到具体行，且有实际影响
```

---

## 第 12 部分：排错与重构提示词

### 12.1 Bug 排查

```
【任务】排查并修复以下问题：

【现象】
<粘贴日志/截图/错误信息>

【期望行为】
<描述正确行为>

【排查步骤（必须按序）】
1. **先复现**：找到最小复现路径，跑出稳定复现。
   如果不能复现，先加日志/断点收集证据，不要盲改。
2. **读代码**：阅读相关模块的**完整文件**（不是片段），
   画出调用链：入口 → 中间层 → 底层 → 副作用。
3. **列假设**：列出所有可能原因（至少 3 个），按可能性排序。
4. **逐一验证**：每个假设给出验证方法与验证结果。
   **必须用证据排除，不能靠猜。**
5. **定位根因**：区分「症状」与「根因」。
   很多"bug"是上游错误的表象（如空指针其实是"记录不存在"没处理）。
6. **最小修复**：只修根因，不做顺带重构（重构另开 PR）。
7. **补测试**：写一个能复现原 bug 的测试，先让它失败，再让它通过。
8. **回归**：跑全部测试确认无破坏。

【输出】
- 复现步骤
- 调用链
- 假设列表与验证结果（表格）
- 根因（精确到行）
- 修复 diff
- 新增测试
- 回归测试结果

【约束】
- 不允许"多打印几个 log 看看"就交付
- 不允许关闭测试或放宽断言来"修复"
- 不允许在没定位根因前就开始改代码
```

### 12.2 重构

```
【任务】重构 <模块/文件>，目标：<具体目标，如"让依赖方向符合分层规范">

【重构铁律】
1. **重构不改行为** —— 除非明确说了要改行为。
   重构前必须有测试覆盖（没有就先补测试）。
2. **小步进行** —— 每次一个原子改动，每步都跑测试。
3. **不夹带修复** —— 发现 bug 记录下来单独提，不在重构里顺手改。
4. **不扩大范围** —— 只动与目标相关的代码。

【执行步骤】
1. 现状分析：
   - 列出该模块的职责、对外接口、依赖
   - 指出与目标的差距（具体到文件与行）
   - 评估风险点
2. 设计目标结构：
   - 给出目标目录/文件结构
   - 给出每个模块的职责与接口
   - 说明依赖方向（上层依赖下层，反之禁止）
   - 说明迁移路径（是否需要兼容层、兼容多久）
3. 先补测试：
   - 为将被重构的逻辑补足单元测试
   - 覆盖正常路径 + 边界 + 错误路径
   - 测试必须能在重构前后都通过（证明行为等价）
4. 执行重构（原子步骤）：
   - 每步：改 → 跑测试 → 提交（逻辑上，不一定要 git commit）
   - 测试失败立即回退该步，不累积
5. 清理：
   - 删除死代码、废弃的兼容层（确认无引用后）
   - 删除注释掉的代码、TODO
   - 更新导入、类型注解
6. 验证：
   - 全部测试通过
   - lint / mypy / vue-tsc 零错误
   - 覆盖率不下降

【输出】
- 现状 vs 目标结构对比
- 依赖方向图（重构前/后）
- 迁移步骤与每步的测试结果
- 删除的代码清单
- 前后覆盖率对比

【约束】
- 不改变任何对外接口签名（除非明确要求）
- 不引入新依赖（除非明确要求）
- 不降低测试覆盖率
- 不留下 TODO / FIXME
```

### 12.3 性能优化

```
【任务】优化 <接口/模块> 的性能，当前：<指标>

【执行步骤】
1. **先测量**：
   - 写一个基准脚本/测试，能稳定复现当前性能
   - 记录基线：QPS、P50/P95/P99 延迟、CPU、内存、DB 查询数
   - **没有基线就不要开始优化**
2. **定位瓶颈**（按概率排查）：
   - 是否 N+1 查询（检查 SQL 日志 / 开启 SQLAlchemy echo）
   - 是否缺索引（EXPLAIN QUERY PLAN 分析慢查询）
   - 是否同步阻塞（async 里做同步 IO）
   - 是否重复计算（相同输入算多次）
   - 是否无缓存（可缓存的只读数据）
   - 是否返回了过多数据（字段裁剪 / 分页 / 限制大小）
   - 是否序列化开销大
3. **逐项优化并测量**：
   - 每次只做一项优化 → 重跑基准 → 记录收益
   - 收益 < 5% 的不保留（增加复杂度不值）
4. **保证正确性**：
   - 优化前后行为必须一致（写对比测试）
   - 缓存必须考虑失效策略，不能返回过期数据
   - 任何缓存都要有 TTL 或显式失效
5. **回归**：跑全部测试

【输出】
- 基线数据表
- 瓶颈定位过程（含 EXPLAIN 输出）
- 优化项清单：每项的前后数据
- 保留/放弃的决策及理由
- 正确性保证方式

【约束】
- 不牺牲正确性换性能
- 不引入复杂度换微小收益
- 优化后必须有量化数据
```

---

## 附录 A：Cursor 工作流操作手册

### A.1 每次开发的六步循环

```
1. 选阶段 → 从本文档取对应的提示词框
2. 整段粘贴给 Cursor（一次一个框）
3. Cursor 执行 → 要求它汇报（文件清单/设计决策/取舍）
4. 你亲自审查 diff（Cursor 报告 ≠ 代码正确）
5. 不满意 → 追加"上一次实现的问题"重新喂
6. 满意 → 跑门禁（lint/typecheck/test）→ 通过则进入下一框
```

### A.2 让 Cursor 自我审查的追加语

```
在我汇报之前，请先自查以下问题并一并回答：
1. 这次改动有没有引入 N+1 查询？
2. 有没有硬编码的魔法数、魔法字符串、魔法路径？
3. 异常路径是否都处理了？包括超时、空结果、部分失败？
4. 类型注解是否完整？前端有没有用 any？
5. 有没有把业务逻辑写在 router 层？
6. 并发场景下会不会有竞态？事务边界是否正确？
7. 新增的代码有没有配套测试？
8. 有没有 TODO / FIXME / 注释掉的代码 / pass 桩？
9. 这次改动是否破坏了对已有的接口契约？
10. 如果线上出问题，最可能的故障点在哪？
```

### A.3 让 Cursor 解释代码的提示语

```
请用以下格式解释 <文件路径>：

【职责】一句话
【对外接口】函数签名 + 用途
【依赖】它 import 了什么，依赖谁
【边界条件】它处理/不处理什么
【失败行为】出错时抛什么/返回什么/怎么降级
【调用者】谁在用它
【风险点】最容易出问题的地方

然后指出：这个实现有没有违反项目分层规范？
```

### A.4 上下文不足时的补充语

```
你缺少以下上下文，请先读这些文件再动手：
- <文件路径1>：<为什么需要它>
- <文件路径2>：<为什么需要它>

阅读之后再实现，不要假设。
```

### A.5 强制约束语（贴在每次提示词开头）

```
本次实现必须遵守：
- 不引入新依赖
- 不修改 <明确排除的目录/文件>，除非我另行说明
- 所有函数带完整类型注解
- 领域逻辑必须是纯函数，零 I/O
- 必须配套单元测试
- 禁止 TODO / FIXME / pass 桩 / 注释掉的代码
- 完成后运行 ruff + mypy + pytest 并报告结果
```

---

## 附录 B：提示词速查表

| 编号 | 任务 | 阶段 | 预计产出 |
|---|---|---|---|
| P0-1 | 工程基座初始化 | P0 | Git/依赖/配置/异常/安全/中间件/测试基座 |
| P0-2 | 数据库迁移与仓储基座 | P0 | Alembic/ORM/Repository/并发测试 |
| P0-3 | Vue3 后台骨架 | P0 | admin-web 完整骨架 + 设计令牌 |
| P0-4 | 数据集抢救 | P0 | 数据恢复 + 审计脚本 + LFS |
| P1-1 | 身份域数据模型 | P1 | 6 张新表 + 仓储 |
| P1-2 | 车辆外观特征 | P1 | 128 维 embedding + 匹配 |
| P1-3 | 多证据身份融合 | P1 | 对数似然融合 + 冲突检测 |
| P1-4 | 车牌 OCR 接入 | P1 | 检测 + 识别 + 校园号牌约束 |
| P1-5 | 共现图谱匹配 | P1 | 时间窗共现 + 匈牙利匹配 |
| P1-6 | 身份管理 API 与页面 | P1 | 5 组 API + 3 个后台页 |
| P2-1 | 积分域与积分服务 | P2 | 台账 + 规则 DSL + 一致性测试 |
| P2-2 | **AI 决策引擎** | P2 | 纯函数决策 + 熔断 + 回放 |
| P2-3 | 决策服务与审批流程 | P2 | 全链路 + 并发审批 + 申诉 |
| P2-4 | LLM 话术生成 | P2 | 模板兜底 + 校验 + PII 隔离 |
| P3-1 | Dashboard 总览 | P3 | 指标卡 + 图表 + 点位健康 |
| P3-2 | **审批中心** | P3 | 双栏 + 证据 + 快捷键 + 实时 |
| P3-3 | 其余后台页面 | P3 | 8 个页面 |
| P3-4 | 实时监控大屏 | P3 | WebSocket + 视频 + ROI 标定 |
| P4-1 | 小程序请求层与登录 | P4 | api/auth/store/知情同意 |
| P4-2 | 小程序首页 | P4 | 积分总览 + 提醒 + 工具 |
| P4-3 | 记录详情与申诉 | P4 | 3 页 + 申诉窗口期 |
| P4-4 | 车辆/排行/商城/我的 | P4 | 4 页 |
| P5-1 | 数据审计与两阶段准备 | P5 | 审计 + 头部分类数据集 |
| P5-2 | 两阶段训练与集成 | P5 | 分类器 + 温度标定 + 管线改造 |
| P5-3 | 性能优化与边缘部署 | P5 | ONNX/流水线/多点位/基准 |
| P6 | 通知触达 | P6 | 渠道抽象 + 模板 + 定时任务 |
| DS | 设计系统 | 全程 | 令牌 + 基础组件 + 检查脚本 |
| QA-1 | CI 质量门禁 | 全程 | workflow + pre-commit + 规范检查 |
| QA-2 | 阶段验收审计 | 每阶段 | 分级问题报告 |
| DBG | Bug 排查 | 随时 | 假设验证 + 根因 + 回归测试 |
| REF | 重构 | 随时 | 行为等价 + 覆盖率不降 |
| PERF | 性能优化 | 随时 | 基线 → 定位 → 量化 |

---

## 使用建议

**三条最重要的执行纪律：**

1. **绝不让 Cursor 一次做超过一个提示词框的量。** 一次做太多，代码质量必然下降，而且你很难审查。

2. **永远亲自看 diff。** Cursor 的汇报是它的自我评价，不是事实。`git diff` 是唯一真相。特别是：有没有偷偷引入依赖、有没有留 TODO、有没有把逻辑写错层。

3. **门禁不能跳。** 每完成一个框就跑 `ruff + mypy + pytest`。规范化的价值在于每次都执行——一次例外，后面就会有十次。

**关于"垃圾代码"的具体防线（这些是本项目最容易出问题的地方）：**

| 风险 | 防线 |
|---|---|
| 决策逻辑散落在各处 | 强制 `app/domain/decision.py` 是唯一决策源，其他地方只能调用 |
| 积分被绕过 LedgerService | 每次验收时 grep `UPDATE score_accounts` |
| 越权只在前端拦 | 每次验收时检查 service 层归属校验 |
| LLM 混进决策链路 | 架构上 domain 不 import ai/ |
| 魔法数字蔓延 | 阈值必须在 policy/常量，且有注释依据 |
| 异常被吞 | 禁止裸 except，异常必须处理或记录 |
| 测试缺失 | CI 覆盖率门槛 + domain 层 90% |
| 前端堆成屎山 | 单文件 ≤ 400 行、style ≤ 100 行、组件拆分 |

---

*文档版本 v1.0 · 2026-11-15*
*配套：`校园头盔检测提醒助手-项目深度分析与研发设计说明书.md`*
