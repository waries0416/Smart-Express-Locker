-- ============================================================================
-- 支付单缓存二维码内容 · 迁移脚本 005
-- ----------------------------------------------------------------------------
-- 背景（用户真机扫码提示"二维码已失效"）：
--   · alipay.trade.precreate 返回的 qr_code 与 out_trade_no 绑定，码串自生成起
--     2 小时有效，且**对同一 out_trade_no 再次 precreate 会返回一张新码、把旧码顶掉**；
--     码被扫过/交易超时后再扫也会提示失效。
--   · 旧实现每次 create 都重新 precreate（同一 out_trade_no），于是任何一次重复
--     create（打开弹窗、切换渠道、前端重试）都会让用户手里那张码立刻作废。
-- 修复思路：把首次生成的二维码缓存在支付单上，**普通复用直接返回同一张码**
--   （不再重复预下单）；只有"订单过期 / 码已被扫过 / 用户显式刷新"时才换
--   out_trade_no 生成新码（见 payment._reuse_alipay_pending）。
--
-- t_pay_order 新增 qr_code（可空，仅真实渠道使用；mock 恒为 NULL）。
--
-- 幂等与安全：只新增可空列，不 DROP、不改动现有数据；MySQL 8.0 无
-- ADD COLUMN IF NOT EXISTS，故用 information_schema 判断 + 预处理语句（同 003/004）。
-- 重放：mysql -u root -p < db/migrations/005_pay_qr_cache.sql
--       或 python scripts/init_db.py --migrate
-- ============================================================================
USE `smart_locker`;

SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_pay_order'
        AND COLUMN_NAME = 'qr_code') = 0,
    'ALTER TABLE t_pay_order ADD COLUMN qr_code VARCHAR(255) NULL COMMENT ''支付宝预下单二维码内容（缓存；普通复用返回同一张码，避免被新码顶掉）'' AFTER provider_label',
    'SELECT ''t_pay_order.qr_code already exists'' AS msg'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
