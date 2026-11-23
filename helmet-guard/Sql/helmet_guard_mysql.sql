-- ============================================================
-- 校园头盔检测提醒助手 · MySQL 8.0 全库建表脚本
-- 适用：小皮 phpStudy（MySQL 8.0.12）+ Navicat Premium Lite 17
-- 用法（Navicat）：连接本地 MySQL → 右键“运行 SQL 文件”选本文件
--        或 新建查询 → 粘贴执行。执行后得到空库 + 基线种子。
-- 约定：
--   * 库名 helmet_guard，字符集 utf8mb4（支持中文/emoji 学号姓名）
--   * 引擎 InnoDB；时间统一 DATETIME（MySQL 不存时区，应用层按 UTC ISO 处理）
--   * 与 Alembic head（0010_org_units）结构对齐，含 alembic_version 标记
--   * 种子：model_versions 基线行 + org_units 演示树（不含超管口令，见下）
-- 超管账号：库建好后回后端执行 `python -m app.seed_demo`（走 DATABASE_URL）
--   自动写入 u_admin（口令取环境变量 HELMET_GUARD_SEED_ADMIN_PASSWORD，
--   缺省 Admin-2026，bcrypt 哈希入库，明文绝不进 SQL）。
-- ============================================================

CREATE DATABASE IF NOT EXISTS `helmet_guard`
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `helmet_guard`;

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ---------------- 采集域（遗留原生 SQL 6 表） ----------------

CREATE TABLE IF NOT EXISTS `sources` (
  `source_id` VARCHAR(64) NOT NULL,
  `name` VARCHAR(128) NOT NULL,
  `status` VARCHAR(32) NOT NULL DEFAULT 'online',
  `last_seen` VARCHAR(32) NULL,
  `updated_at` VARCHAR(32) NOT NULL,
  PRIMARY KEY (`source_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `passes` (
  `pass_id` VARCHAR(64) NOT NULL,
  `source_id` VARCHAR(64) NOT NULL,
  `run_id` VARCHAR(64) NOT NULL,
  `occurred_at` VARCHAR(32) NOT NULL,
  `rider_status` VARCHAR(16) NOT NULL,
  `model_raw` VARCHAR(64) NOT NULL DEFAULT '',
  `boxes` TEXT NULL,
  `image_width` INT NULL,
  `image_height` INT NULL,
  `created_at` VARCHAR(32) NOT NULL,
  PRIMARY KEY (`pass_id`),
  UNIQUE KEY `uq_passes_source_run_pass` (`source_id`, `run_id`, `pass_id`),
  CONSTRAINT `ck_passes_rider_status` CHECK (`rider_status` IN ('helmeted','bare','unknown'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `events` (
  `event_id` VARCHAR(64) NOT NULL,
  `pass_id` VARCHAR(64) NOT NULL,
  `source_id` VARCHAR(64) NOT NULL,
  `run_id` VARCHAR(64) NOT NULL,
  `occurred_at` VARCHAR(32) NOT NULL,
  `status` VARCHAR(16) NOT NULL DEFAULT 'pending',
  `model_label` VARCHAR(64) NOT NULL DEFAULT '',
  `reason` VARCHAR(500) NOT NULL DEFAULT '',
  `reviewer` VARCHAR(64) NOT NULL DEFAULT '',
  `reviewed_at` VARCHAR(32) NULL,
  `created_at` VARCHAR(32) NOT NULL,
  PRIMARY KEY (`event_id`),
  UNIQUE KEY `uq_events_pass_id` (`pass_id`),
  CONSTRAINT `ck_events_status` CHECK (`status` IN ('pending','confirmed','dismissed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `reviews` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `event_id` VARCHAR(64) NOT NULL,
  `decision` VARCHAR(16) NOT NULL,
  `reason` VARCHAR(500) NOT NULL DEFAULT '',
  `operator` VARCHAR(64) NOT NULL DEFAULT '',
  `created_at` VARCHAR(32) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_reviews_event` (`event_id`),
  CONSTRAINT `ck_reviews_decision` CHECK (`decision` IN ('confirmed','dismissed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `heartbeats` (
  `source_id` VARCHAR(64) NOT NULL,
  `run_id` VARCHAR(64) NOT NULL DEFAULT '',
  `mode` VARCHAR(32) NOT NULL DEFAULT '',
  `updated_at` VARCHAR(32) NOT NULL,
  `detail` VARCHAR(1024) NOT NULL DEFAULT '',
  PRIMARY KEY (`source_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `alerts` (
  `alert_id` VARCHAR(64) NOT NULL,
  `event_id` VARCHAR(64) NOT NULL,
  `source_id` VARCHAR(64) NOT NULL,
  `status` VARCHAR(16) NOT NULL DEFAULT 'queued',
  `note` VARCHAR(500) NOT NULL DEFAULT '',
  `created_at` VARCHAR(32) NOT NULL,
  `updated_at` VARCHAR(32) NOT NULL,
  PRIMARY KEY (`alert_id`),
  UNIQUE KEY `uq_alerts_event_id` (`event_id`),
  CONSTRAINT `ck_alerts_status` CHECK (`status` IN ('queued','played','expired','silent'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- 身份域 ----------------

CREATE TABLE IF NOT EXISTS `users` (
  `user_id` VARCHAR(64) NOT NULL,
  `openid` VARCHAR(64) NULL,
  `unionid` VARCHAR(64) NULL,
  `wechat_session_key` VARCHAR(255) NULL COMMENT 'jscode2session 返回的 session_key，每次 wx.login 顶替旧值',
  `username` VARCHAR(64) NULL,
  `password_hash` VARCHAR(255) NULL,
  `phone` VARCHAR(20) NULL,
  `role` ENUM('student','counselor','security_officer','league_officer','super_admin','auditor','admin','reviewer','observer') NOT NULL DEFAULT 'student',
  `status` ENUM('active','disabled') NOT NULL DEFAULT 'active',
  `last_login_at` DATETIME NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`),
  UNIQUE KEY `uq_users_openid` (`openid`),
  KEY `ix_users_phone` (`phone`),
  KEY `ix_users_role` (`role`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `students` (
  `student_id` VARCHAR(64) NOT NULL,
  `user_id` VARCHAR(64) NULL,
  `name` VARCHAR(64) NOT NULL,
  `gender` VARCHAR(16) NULL,
  `school` VARCHAR(64) NULL,
  `college` VARCHAR(64) NULL,
  `major` VARCHAR(64) NULL,
  `class_name` VARCHAR(64) NULL,
  `grade` VARCHAR(32) NULL,
  `dorm_id` VARCHAR(64) NULL,
  `phone` VARCHAR(20) NULL,
  `avatar` VARCHAR(255) NULL,
  `status` ENUM('active','graduated','suspended') NOT NULL DEFAULT 'active',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`student_id`),
  UNIQUE KEY `uq_students_user_id` (`user_id`),
  KEY `ix_students_class` (`class_name`),
  CONSTRAINT `fk_students_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `vehicles` (
  `vehicle_id` VARCHAR(64) NOT NULL,
  `plate_no` VARCHAR(32) NULL,
  `plate_type` ENUM('blue','school','university','none') NULL,
  `owner_id` VARCHAR(64) NULL,
  `owner_bind_type` ENUM('registered','qr','nfc','appearance','cooccur','manual') NULL,
  `confidence` FLOAT NOT NULL DEFAULT 0,
  `color_hist` JSON NULL,
  `embedding` BLOB NULL,
  `first_seen` DATETIME NULL,
  `last_seen` DATETIME NULL,
  `status` ENUM('active','unbound','blocked') NOT NULL DEFAULT 'active',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`vehicle_id`),
  UNIQUE KEY `uq_vehicles_plate_no` (`plate_no`),
  KEY `ix_vehicles_owner` (`owner_id`),
  KEY `ix_vehicles_plate` (`plate_no`),
  CONSTRAINT `fk_vehicles_owner` FOREIGN KEY (`owner_id`) REFERENCES `students` (`student_id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `identity_resolutions` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `event_id` VARCHAR(64) NOT NULL,
  `vehicle_id` VARCHAR(64) NULL,
  `subject_id` VARCHAR(64) NULL,
  `method` ENUM('plate','qr','nfc','appearance','cooccur','manual','none') NULL,
  `confidence` FLOAT NOT NULL,
  `plate_conf` FLOAT NOT NULL DEFAULT 0,
  `appearance_conf` FLOAT NOT NULL DEFAULT 0,
  `cooccur_conf` FLOAT NOT NULL DEFAULT 0,
  `matched_count` INT NOT NULL DEFAULT 0,
  `snapshot_id` VARCHAR(255) NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_identity_event` (`event_id`),
  KEY `ix_identity_subject` (`subject_id`),
  KEY `ix_identity_vehicle` (`vehicle_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `pending_identities` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `vehicle_id` VARCHAR(64) NOT NULL,
  `pass_count` INT NOT NULL DEFAULT 1,
  `first_seen` DATETIME NULL,
  `last_seen` DATETIME NULL,
  `location` VARCHAR(128) NULL,
  `snapshot_id` VARCHAR(255) NULL,
  `status` ENUM('pending','resolved','ignored') NOT NULL DEFAULT 'pending',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_pending_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `vehicle_cooccurrence` (
  `vehicle_a` VARCHAR(64) NOT NULL,
  `vehicle_b` VARCHAR(64) NOT NULL,
  `window_count` INT NOT NULL,
  `jaccard` FLOAT NOT NULL,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`vehicle_a`, `vehicle_b`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `audit_logs` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `actor` VARCHAR(64) NOT NULL,
  `role` VARCHAR(32) NOT NULL,
  `action` VARCHAR(128) NOT NULL,
  `object_type` VARCHAR(64) NULL,
  `object_id` VARCHAR(128) NULL,
  `ip` VARCHAR(64) NULL,
  `result` VARCHAR(16) NOT NULL DEFAULT 'ok',
  `detail` VARCHAR(1024) NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_audit_actor` (`actor`),
  KEY `ix_audit_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `counselor_assignments` (
  `user_id` VARCHAR(64) NOT NULL,
  `class_name` VARCHAR(64) NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`, `class_name`),
  KEY `ix_counselor_user` (`user_id`),
  CONSTRAINT `fk_counselor_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `org_units` (
  `unit_id` VARCHAR(64) NOT NULL,
  `unit_type` ENUM('school','college','grade','major','class') NOT NULL,
  `name` VARCHAR(128) NOT NULL,
  `parent_id` VARCHAR(64) NULL,
  `sort_order` INT NOT NULL DEFAULT 0,
  `status` VARCHAR(16) NOT NULL DEFAULT 'active',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`unit_id`),
  KEY `ix_org_parent` (`parent_id`),
  KEY `ix_org_type` (`unit_type`),
  CONSTRAINT `fk_org_parent` FOREIGN KEY (`parent_id`) REFERENCES `org_units` (`unit_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- 积分域 ----------------

CREATE TABLE IF NOT EXISTS `score_accounts` (
  `student_id` VARCHAR(64) NOT NULL,
  `balance` INT NOT NULL DEFAULT 100,
  `total_deducted` INT NOT NULL DEFAULT 0,
  `total_awarded` INT NOT NULL DEFAULT 0,
  `level` ENUM('S','A','B','C','D') NOT NULL DEFAULT 'B',
  `streak_days` INT NOT NULL DEFAULT 0,
  `compliance_rate` FLOAT NOT NULL DEFAULT 1.0,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`student_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `score_ledger` (
  `ledger_id` INT NOT NULL AUTO_INCREMENT,
  `student_id` VARCHAR(64) NOT NULL,
  `change` INT NOT NULL,
  `balance_after` INT NOT NULL,
  `reason_code` VARCHAR(64) NOT NULL,
  `reason_text` VARCHAR(500) NULL,
  `event_id` VARCHAR(64) NULL,
  `decision_id` VARCHAR(64) NULL,
  `operator` VARCHAR(64) NULL,
  `effective_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`ledger_id`),
  KEY `ix_ledger_student` (`student_id`),
  KEY `ix_ledger_time` (`effective_at`),
  KEY `ix_ledger_event` (`event_id`),
  CONSTRAINT `fk_ledger_student` FOREIGN KEY (`student_id`) REFERENCES `students` (`student_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `score_rules` (
  `rule_id` VARCHAR(64) NOT NULL,
  `rule_type` ENUM('deduct','award','streak') NOT NULL DEFAULT 'deduct',
  `name` VARCHAR(128) NOT NULL,
  `condition_json` JSON NOT NULL,
  `score_change` INT NOT NULL,
  `priority` INT NOT NULL DEFAULT 0,
  `enabled` TINYINT(1) NOT NULL DEFAULT 1,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`rule_id`),
  KEY `ix_rule_enabled` (`enabled`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- 决策审批与申诉 ----------------

CREATE TABLE IF NOT EXISTS `decisions` (
  `decision_id` VARCHAR(64) NOT NULL,
  `event_id` VARCHAR(64) NOT NULL,
  `student_id` VARCHAR(64) NULL,
  `level` ENUM('L0','L1','L2','L3','L4') NOT NULL,
  `action` ENUM('none','remind','deduct_score','notify','report','award') NOT NULL,
  `score_delta` INT NOT NULL DEFAULT 0,
  `reason_code` VARCHAR(64) NOT NULL,
  `message` VARCHAR(500) NULL,
  `confidence` FLOAT NULL,
  `factors` JSON NULL,
  `evidence_refs` JSON NULL,
  `policy_version` VARCHAR(64) NULL,
  `status` ENUM('PENDING_REVIEW','APPROVED','REJECTED','ADJUSTED','AUTO_APPROVED','APPEALING','APPEAL_UPHELD','APPEAL_REJECTED','EXPIRED') NOT NULL DEFAULT 'PENDING_REVIEW',
  `auto_approved` TINYINT(1) NOT NULL DEFAULT 0,
  `reviewed_by` VARCHAR(64) NULL,
  `reviewed_at` DATETIME NULL,
  `review_note` VARCHAR(500) NULL,
  `original_level` VARCHAR(16) NULL,
  `effective_at` DATETIME NULL,
  `due_at` DATETIME NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`decision_id`),
  KEY `ix_decisions_status` (`status`),
  KEY `ix_decisions_student` (`student_id`),
  KEY `ix_decisions_due` (`due_at`),
  UNIQUE KEY `ix_decisions_event` (`event_id`),
  KEY `ix_decisions_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `review_logs` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `decision_id` VARCHAR(64) NOT NULL,
  `action` ENUM('approve','reject','adjust','auto','batch','expire','escalate','appeal','simulate') NOT NULL,
  `from_status` VARCHAR(32) NULL,
  `to_status` VARCHAR(32) NULL,
  `from_level` VARCHAR(16) NULL,
  `to_level` VARCHAR(16) NULL,
  `note` VARCHAR(500) NULL,
  `operator` VARCHAR(64) NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_review_decision` (`decision_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `appeals` (
  `appeal_id` VARCHAR(64) NOT NULL,
  `decision_id` VARCHAR(64) NOT NULL,
  `student_id` VARCHAR(64) NOT NULL,
  `reason` VARCHAR(500) NOT NULL,
  `attachments` JSON NULL,
  `status` ENUM('pending','submitted','processing','upheld','rejected') NOT NULL DEFAULT 'pending',
  `handler` VARCHAR(64) NULL,
  `handle_note` VARCHAR(500) NULL,
  `resolved_at` DATETIME NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`appeal_id`),
  KEY `ix_appeals_student` (`student_id`),
  KEY `ix_appeals_status` (`status`),
  KEY `ix_appeals_decision` (`decision_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `feedback_samples` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `event_id` VARCHAR(64) NOT NULL,
  `decision_id` VARCHAR(64) NULL,
  `appeal_id` VARCHAR(64) NULL,
  `snapshot_id` VARCHAR(255) NULL,
  `image_path` VARCHAR(255) NULL,
  `label` VARCHAR(64) NULL,
  `model_pred` VARCHAR(64) NULL,
  `original_label` VARCHAR(64) NULL,
  `corrected_label` VARCHAR(64) NULL,
  `reason` VARCHAR(500) NULL,
  `source` ENUM('review_reject','appeal_upheld','manual') NOT NULL,
  `used_for_train` TINYINT(1) NOT NULL DEFAULT 0,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_feedback_train` (`used_for_train`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- 模型与点位 ----------------

CREATE TABLE IF NOT EXISTS `model_versions` (
  `model_id` VARCHAR(64) NOT NULL,
  `task` VARCHAR(32) NOT NULL,
  `version` VARCHAR(64) NOT NULL,
  `weight_path` VARCHAR(255) NOT NULL,
  `metrics` JSON NULL,
  `dataset_id` VARCHAR(128) NULL,
  `is_active` TINYINT(1) NOT NULL DEFAULT 0,
  `deployed_at` DATETIME NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`model_id`),
  KEY `ix_model_task` (`task`),
  KEY `ix_model_active` (`is_active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `camera_points` (
  `source_id` VARCHAR(64) NOT NULL,
  `roi_x1` FLOAT NOT NULL DEFAULT 0.05,
  `roi_y1` FLOAT NOT NULL DEFAULT 0.2,
  `roi_x2` FLOAT NOT NULL DEFAULT 0.95,
  `roi_y2` FLOAT NOT NULL DEFAULT 0.95,
  `count_line_y` FLOAT NOT NULL DEFAULT 0.6,
  `zone_x1` FLOAT NOT NULL DEFAULT 0.2,
  `zone_y1` FLOAT NOT NULL DEFAULT 0.3,
  `zone_x2` FLOAT NOT NULL DEFAULT 0.8,
  `zone_y2` FLOAT NOT NULL DEFAULT 0.9,
  `updated_by` VARCHAR(64) NULL,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`source_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- Alembic 版本标记 ----------------

CREATE TABLE IF NOT EXISTS `alembic_version` (
  `version_num` VARCHAR(32) NOT NULL,
  PRIMARY KEY (`version_num`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- 基线种子（幂等） ----------------

INSERT IGNORE INTO `model_versions`
  (`model_id`, `task`, `version`, `weight_path`, `metrics`, `dataset_id`, `is_active`, `deployed_at`, `created_at`, `updated_at`)
VALUES
  ('helmet-v2-baseline', 'detect', 'v2-baseline',
   'runs/detect/helmet-v2-baseline/weights/best.pt',
   '{"precision": 0.696, "recall": 0.425, "note": "基线权重，recall偏低需持续回流"}',
   'ebike_helmet_v2+roboflow_motorcycle', 1, NOW(), NOW(), NOW());

INSERT IGNORE INTO `org_units` (`unit_id`, `unit_type`, `name`, `parent_id`, `sort_order`, `status`, `created_at`, `updated_at`) VALUES
  ('org-school-demo', 'school', '示范大学', NULL, 1, 'active', NOW(), NOW()),
  ('org-college-cs', 'college', '计算机学院', 'org-school-demo', 1, 'active', NOW(), NOW()),
  ('org-college-me', 'college', '机械工程学院', 'org-school-demo', 2, 'active', NOW(), NOW()),
  ('org-grade-2024', 'grade', '2024 级', 'org-college-cs', 1, 'active', NOW(), NOW()),
  ('org-grade-2025', 'grade', '2025 级', 'org-college-cs', 2, 'active', NOW(), NOW()),
  ('org-major-se', 'major', '软件工程', 'org-grade-2024', 1, 'active', NOW(), NOW()),
  ('org-major-cst', 'major', '计算机科学与技术', 'org-grade-2024', 2, 'active', NOW(), NOW()),
  ('org-class-2401', 'class', '计科 2401', 'org-major-se', 1, 'active', NOW(), NOW()),
  ('org-class-2402', 'class', '计科 2402', 'org-major-se', 2, 'active', NOW(), NOW());

INSERT IGNORE INTO `alembic_version` (`version_num`) VALUES ('0010_org_units');

SET FOREIGN_KEY_CHECKS = 1;
