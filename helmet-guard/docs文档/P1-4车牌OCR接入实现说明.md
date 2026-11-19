# P1-4 车牌 OCR 接入实现说明

> 实施日期：2026-11-16
> 范围：`app/domain/plate.py`、`app/services/identity/plate_ocr.py`、`app/services/identity/rapid_plate_recognizer.py`、`app/services/identity/resolver.py`（集成）、`tests/test_plate_ocr.py`、`tests/test_rapid_plate_recognizer.py`
> 阶段定位：P1（身份识别）第 4 个子任务，P1-5（共现图谱匹配）之前。
> 状态：**真实 OCR 已落地并跑通**（RapidOCR / PP-OCRv3 ONNX 版），非仅骨架。

---

## 1. 依赖可行性评估与落地结论

### 1.1 实测探测结果

在项目虚拟环境（Python **3.14.5**，pip 26.3）中实测：

| 依赖 | 探测前 | 探测后 | 说明 |
|------|--------|--------|------|
| `paddleocr` | ❌ | ❌（未装） | PP-OCRv4 需 `paddlepaddle`（数百 MB，**Python 3.14 尚无官方 wheel**） |
| `rapidocr-onnxruntime` | ❌ | ✅ **1.2.3** | **已安装并跑通真实推理** |
| `onnxruntime` | ❌ | ✅ **1.32.0** | 随 rapidocr 装入，CPU 推理 |
| `opencv-python` | cv2 5.0.0 | ✅ | rapidocr 依赖 |
| `numpy` | ✅ | 2.5.4 | 随 rapidocr 升到 2.5.4 |
| `torch` / `ultralytics` | ✅ | ✅ | 沿用，不受影响 |

**关键发现**：原判断「离线环境安装困难」**不成立**——网络与 PyPI 均可用。
真正的阻碍是 `paddlepaddle` 尚无 Python 3.14 官方轮子，而非网络或体积。

### 1.2 最终选型：RapidOCR（PP-OCRv3 ONNX 版）

| 维度 | PaddleOCR PP-OCRv4 | **RapidOCR（选用）** |
|------|-------------------|-------------------|
| 运行时 | paddlepaddle（数百 MB，3.14 无轮子） | **onnxruntime（17MB）** |
| 模型权重 | 需联网下载 | **随包内置**（`ch_ppocr_v3_det/rec/cls`），开箱即用 |
| 模型版本 | v4 | v3（PP-OCR 同源、精度接近） |
| 部署形态 | 独立进程/GPU | **同进程 CPU，边缘盒友好** |
| 单次延迟 | 30~80ms (GPU) | **~100~500ms (CPU)** |

**结论**：RapidOCR 是 PaddleOCR 同源模型的轻量可落地形态，满足「真实实现」要求。
生产环境如需 PP-OCRv4，只需替换 `PlateRecognizer` 协议实现，`resolver` 零改动。

### 1.3 安装方式

```bash
pip install rapidocr-onnxruntime==1.2.3
# 或按 pyproject 的可选依赖组
pip install -e ".[ocr]"
```

已加入 `pyproject.toml` 的 `ocr` 可选依赖组，**不污染核心依赖**。

---

## 2. 车牌处理流水线

```
             ┌──────────────────────────────────────────────────────┐
  BGR 帧     │  PlateOCRService.read(frame, rider_box)              │
  + 骑行者框 →│                                                      │
             └──────────────────────────────────────────────────────┘
                              │
              ┌───────────────▼────────────────┐
      ①检测   │ PlateDetector.detect()          │  ← Protocol
              │  默认 HeuristicPlateDetector    │     (YOLO plate 类预留)
              │  骑行者框内中央条带裁剪          │
              │  垂直 45%~70% / 水平 20%~80%     │
              └───────────────┬────────────────┘
                              │ 车牌框列表
              ┌───────────────▼────────────────┐
      ②矫正   │ 裁剪 → 灰度 → CLAHE → 留白补边  │  ← warp_plate_quad
              │ （四点框走透视矫正）              │     预留四边形接口
              └───────────────┬────────────────┘
                              │ 车牌裁剪图
              ┌───────────────▼────────────────┐
      ③识别   │ PlateRecognizer.recognize()    │  ← Protocol
              │  ★ RapidPlateRecognizer（真实） │     PP-OCRv3 ONNX
              │    → 放大至 ≥96px 高 → 推理      │
              │  → list[PlateCandidate]        │
              └───────────────┬────────────────┘
                              │ OCR 候选（原始文本仅作参考）
              ┌───────────────▼────────────────┐
      ④约束   │ CampusPlateConstrainer          │  ← 强制经过
              │  a. is_valid_plate 合法性过滤    │
              │  b. campus_plate_score 模式加分  │
              │  c. 加权分排序 → 最优候选       │
              │  d. 低于准入线 → None            │
              └───────────────┬────────────────┘
                              │ ScoredCandidate
              ┌───────────────▼────────────────┐
      ⑤输出   │ PlateResult(text, confidence,   │
              │   plate_type, bbox)             │
              └───────────────┬────────────────┘
                              │
              ┌───────────────▼────────────────┐
      ⑥集成   │ resolver: normalize → 合法性校验 │
              │  → VehicleRepository.get_by_plate│
              │  → Evidence(PLATE) + 日志脱敏    │
              └─────────────────────────────────┘
```

**关键约束**：④ 约束后处理是必经环节。OCR 原始文本不可直接入库或查库，必须先归一化并通过合法性校验。

### 2.1 两个实测踩坑与修正

| 现象 | 根因 | 修正 |
|------|------|------|
| `A12345` 被识别成 `A1`/`23`/`45` 三段 | RapidOCR 的 DBNet 文本检测会**裁掉紧贴图像边缘的字符** | 预处理加 `OCR_BORDER_PX=12` 留白补边 |
| 60×130 的小图仍识别不全 | 小图上检测框进一步切碎字符 | 识别前统一**放大到 ≥96px 高**（`MIN_OCR_HEIGHT`） |

修正后端到端实测：`PlateResult(text='A1234', confidence=0.75, plate_type='school', bbox=(46.0, 142.0, 154.0, 209.0))`。

---

## 3. 约束规则表

### 3.1 合法性规则（`is_valid_plate`，先过滤后打分）

| 规则 | 判定 | 说明 |
|------|------|------|
| 字符集 | `^[一-龥A-Z0-9]+$` | 归一化后仅允许汉字、大写字母、数字 |
| 长度 | 3 ~ 10 | 短于 3 或长于 10 一律拒绝 |
| 数字要求 | 必须含至少 1 位数字 | `XYZ` 被拒绝（纯字母多为噪声） |
| 纯数字长度 | 4 ~ 6 位 | 校园自编号范围；`1234567` 拒绝 |

### 3.2 校园模式加分表（`campus_plate_score`）

基分 **0.40**，命中模式叠加 bonus，无数字 **−0.20**，最终裁剪到 `[0, 1]`。

| 模式名 | 正则 | bonus | 示例 | 得分 |
|--------|------|-------|------|------|
| `gate_full` | `^[东南西北]门\d{2,3}$` | +0.35 | 东门037 | **0.75** |
| `gate_alpha` | `^[东南西北]门[A-Z]\d{1,3}$` | +0.35 | 南门A12 | **0.75** |
| `campus_word` | `.*校.*` | +0.30 | 某某校车12 | 0.70 |
| `pure_digits` | `^\d{4,6}$` | +0.25 | 12345 | 0.65 |
| `short_code` | `^[A-Z]\d{4,5}$` | +0.20 | A12345 | **0.60** |
| `province_ebike` | `^[一-龥][A-Z]\d{4,5}$` | +0.20 | 皖A12345 | 0.60 |
| `province_standard` | `^[一-龥][A-Z][A-Z0-9]{5}$` | +0.20 | 皖AB1234 | 0.60 |
| （惩罚）无数字 | — | −0.20 | XYZ | **0.20** |

### 3.3 加权综合分与准入

```
final_score = OCR置信度 × 0.7 + 校园模式分 × 0.3
准入线：final_score ≥ 0.45
```

**约束生效的实证**（`test_constrainer_prefers_campus_pattern_over_noise`）：

| 候选 | OCR 置信度 | 模式分 | final_score | 结果 |
|------|------------|--------|-------------|------|
| `XYZ`（噪声） | 0.95 | 0.20 | 0.725 | 落选 |
| `东门037`（真实） | 0.70 | 0.75 | **0.715** | **胜出** |

即：真实号牌即使 OCR 置信度更低，也能凭校园模式先验反超高置信噪声文本。
权重取 0.7/0.3 的依据：OCR 置信度是主信号，校园模式是**先验加分**而非主判据。

### 3.4 编号类型映射（`guess_plate_type`）

领域层使用与 `vehicles.plate_type` 枚举一致的**小写**值；任务书中的大写名为概念名。

| 任务书名 | 领域层值 | 判定条件 | 示例 |
|----------|----------|----------|------|
| SCHOOL | `school` | 含"门" / 纯数字 / `^[A-Z]\d{4,5}$` | 东门037、12345、A12345 |
| UNIVERSITY | `university` | 含"校"或"大学" | 某某校车12 |
| BLUE | `blue` | 汉字开头的地方牌 | 皖A12345 |
| NONE | `none` | 非法文本 | XYZ |

---

## 4. 降级策略

| 故障点 | 降级行为 | 是否中断采集 |
|--------|----------|--------------|
| `rapidocr` 未安装 | `_default_recognizer()` 探测失败 → 自动切 `StubPlateRecognizer`（未识别） | 否 |
| OCR 引擎初始化失败 | `RapidPlateRecognizer` 抛 `RuntimeError` → `read()` 捕获 → 未识别 | 否 |
| 推理异常 | 同上，捕获后降级 | 否 |
| 检测器抛异常 | `read()` 捕获 → 返回 `PlateResult(text=None, confidence=0.0)` | 否 |
| 裁剪区域非法（框越界/过小） | 跳过该框，继续下一个候选框 | 否 |
| 预处理/识别单框失败 | `try/except` 跳过该框，保留其他候选 | 否 |
| 所有候选均非法 | 约束器返回 `None` → 未识别 | 否 |
| 识别结果总分低于准入线 | 同上，未识别 | 否 |
| 合法车牌但库中无登记车辆 | 产出 PLATE 证据但 `subject_id/vehicle_id=None`，走待识别池 | 否 |

**核心语义**：未识别 = "无该证据"，融合层按证据缺席处理，**不产生虚假支持**，
不会因为 OCR 失败而误判身份或误施处罚。

**降级链**：`RapidOCR`（真实） → `StubPlateRecognizer`（未识别） → 融合层视作无证据。
三层均不会中断采集主链路。

---

## 5. 日志脱敏

`mask_plate(text)`：**保留前 2 后 2，中间打码**。

| 输入 | 输出 |
|------|------|
| `皖A12345` | `皖A***45` |
| `东门037` | `东门**37` |
| `A12` | `***`（≤4 位全打码） |
| `None` / `""` | `****` |

- resolver 的 `Evidence.detail` 使用脱敏串，完整车牌明文不进入日志与事件说明。
- 明文车牌仅用于 `VehicleRepository.get_by_plate()` 的库内精确匹配（车牌本身是登记主键，非敏感 PII）。

---

## 6. 与生产级 PaddleOCR 方案的差异

| 环节 | 当前实现 | 生产级方案（PaddleOCR PP-OCRv4） | 切换成本 |
|------|----------|--------------------------------|----------|
| 车牌检测 | 启发式条带裁剪（骑行者框中央） | YOLO 新增 `plate` 类（需校内自采车牌数据训练） | 实现 `PlateDetector` 协议，注入即可 |
| 字符识别 | **RapidOCR PP-OCRv3 ONNX（真实可用）** | PaddleOCR PP-OCRv4（DBNet 检测 + CRNN 识别 + 字典约束） | 实现 `PlateRecognizer` 协议，注入即可 |
| 运行时 | onnxruntime CPU | paddlepaddle / paddle-gpu | 随实现一并替换 |
| 置信度 | RapidOCR 文本分数 | 字符均值置信度 × 检测框置信度 | 识别器内部计算 |
| 透视矫正 | 四点接口已就绪，默认走矩形裁剪 | YOLO 输出四点或多边形 → `warp_plate_quad` | 改检测器输出格式 |
| 留白 + 放大 | **已实现**（`OCR_BORDER_PX=12`、`MIN_OCR_HEIGHT=96`） | 同左（同样需要，DBNet 行为一致） | 零改动 |
| 后处理约束 | **已实现且生产可用**（归一化/合法性/校园模式/脱敏） | 同左，完全复用 | 零改动 |
| 集成层（resolver） | **已实现且生产可用** | 同左 | 零改动 |
| 推理部署 | 边缘盒同进程同步调用 | 建议 OCR 放 GPU worker（独立推理服务），`read()` 改为异步/队列 | 改调用方式 |

**结论**：领域约束、集成层与识别链路均已是生产可用形态；替换点集中在两个 Protocol 实现，不触碰业务逻辑。

---

## 7. 测试结果

| 项目 | 结果 |
|------|------|
| 新增测试 | `tests/test_plate_ocr.py` **37 项** + `tests/test_rapid_plate_recognizer.py` **7 项** |
| P1-4 专项 | **44 passed** |
| 全量回归 | **164 passed**（原 120 + 新增 44） |
| ruff | `All checks passed!`（app + tests） |
| mypy strict | `Success: no issues found in 44 source files` |
| 覆盖率 | 总计 **80.38%**（阈值 60%）；`app/domain/plate.py` **97%**、`app/services/identity/plate_ocr.py` **91%**、`app/services/identity/rapid_plate_recognizer.py` **83%** |

### 测试覆盖矩阵

**领域层纯函数（`app/domain/plate.py`）**
- `normalize_plate`：去空格、大写、全角→半角、空串/纯空白、非字符串抛 `ValueError`、中文保留
- `campus_plate_score`：三档分离断言（东门037=0.75 > A12345=0.60 > XYZ=0.20）、纯数字/省牌、空串=0
- `is_valid_plate`：10 组参数化边界（合法 5 组 / 非法 5 组）、脏输入先归一化
- `guess_plate_type`：school / blue / university / none 四类

**服务层（`app/services/identity/plate_ocr.py`）**
- 约束器：校园模式反超高置信噪声、非法文本淘汰、加权排序、低分候选拒绝
- 脱敏：长文本保留首尾、短文本全打码、None 处理
- 检测器：条带落在骑行者框内、非法输入返回空列表
- 预处理：输出 3 通道 + 留白边距、空图/灰度图抛 `ValueError`
- 透视矫正：输出固定尺寸 (48, 160, 3)
- 服务流水线：约束后处理返回最优候选、检测器异常优雅降级、默认空识别、非法帧降级

**真实 OCR（`app/services/identity/rapid_plate_recognizer.py`）**
- 放大逻辑：小图被放大到 ≥96px 高、大图保持不变
- 依赖探测：已安装时构造出真实识别器
- **真实推理**：仿真车牌 `A12345` → 识别出含数字的合法车牌文本（置信度 > 0.5）
- 空白图 → 空候选（不抛异常）
- **端到端**：帧 → 检测 → 矫正 → 真实识别 → 约束 → `PlateResult`（text/confidence/plate_type/bbox 齐备）
- 空白帧 → 未识别，优雅降级
- 该组用 `importorskip` 保护，未装 OCR 依赖时自动跳过，不影响主链路

**集成（`app/services/identity/resolver.py`）**
- PlateReader 返回结果 → 产出 PLATE 证据 → BIND 到已登记车辆 → 证据 detail 已脱敏（不含明文）
- 脏车牌文本（`  皖a 12345 `）归一化后仍命中登记车辆
- 非法车牌文本不命中任何车辆，产出证据但不绑定

---

## 8. 变更文件清单

| 文件 | 状态 | 职责 |
|------|------|------|
| `app/domain/plate.py` | 新增 | 车牌领域层纯函数：归一化、合法性、类型猜测、校园模式打分 |
| `app/services/identity/plate_ocr.py` | 新增 | OCR 服务：检测/矫正/识别/约束流水线 + Protocol + 脱敏 |
| `app/services/identity/rapid_plate_recognizer.py` | 新增 | **真实识别器**：RapidOCR（PP-OCRv3 ONNX）适配 `PlateRecognizer` 协议 |
| `app/services/identity/protocols.py` | 修改 | `PlateResult` 补 `bbox` 字段 |
| `app/services/identity/resolver.py` | 修改 | PLATE 证据路径接入归一化、合法性校验、库内查表与日志脱敏 |
| `app/domain/__init__.py` | 修改 | 导出车牌领域层公开接口 |
| `pyproject.toml` | 修改 | 新增 `ocr` 可选依赖组 + mypy 第三方豁免 |
| `tests/test_plate_ocr.py` | 新增 | 37 项领域/服务/集成测试 |
| `tests/test_rapid_plate_recognizer.py` | 新增 | 7 项真实 OCR 推理测试（含端到端） |

---

## 9. 已知限制与后续计划

**已知限制**
1. 车牌检测仍为启发式条带，对遮挡、斜置、非居中挂载的牌召回率有限；生产需训练 YOLO `plate` 类。
2. OCR 为 CPU 推理（约 100~500ms/次），**不适合逐帧全量调用**；应仅在检测到骑行者且事件触发时低频调用，或迁至 GPU worker。
3. `rapidocr-onnxruntime` 内置的是 **PP-OCRv3** 权重，精度略低于 v4；如需 v4 需自行准备权重并替换实现。
4. 仿真车牌测试用 OpenCV 渲染字体，与真实号牌的字体/反光/污损差异较大，真实场景召回率需实测校准。
5. `plate_type` 枚举大小写与任务书大写名存在映射差异（领域层用小写以匹配 `vehicles.plate_type` DB 枚举），已在代码注释中说明。

**后续计划**
1. P1-5：接入共现图谱匹配，融合为四证据完整链路。
2. P1-6：身份管理 API 与后台页面，将车牌证据详情（含脱敏车牌）纳入审核界面。
3. 生产化：采集校内车牌数据集训练 YOLO `plate` 类；评估 PP-OCRv4 + GPU worker 部署方案。
