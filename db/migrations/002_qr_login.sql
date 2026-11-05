-- ============================================================================
-- 扫码登录扩展 · 迁移脚本 002
-- ----------------------------------------------------------------------------
-- t_qr_ticket：柜机首页二维码的一次性票据。
--   柜机申请票据 → 屏幕展示二维码 → 手机扫码确认 → 柜机轮询换回 token。
-- 状态机：PENDING → CONFIRMED → CONSUMED（终态）
--         PENDING → EXPIRED / CANCELLED
-- 约束要点：票据 128bit 随机 + 唯一索引；2 分钟过期；CONFIRMED 只能被原子消费一次。
--
-- 幂等：CREATE TABLE IF NOT EXISTS，可重复执行。
-- 重放：mysql -u root -p < db/migrations/002_qr_login.sql
-- ============================================================================
USE `smart_locker`;

CREATE TABLE IF NOT EXISTS t_qr_ticket (
    ticket_id    INT          NOT NULL AUTO_INCREMENT COMMENT '票据ID(PK)',
    ticket       CHAR(32)     NOT NULL                COMMENT '随机票据(token_hex(16))',
    purpose      VARCHAR(15)  NOT NULL DEFAULT 'KIOSK_LOGIN' COMMENT '用途 KIOSK_LOGIN/PICKUP',
    cabinet_id   INT          NOT NULL                COMMENT '绑定柜体ID(FK)',
    status       VARCHAR(12)  NOT NULL DEFAULT 'PENDING'
                 COMMENT '状态 PENDING/CONFIRMED/CONSUMED/EXPIRED/CANCELLED',
    confirm_role VARCHAR(10)  NULL                    COMMENT '确认人身份 USER/COURIER',
    confirm_id   INT          NULL                    COMMENT '确认人ID(多态，不加外键)',
    poll_count   INT          NOT NULL DEFAULT 0      COMMENT '柜机轮询次数(限流用)',
    confirmed_at DATETIME     NULL                    COMMENT '手机确认时间',
    consumed_at  DATETIME     NULL                    COMMENT '柜机换取 token 时间',
    expire_at    DATETIME     NOT NULL                COMMENT '过期时间(NOW()+120s)',
    created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '签发时间',
    PRIMARY KEY (ticket_id),
    UNIQUE KEY uk_qr_ticket (ticket),
    CONSTRAINT fk_qr_cabinet FOREIGN KEY (cabinet_id) REFERENCES t_cabinet (cabinet_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT chk_qr_purpose CHECK (purpose IN ('KIOSK_LOGIN','PICKUP')),
    CONSTRAINT chk_qr_status  CHECK (status IN ('PENDING','CONFIRMED','CONSUMED','EXPIRED','CANCELLED')),
    CONSTRAINT chk_qr_role    CHECK (confirm_role IS NULL OR confirm_role IN ('USER','COURIER')),
    -- 身份二元组必须同时为空或同时有值，避免"有角色没ID"的脏数据
    CONSTRAINT chk_qr_confirm CHECK ((confirm_role IS NULL AND confirm_id IS NULL)
                                 OR (confirm_role IS NOT NULL AND confirm_id IS NOT NULL)),
    CONSTRAINT chk_qr_expire  CHECK (expire_at > created_at),
    INDEX idx_qr_cabinet_status (cabinet_id, status, created_at),
    INDEX idx_qr_status_expire (status, expire_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='柜机扫码登录票据（一次性，2 分钟有效）';
