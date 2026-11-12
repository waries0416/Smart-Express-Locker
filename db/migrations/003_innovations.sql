-- ============================================================================
-- 创新功能扩展 · 迁移脚本 003
-- ----------------------------------------------------------------------------
-- 覆盖四组创新功能所需的库表变更：
--
--   【创新点 1/2】DeepSeek 智能包装推荐与备包装协同
--     t_pack_recommendation   推荐结果（模型/规则来源、结构化结果、耗时、降级原因）
--     t_pack_recommend_item   推荐里的禁寄/敏感/打包步骤明细（一对一多行）
--     t_pack_material         备包装材料台账（库存/阈值/单位）
--     t_pack_task             快递员"备包装"任务（引用推荐、材料清单快照）
--     t_pack_task_item        任务的材料快照明细（快照，材料改名不影响历史）
--     t_package 新增可空列     pack_recommendation_id（寄件单引用推荐）
--
--   【创新点 3】高德地图找柜与智能选柜
--     t_cabinet 新增可空列     latitude / longitude（WGS84，DECIMAL(9,6)）+ 索引
--
--   【创新点 4】支付宝沙箱 / 模拟支付
--     t_pay_order             统一支付单（金额服务端快照、幂等键、状态机）
--     t_pay_callback_log      支付回调流水（幂等键唯一，重复通知只记日志不入账）
--
-- 幂等与安全：
--   · 全部使用 CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS 语义
--     （MySQL 8.0 无 ADD COLUMN IF NOT EXISTS，故用 information_schema 判断 +
--      预处理语句，见下方 2 处动态 SQL）；
--   · 只新增表和可空列，**不 DROP、不改动任何现有数据**；
--   · 可重复执行。
--
-- 重放：
--   mysql -u root -p < db/migrations/003_innovations.sql
--   或 python scripts/init_db.py --migrate
-- ============================================================================
USE `smart_locker`;

-- ----------------------------------------------------------------------------
-- 1) t_cabinet 增加经纬度（可空，不破坏现有数据）
-- ----------------------------------------------------------------------------
SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_cabinet'
        AND COLUMN_NAME = 'latitude') = 0,
    'ALTER TABLE t_cabinet ADD COLUMN latitude DECIMAL(9,6) NULL COMMENT ''纬度(WGS84，-90~90)，用于附近柜机距离计算'' AFTER location',
    'SELECT ''t_cabinet.latitude already exists'' AS msg'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_cabinet'
        AND COLUMN_NAME = 'longitude') = 0,
    'ALTER TABLE t_cabinet ADD COLUMN longitude DECIMAL(9,6) NULL COMMENT ''经度(WGS84，-180~180)，用于附近柜机距离计算'' AFTER latitude',
    'SELECT ''t_cabinet.longitude already exists'' AS msg'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 经纬度范围 CHECK：MySQL 8 支持，但 ALTER 加 CHECK 不幂等，改用触发器不划算，
-- 故约束放在应用层（backend/location.py 统一校验）+ 下方索引保证查询性能。
SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.STATISTICS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_cabinet'
        AND INDEX_NAME = 'idx_cabinet_coord') = 0,
    'ALTER TABLE t_cabinet ADD INDEX idx_cabinet_coord (latitude, longitude)',
    'SELECT ''idx_cabinet_coord already exists'' AS msg'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ----------------------------------------------------------------------------
-- 2) 包装推荐主表 t_pack_recommendation
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS t_pack_recommendation (
    recommendation_id INT          NOT NULL AUTO_INCREMENT COMMENT '推荐ID(PK)',
    description       VARCHAR(500) NOT NULL                COMMENT '用户物品描述（去空白后的原文）',
    source            VARCHAR(10)  NOT NULL DEFAULT 'rule' COMMENT '结果来源 deepseek/rule',
    degraded          TINYINT      NOT NULL DEFAULT 0      COMMENT '是否降级到本地规则 0/1',
    degraded_reason   VARCHAR(200) NULL                    COMMENT '降级原因（中文，可直接展示）',
    size_type         VARCHAR(10)  NOT NULL DEFAULT 'MEDIUM' COMMENT '建议格口规格 SMALL/MEDIUM/LARGE',
    size_reason       VARCHAR(255) NULL                    COMMENT '规格理由',
    elapsed_ms        INT          NOT NULL DEFAULT 0      COMMENT '服务端耗时(ms)',
    notice            VARCHAR(200) NULL                    COMMENT '免责提示（以快递员/承运商审核为准）',
    created_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '生成时间',
    PRIMARY KEY (recommendation_id),
    KEY idx_rec_created (created_at),
    KEY idx_rec_source (source),
    CONSTRAINT chk_rec_source CHECK (source IN ('deepseek','rule')),
    CONSTRAINT chk_rec_size   CHECK (size_type IN ('SMALL','MEDIUM','LARGE')),
    CONSTRAINT chk_rec_degraded CHECK (degraded IN (0,1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='AI/规则包装推荐结果（创新点 1）';

-- ----------------------------------------------------------------------------
-- 3) 推荐明细 t_pack_recommend_item
--    kind: FORBIDDEN(禁寄) / SENSITIVE(敏感) / STEP(打包步骤) / MATERIAL(材料)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS t_pack_recommend_item (
    item_id           INT          NOT NULL AUTO_INCREMENT COMMENT '明细ID(PK)',
    recommendation_id INT          NOT NULL                COMMENT '所属推荐ID(FK)',
    kind              VARCHAR(12)  NOT NULL                COMMENT '类型 FORBIDDEN/SENSITIVE/STEP/MATERIAL',
    seq               INT          NOT NULL DEFAULT 0      COMMENT '顺序号（STEP 从 1 开始）',
    name              VARCHAR(100) NULL                    COMMENT '名称（禁寄/敏感/材料名；步骤时为标题）',
    detail            VARCHAR(500) NULL                    COMMENT '说明（原因/具体做法）',
    qty               INT          NULL                    COMMENT '数量（MATERIAL 时使用）',
    unit              VARCHAR(20)  NULL                    COMMENT '单位（MATERIAL 时使用）',
    PRIMARY KEY (item_id),
    KEY idx_recitem_rec (recommendation_id, kind, seq),
    CONSTRAINT fk_recitem_rec FOREIGN KEY (recommendation_id)
        REFERENCES t_pack_recommendation (recommendation_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT chk_recitem_kind CHECK (kind IN ('FORBIDDEN','SENSITIVE','STEP','MATERIAL'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='包装推荐明细（禁寄/敏感/步骤/材料）';

-- ----------------------------------------------------------------------------
-- 4) 备包装材料台账 t_pack_material
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS t_pack_material (
    material_id INT          NOT NULL AUTO_INCREMENT COMMENT '材料ID(PK)',
    name        VARCHAR(50)  NOT NULL                COMMENT '材料名（如 气泡膜）',
    spec        VARCHAR(50)  NULL                    COMMENT '规格描述',
    unit        VARCHAR(20)  NOT NULL DEFAULT '件'   COMMENT '计量单位',
    stock       INT          NOT NULL DEFAULT 0      COMMENT '当前库存',
    threshold   INT          NOT NULL DEFAULT 5      COMMENT '低库存阈值（stock<=threshold 时告警）',
    updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (material_id),
    UNIQUE KEY uk_material_name (name),
    CONSTRAINT chk_material_stock CHECK (stock >= 0),
    CONSTRAINT chk_material_threshold CHECK (threshold >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='备包装材料台账（创新点 2）';

-- ----------------------------------------------------------------------------
-- 5) 快递员备包装任务 t_pack_task
--    材料清单以 t_pack_task_item 快照保存，材料台账后续改名/改规格不影响历史任务。
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS t_pack_task (
    task_id              INT          NOT NULL AUTO_INCREMENT COMMENT '任务ID(PK)',
    package_id           INT          NULL                    COMMENT '关联包裹ID(FK，可空：仅咨询未下单)',
    recommendation_id    INT          NULL                    COMMENT '引用推荐ID(FK)',
    assignee_courier_id  INT          NULL                    COMMENT '指派快递员ID(FK)',
    cabinet_id           INT          NULL                    COMMENT '柜体ID(FK)',
    size_type            VARCHAR(10)  NULL                    COMMENT '建议格口规格',
    status               VARCHAR(12)  NOT NULL DEFAULT 'PENDING'
                         COMMENT '状态 PENDING/DONE/CANCELED',
    note                 VARCHAR(200) NULL                    COMMENT '备注',
    created_at           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    done_at              DATETIME     NULL                    COMMENT '完成时间',
    PRIMARY KEY (task_id),
    KEY idx_task_assignee_status (assignee_courier_id, status, created_at),
    KEY idx_task_package (package_id),
    KEY idx_task_status (status, created_at),
    CONSTRAINT fk_task_package FOREIGN KEY (package_id)
        REFERENCES t_package (package_id) ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_task_rec FOREIGN KEY (recommendation_id)
        REFERENCES t_pack_recommendation (recommendation_id) ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT fk_task_courier FOREIGN KEY (assignee_courier_id)
        REFERENCES t_courier (courier_id) ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT fk_task_cabinet FOREIGN KEY (cabinet_id)
        REFERENCES t_cabinet (cabinet_id) ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT chk_task_status CHECK (status IN ('PENDING','DONE','CANCELED')),
    CONSTRAINT chk_task_size CHECK (size_type IS NULL OR size_type IN ('SMALL','MEDIUM','LARGE'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='快递员备包装任务（创新点 2）';

-- ----------------------------------------------------------------------------
-- 6) 备包装任务材料快照 t_pack_task_item
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS t_pack_task_item (
    task_item_id INT          NOT NULL AUTO_INCREMENT COMMENT '明细ID(PK)',
    task_id      INT          NOT NULL                COMMENT '所属任务ID(FK)',
    material_id  INT          NULL                    COMMENT '材料台账ID(FK，可空=台账无此材料)',
    name         VARCHAR(50)  NOT NULL                COMMENT '材料名快照',
    qty          INT          NOT NULL DEFAULT 1      COMMENT '数量',
    unit         VARCHAR(20)  NOT NULL DEFAULT '件'   COMMENT '单位快照',
    PRIMARY KEY (task_item_id),
    KEY idx_taskitem_task (task_id),
    CONSTRAINT fk_taskitem_task FOREIGN KEY (task_id)
        REFERENCES t_pack_task (task_id) ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_taskitem_material FOREIGN KEY (material_id)
        REFERENCES t_pack_material (material_id) ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT chk_taskitem_qty CHECK (qty > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='备包装任务材料快照';

-- ----------------------------------------------------------------------------
-- 7) t_package 增加 pack_recommendation_id（可空，寄件单引用推荐）
-- ----------------------------------------------------------------------------
SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_package'
        AND COLUMN_NAME = 'pack_recommendation_id') = 0,
    'ALTER TABLE t_package ADD COLUMN pack_recommendation_id INT NULL COMMENT ''引用的包装推荐ID(FK，可空)'' AFTER note, ADD INDEX idx_pkg_pack_rec (pack_recommendation_id)',
    'SELECT ''t_package.pack_recommendation_id already exists'' AS msg'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_package'
        AND CONSTRAINT_NAME = 'fk_pkg_pack_rec') = 0,
    'ALTER TABLE t_package ADD CONSTRAINT fk_pkg_pack_rec FOREIGN KEY (pack_recommendation_id) REFERENCES t_pack_recommendation (recommendation_id) ON UPDATE CASCADE ON DELETE SET NULL',
    'SELECT ''fk_pkg_pack_rec already exists'' AS msg'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ----------------------------------------------------------------------------
-- 8) 统一支付单 t_pay_order
--
-- 设计要点（对应验收要求）：
--   · amount 是**服务端快照**：由后端依据 biz_type+biz_id 重新计算后写入，
--     绝不采用浏览器传来的金额；支付成功后也不允许再改。
--   · idempotency_key：业务侧的幂等键（biz_type:biz_id:provider），
--     重复提交同一业务只复用未过期 PENDING 单，不会重复建单。
--   · trade_no：支付宝交易号，与 pay_no 组合唯一，保证重复回调不重复入账。
--   · status 状态机：PENDING → SUCCESS / FAILED / CLOSED
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS t_pay_order (
    pay_id           INT          NOT NULL AUTO_INCREMENT COMMENT '支付单ID(PK)',
    pay_no           VARCHAR(40)  NOT NULL                COMMENT '商户订单号（唯一）',
    biz_type         VARCHAR(15)  NOT NULL                COMMENT '业务类型 OVERTIME(超时费)/SEND(寄件费)',
    biz_id           INT          NOT NULL                COMMENT '业务ID（OVERTIME=package_id，SEND=寄件单package_id）',
    user_id          INT          NULL                    COMMENT '付款用户ID(FK，可空=管理端代建)',
    amount           DECIMAL(10,2) NOT NULL               COMMENT '金额(元)——服务端快照，不接受前端传值',
    provider         VARCHAR(20)  NOT NULL DEFAULT 'mock' COMMENT '渠道 mock/alipay_sandbox',
    provider_label   VARCHAR(20)  NOT NULL DEFAULT '模拟支付' COMMENT '中文展示文案',
    is_mock          TINYINT      NOT NULL DEFAULT 1      COMMENT '是否模拟渠道 0/1',
    status           VARCHAR(12)  NOT NULL DEFAULT 'PENDING'
                     COMMENT '状态 PENDING/SUCCESS/FAILED/CLOSED',
    idempotency_key  VARCHAR(80)  NULL                    COMMENT '业务幂等键（唯一）',
    trade_no         VARCHAR(64)  NULL                    COMMENT '第三方交易号（支付宝 trade_no）',
    fail_reason      VARCHAR(200) NULL                    COMMENT '失败/关闭原因',
    raw_payload      TEXT         NULL                    COMMENT '降级/调试用的原始响应摘要（不含密钥）',
    expire_at        DATETIME     NOT NULL                COMMENT '支付单过期时间',
    paid_at          DATETIME     NULL                    COMMENT '支付成功时间',
    created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (pay_id),
    UNIQUE KEY uk_pay_no (pay_no),
    UNIQUE KEY uk_pay_idem (idempotency_key),
    UNIQUE KEY uk_pay_trade_no (trade_no),
    KEY idx_pay_biz (biz_type, biz_id),
    KEY idx_pay_status (status, created_at),
    KEY idx_pay_user (user_id, created_at),
    KEY idx_pay_provider (provider, created_at),
    CONSTRAINT fk_pay_user FOREIGN KEY (user_id)
        REFERENCES t_user (user_id) ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT chk_pay_status CHECK (status IN ('PENDING','SUCCESS','FAILED','CLOSED')),
    CONSTRAINT chk_pay_biz CHECK (biz_type IN ('OVERTIME','SEND')),
    CONSTRAINT chk_pay_provider CHECK (provider IN ('mock','alipay_sandbox')),
    CONSTRAINT chk_pay_amount CHECK (amount >= 0),
    CONSTRAINT chk_pay_mock CHECK (is_mock IN (0,1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='统一支付单（创新点 4）';

-- ----------------------------------------------------------------------------
-- 9) 支付回调流水 t_pay_callback_log
--
-- idem_key 唯一索引 = 回调幂等键：`{pay_no}:{trade_no}`。
-- 支付宝会重复推送异步通知（间隔递增），必须保证"收到多次只入账一次"：
--   第一次插入成功 → 继续处理入账；重复插入触发 uk 冲突 → 直接回 success 不再入账。
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS t_pay_callback_log (
    log_id        INT          NOT NULL AUTO_INCREMENT COMMENT '日志ID(PK)',
    pay_id        INT          NULL                    COMMENT '关联支付单ID(FK)',
    pay_no        VARCHAR(40)  NULL                    COMMENT '商户订单号',
    trade_no      VARCHAR(64)  NULL                    COMMENT '第三方交易号',
    idem_key      VARCHAR(120) NOT NULL                COMMENT '回调幂等键 pay_no:trade_no（唯一）',
    provider      VARCHAR(20)  NOT NULL DEFAULT 'alipay_sandbox' COMMENT '渠道',
    trade_status  VARCHAR(30)  NULL                    COMMENT '第三方交易状态原文',
    verify_ok     TINYINT      NOT NULL DEFAULT 0      COMMENT '验签是否通过 0/1',
    amount_ok     TINYINT      NOT NULL DEFAULT 0      COMMENT '金额/订单号核验是否通过 0/1',
    applied       TINYINT      NOT NULL DEFAULT 0      COMMENT '是否实际入账 0/1',
    result        VARCHAR(20)  NOT NULL DEFAULT 'IGNORED'
                  COMMENT '处理结果 APPLIED/DUPLICATE/VERIFY_FAIL/AMOUNT_MISMATCH/IGNORED',
    reason        VARCHAR(200) NULL                    COMMENT '原因',
    raw_payload   TEXT         NULL                    COMMENT '回调原始参数（已脱敏，不含密钥/签名密钥）',
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (log_id),
    UNIQUE KEY uk_cb_idem (idem_key),
    KEY idx_cb_pay (pay_id, created_at),
    KEY idx_cb_result (result, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='支付回调流水（幂等键唯一，防重复入账）';

-- ----------------------------------------------------------------------------
-- 10) 演示种子：备包装材料台账（旧库升级也会补齐，INSERT IGNORE 幂等）
-- ----------------------------------------------------------------------------
INSERT IGNORE INTO t_pack_material (name, spec, unit, stock, threshold) VALUES
    ('气泡膜',   '宽 50cm 卷装', '卷', 12, 5),
    ('5 号纸箱', '标准 5 号',    '个', 20, 8),
    ('易碎标签', '红色不干胶',   '张', 50, 20),
    ('缠绕膜',   '宽 30cm 卷装', '卷', 8,  3),
    ('泡沫板',   '厚 2cm',       '块', 15, 5),
    ('封箱胶带', '宽 4.5cm',     '卷', 10, 4);
