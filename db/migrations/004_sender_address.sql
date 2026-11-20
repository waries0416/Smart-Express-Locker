-- ============================================================================
-- 寄件人 / 收件人地址扩展 · 迁移脚本 004
-- ----------------------------------------------------------------------------
-- 背景（BUG2，用户实测）：寄件表单原先只有寄件人 / 收件人的姓名与手机号，没有地址；
--   但「快递员上门揽收」和「收件人收货」都必须知道地址，只留手机号不成立。
--
-- t_package 新增两列（均可空）：
--   sender_address     寄件人地址（寄件单填写）
--   recipient_address  收件人地址（寄件单填写）
--
-- 幂等与安全：
--   · 只新增**可空列**，不 DROP、不改动任何现有数据；历史寄件单这两列为 NULL，
--     前端按"未填写"展示，不产生回填压力；
--   · MySQL 8.0 没有 ADD COLUMN IF NOT EXISTS，故用 information_schema 判断 +
--     预处理语句（与 003_innovations.sql 同一写法），可重复执行。
--
-- 重放：
--   mysql -u root -p < db/migrations/004_sender_address.sql
--   或 python scripts/init_db.py --migrate
-- ============================================================================
USE `smart_locker`;

-- ----------------------------------------------------------------------------
-- 1) 寄件人地址（放在 recipient_phone 之后，便于与收件人信息相邻阅读）
-- ----------------------------------------------------------------------------
SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_package'
        AND COLUMN_NAME = 'sender_address') = 0,
    'ALTER TABLE t_package ADD COLUMN sender_address VARCHAR(120) NULL COMMENT ''寄件人地址（寄件单填写）'' AFTER recipient_phone',
    'SELECT ''t_package.sender_address already exists'' AS msg'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ----------------------------------------------------------------------------
-- 2) 收件人地址
-- ----------------------------------------------------------------------------
SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_package'
        AND COLUMN_NAME = 'recipient_address') = 0,
    'ALTER TABLE t_package ADD COLUMN recipient_address VARCHAR(120) NULL COMMENT ''收件人地址（寄件单填写）'' AFTER sender_address',
    'SELECT ''t_package.recipient_address already exists'' AS msg'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
