-- ============================================================================
-- 手机端（H5）扩展 · 迁移脚本 001
-- ----------------------------------------------------------------------------
-- 新增两张表，支撑「手机远程开柜」这条现实链路：
--   t_sms_code        —— 手机号 + 短信验证码登录（5 分钟有效、一次性使用、60 秒防重发）
--   t_device_command  —— 开柜指令队列（手机下发 → 柜机轮询执行 → 回执），
--                        并用 idempotency_key 保证网络重试不会重复开柜
--
-- 幂等：全部使用 CREATE TABLE IF NOT EXISTS，可重复执行。
-- 重放：mysql -u root -p < db/migrations/001_mobile.sql
-- ============================================================================
USE `smart_locker`;

-- ----------------------------------------------------------------------------
-- 1) 短信验证码 t_sms_code
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS t_sms_code (
    code_id    INT         NOT NULL AUTO_INCREMENT COMMENT '验证码ID(PK)',
    phone      VARCHAR(20) NOT NULL                COMMENT '接收手机号',
    code       CHAR(6)     NOT NULL                COMMENT '6 位数字验证码',
    purpose    VARCHAR(15) NOT NULL DEFAULT 'LOGIN' COMMENT '用途 LOGIN/SEND',
    expire_at  DATETIME    NOT NULL                COMMENT '过期时间',
    used       TINYINT     NOT NULL DEFAULT 0      COMMENT '是否已使用 0/1',
    created_at DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '发送时间',
    PRIMARY KEY (code_id),
    CONSTRAINT chk_sms_phone   CHECK (phone REGEXP '^1[3-9][0-9]{9}$'),
    CONSTRAINT chk_sms_purpose CHECK (purpose IN ('LOGIN','SEND')),
    CONSTRAINT chk_sms_used    CHECK (used IN (0,1)),
    -- 校验路径固定为「手机号 + 用途 + 未使用」，并取最新一条，复合索引直接命中
    INDEX idx_sms_phone  (phone, purpose, used),
    INDEX idx_sms_expire (expire_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='手机端短信验证码（一次性，5 分钟有效）';

-- ----------------------------------------------------------------------------
-- 2) 柜机指令队列 t_device_command
-- ----------------------------------------------------------------------------
-- 状态机：PENDING(待下发) → SENT(已下发待回执) → ACK(柜门已弹开)
--                              ↘ FAILED(执行失败，附 error_msg)
-- 手机端只负责"下指令"，格口是否真的打开由柜机回执确认——这是与
-- 「手机直接改数据库状态」的关键区别，也是异常排查的依据。
CREATE TABLE IF NOT EXISTS t_device_command (
    command_id      INT          NOT NULL AUTO_INCREMENT COMMENT '指令ID(PK)',
    cabinet_id      INT          NOT NULL                COMMENT '目标柜体ID(FK)',
    cell_id         INT          NOT NULL                COMMENT '目标格口ID(FK)',
    package_id      INT          NULL                    COMMENT '关联包裹ID(FK)',
    command_type    VARCHAR(20)  NOT NULL DEFAULT 'OPEN_CELL' COMMENT '指令类型 OPEN_CELL/DIAGNOSE',
    source          VARCHAR(15)  NOT NULL DEFAULT 'MOBILE'    COMMENT '来源 MOBILE/KIOSK/ADMIN',
    status          VARCHAR(15)  NOT NULL DEFAULT 'PENDING'   COMMENT '状态 PENDING/SENT/ACK/FAILED/EXPIRED',
    idempotency_key VARCHAR(64)  NULL                    COMMENT '幂等键（客户端生成，防重复开柜）',
    payload         VARCHAR(200) NULL                    COMMENT '指令参数快照',
    response_json   TEXT         NULL                    COMMENT '下发时的响应快照（重复请求直接复用）',
    error_msg       VARCHAR(200) NULL                    COMMENT '失败原因',
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入队时间',
    sent_at         DATETIME     NULL                    COMMENT '柜机取走时间',
    ack_at          DATETIME     NULL                    COMMENT '柜机回执时间',
    PRIMARY KEY (command_id),
    UNIQUE KEY uk_cmd_idem (idempotency_key),
    CONSTRAINT fk_cmd_cabinet FOREIGN KEY (cabinet_id) REFERENCES t_cabinet (cabinet_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_cmd_cell    FOREIGN KEY (cell_id)    REFERENCES t_cell (cell_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_cmd_pkg     FOREIGN KEY (package_id) REFERENCES t_package (package_id)
        ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT chk_cmd_type   CHECK (command_type IN ('OPEN_CELL','DIAGNOSE')),
    CONSTRAINT chk_cmd_source CHECK (source IN ('MOBILE','KIOSK','ADMIN')),
    CONSTRAINT chk_cmd_status CHECK (status IN ('PENDING','SENT','ACK','FAILED','EXPIRED')),
    -- 柜机轮询固定按「柜体 + 待下发」取任务
    INDEX idx_cmd_cabinet_status (cabinet_id, status),
    INDEX idx_cmd_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='柜机指令队列（手机远程开柜闭环）';
