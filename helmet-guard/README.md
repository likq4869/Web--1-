# 校园头盔检测提醒助手（Helmet Guard）

边缘侧 YOLOv8 头盔检测 + 后端分级决策 + 人工复核 + 积分闭环。

当前处于 **P0 工程基线**阶段：后端、采集、自查链路可用，工程化配置（依赖管理、
Git、类型检查、测试基线）已就位。业务表扩充、认证鉴权、管理后台尚未开始。

---

## 快速开始

### 1. 环境准备

需要 **Python 3.11 / 3.12**（3.13+ 暂未验证 `ultralytics` / `torch` 的 wheel 兼容性）。

```powershell
# 创建虚拟环境
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1

# 安装开发依赖（含采集/推理组）
pip install -e ".[dev,vision]"
```

### 2. 运行后端

```powershell
# 演示模式（默认，使用合成种子数据，不写业务数据到 live 库）
.\.venv\Scripts\python.exe -m app.seed_demo
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

启动后访问 <http://127.0.0.1:8000/docs> 查看接口文档。

### 3. 运行采集进程（真实摄像头）

```powershell
# live 模式：真实点位采集，写入 passes/events
.\.venv\Scripts\python.exe -m app.detect --source 0 --mode live `
    --weights runs/detect/helmet-v2-baseline/weights/best.pt
```

> `camera_check` 模式仅做预览（允许 COCO 通用权重），不写业务数据。

### 4. 微信小程序自查

```powershell
cd ..\miniprogram
npm install
npm run dev:mp-weixin
```

用微信开发者工具打开 `dist/dev/mp-weixin`。

---

## 目录结构

```
bisai/
├── helmet-guard/          # 后端 + 采集 + 算法（Python）
│   ├── app/
│   │   ├── main.py        # FastAPI 入口：8 个接口
│   │   ├── detect.py      # 采集进程：单摄像头 YOLOv8 track
│   │   ├── tracks.py      # 骑行判定与去重（纯函数）
│   │   ├── vision.py      # 权重校验与 ROI 几何（纯函数）
│   │   ├── selfcheck.py   # 拍照自查：模型 pin + 三态判定 + 推理名额控制
│   │   ├── db.py          # SQLite 表结构（6 张表）
│   │   ├── store.py       # 存储操作（短事务 + 参数化 SQL）
│   │   └── alerts.py      # 提醒队列与限频
│   ├── tests/             # 回归测试（34 个用例）
│   ├── dataset/           # 数据集（不进 Git，见 .gitignore）
│   └── runs/              # 训练产物（不进 Git）
├── miniprogram/           # UniApp 微信小程序（Vue3 + TS）
└── docs文档/              # 需求与设计文档
```

---

## 现有接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查（数据库 / 模型 / 采集状态） |
| GET | `/api/v1/sources` | 点位列表 |
| GET | `/api/v1/stats` | 通行统计（佩戴率 / 覆盖率） |
| GET | `/api/v1/events` | 事件列表（分页 + 过滤） |
| POST | `/api/v1/events/{event_id}/review` | 人工复核（幂等，冲突返回 409） |
| GET | `/api/v1/alerts` | 提醒记录 |
| GET | `/api/v1/self-check/status` | 自查模型预检 |
| POST | `/api/v1/self-check` | 拍照自查（单并发，忙时 429） |

---

## 数据集

**数据集完好，无需恢复。** 当前状态：

| 数据集 | train | valid | test | 类别 |
|---|---|---|---|---|
| `ebike_helmet_v2` | 1930 | 467 | 289 | Cyclists / helmet / no helmet |
| `roboflow_motorcycle` | 1110 | 105 | 53 | 单类 |

原始 zip 位于工作区 `数据集/` 目录（已解压的版本位于 `helmet-guard/dataset/`）。

> `dataset/` 与 `数据集/` 均已加入 `.gitignore`——数据集体量大（GB 级），
> 且 `*.cache` 仅为 YOLO 训练时生成的标签缓存索引，与原始标签并存。

### 模型

YOLOv8n，20 epoch，CPU 训练，`imgsz=480`，`batch=4`：

| 指标 | 值 |
|---|---|
| mAP50 | 0.457 |
| recall | 0.425 |
| precision | 0.696 |

权重位于 `runs/detect/helmet-v2-baseline/weights/best.pt`（不进 Git，可由数据集复现）。

**模型质量是当前最大风险**：recall 0.425 意味着约 57% 的未戴盔目标会被漏检，
不足以支撑「自动处罚」类业务。P5 阶段需通过数据增强、类别平衡与更长训练提升。

---

## 开发规范

### 质量门禁（提交前必须全绿）

```powershell
.\.venv\Scripts\python.exe -m ruff check .          # lint
.\.venv\Scripts\python.exe -m ruff format --check . # 格式
.\.venv\Scripts\python.exe -m mypy app             # 严格类型
.\.venv\Scripts\python.exe -m pytest --cov=app     # 测试 + 覆盖率
```

### 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `HELMET_GUARD_MODE` | `demo` | `demo` / `live`，决定数据库文件与行为 |
| `HELMET_GUARD_DB` | 按模式推导 | 显式指定 SQLite 路径（测试隔离用） |
| `HELMET_GUARD_WEIGHTS` | `weights/helmet_best.pt` | 采集进程权重路径 |
| `HELMET_GUARD_SELFCHECK_WEIGHTS` | 按候选顺序查找 | 自查权重路径 |
| `HELMET_GUARD_ALERTS_ENABLED` | `0` | `1` 开启现场提醒（默认静默） |
| `HELMET_GUARD_HEARTBEAT_EXPIRE` | `30` | 心跳过期秒数 |

### 已知环境约束

- `%TEMP%\pytest-of-<user>` 目录在本机 ACL 异常，导致 pytest 默认 `tmp_path` 无法建目录。
  `tests/conftest.py` 的 `pytest_configure` 会设置 `PYTEST_DEBUG_TEMPROOT` 指向项目内
  `.pytest_tmp/` 予以规避，**无需手动处理**。
- `app/selfcheck.py` 的模型 pin（`_MODEL_CACHE`）是进程级全局单例，测试间会互相污染。
  `tests/conftest.py` 的 autouse 夹具已在每个测试前后重置该状态。

---

## 后续阶段

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | 工程基线：Git、依赖管理、类型检查、测试基线 | ✅ |
| P1 | 领域层 + 仓储层 + Alembic 迁移 + 业务表扩充 | 未开始 |
| P2 | 认证鉴权（JWT + RBAC） | 未开始 |
| P3 | 管理后台 `admin-web/`（Vue3） | 未开始 |
| P4 | 异步任务与对象存储 | 未开始 |
| P5 | 模型质量提升 + 数据集泄漏排查 | 未开始 |
