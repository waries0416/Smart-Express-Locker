-- ============================================================================
-- 智能快递柜管理系统  ·  数据库对象 (视图 / 触发器 / 存储过程)
-- 依赖 schema.sql 已执行。本文件各对象之间以专属标记分隔，
-- 供初始化脚本按块执行（每条 CREATE 作为独立语句提交，无需 DELIMITER）。
-- ============================================================================
USE `smart_locker`;

-- ----------------------------------------------------------------------------
-- 视图 1：包裹明细视图（多表关联，避免前端重复 JOIN）
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_package_detail AS
SELECT
    p.package_id,
    p.user_id,
    p.direction,
    p.tracking_no,
    p.status                                   AS pkg_status,
    p.size_type,
    p.weight,
    p.pickup_code,
    p.store_time,
    p.expire_time,
    p.pickup_time,
    p.note,
    p.recipient_name,
    p.recipient_phone,
    p.from_send_id,
    p.overtime_fee,
    p.overtime_fee_paid,
    COALESCE(c1.company_name, c2.company_name) AS company_name,
    cr.name                                    AS courier_name,
    cr.phone                                   AS courier_phone,
    u.name                                     AS user_name,
    u.phone                                    AS user_phone,
    cab.cabinet_code,
    cab.location,
    cell.cell_code,
    p.company_id                               AS chosen_company_id,
    c2.company_name                            AS chosen_company_name,
    sd.tracking_no                             AS from_send_tracking_no,
    sd.status                                  AS from_send_status
FROM t_package p
JOIN t_user             u   ON p.user_id     = u.user_id
JOIN t_cabinet          cab ON p.cabinet_id  = cab.cabinet_id
JOIN t_cell             cell ON p.cell_id    = cell.cell_id
LEFT JOIN t_courier     cr  ON p.courier_id  = cr.courier_id
LEFT JOIN t_express_company c1 ON cr.company_id = c1.company_id
LEFT JOIN t_express_company c2 ON p.company_id  = c2.company_id
LEFT JOIN t_package     sd  ON sd.package_id = p.from_send_id;
/*OBJECTS_SPLIT*/

-- ----------------------------------------------------------------------------
-- 视图 2：柜体占用率视图（统计各柜体格口空闲/占用/故障及占用率）
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_cabinet_occupancy AS
SELECT
    cab.cabinet_id,
    cab.cabinet_code,
    cab.location,
    cab.status                                  AS cabinet_status,
    COUNT(cell.cell_id)                         AS total_cells,
    SUM(CASE WHEN cell.status = 'FREE'      THEN 1 ELSE 0 END) AS free_cells,
    SUM(CASE WHEN cell.status = 'OCCUPIED'  THEN 1 ELSE 0 END) AS occupied_cells,
    SUM(CASE WHEN cell.status = 'FAULT'     THEN 1 ELSE 0 END) AS fault_cells,
    ROUND(SUM(CASE WHEN cell.status = 'OCCUPIED' THEN 1 ELSE 0 END)
          / NULLIF(COUNT(cell.cell_id), 0), 3)  AS occupancy_rate
FROM t_cabinet cab
LEFT JOIN t_cell cell ON cab.cabinet_id = cell.cabinet_id
GROUP BY cab.cabinet_id, cab.cabinet_code, cab.location, cab.status;
/*OBJECTS_SPLIT*/

-- ----------------------------------------------------------------------------
-- 触发器：t_package 状态变更后自动维护业务一致性
--   · 取件成功(PICKED)        -> 释放对应格口(FREE)
--   · 转为异常(EXCEPTION)     -> 格口保持占用(OCCUPIED)，便于定位
--   · 超时(EXPIRED)           -> 自动登记一条 TIMEOUT 异常流转记录(若未登记)
-- ----------------------------------------------------------------------------
CREATE TRIGGER trg_package_after_update
AFTER UPDATE ON t_package
FOR EACH ROW
BEGIN
    IF NEW.status = 'PICKED' AND OLD.status <> 'PICKED' THEN
        UPDATE t_cell SET status = 'FREE' WHERE cell_id = NEW.cell_id;
    END IF;

    IF NEW.status = 'EXCEPTION' AND OLD.status <> 'EXCEPTION' THEN
        UPDATE t_cell SET status = 'OCCUPIED' WHERE cell_id = NEW.cell_id;
    END IF;

    IF NEW.status = 'SEND_COLLECTED' AND OLD.status <> 'SEND_COLLECTED' THEN
        UPDATE t_cell SET status = 'FREE' WHERE cell_id = NEW.cell_id;
    END IF;

    IF NEW.status = 'EXPIRED' AND OLD.status <> 'EXPIRED' THEN
        IF NOT EXISTS (
            SELECT 1 FROM t_exception_log
            WHERE package_id = NEW.package_id AND exception_type = 'TIMEOUT'
        ) THEN
            INSERT INTO t_exception_log
                (package_id, exception_type, occur_time, handle_result, remark)
            VALUES
                (NEW.package_id, 'TIMEOUT', NEW.expire_time, 'PENDING',
                 '系统自动登记：免费取件期已超时');
        END IF;
    END IF;
END;
/*OBJECTS_SPLIT*/

-- ----------------------------------------------------------------------------
-- 存储过程 1：查询单个柜体占用情况
-- ----------------------------------------------------------------------------
CREATE PROCEDURE sp_cabinet_occupancy(IN p_cabinet_id INT)
BEGIN
    SELECT * FROM v_cabinet_occupancy WHERE cabinet_id = p_cabinet_id;
END;
/*OBJECTS_SPLIT*/

-- ----------------------------------------------------------------------------
-- 存储过程 2：各快递公司存件量与超时率排名
-- ----------------------------------------------------------------------------
CREATE PROCEDURE sp_company_ranking()
BEGIN
    SELECT
        c.company_name,
        COUNT(p.package_id)                                                       AS total_cnt,
        SUM(CASE WHEN p.status = 'PICKED'    THEN 1 ELSE 0 END)                    AS picked_cnt,
        SUM(CASE WHEN p.status = 'EXPIRED'   THEN 1 ELSE 0 END)                    AS expired_cnt,
        SUM(CASE WHEN p.status = 'RETURNED'  THEN 1 ELSE 0 END)                    AS returned_cnt,
        CONCAT(ROUND(SUM(CASE WHEN p.status = 'EXPIRED' THEN 1 ELSE 0 END)
              / NULLIF(COUNT(p.package_id), 0) * 100, 1), '%')                     AS timeout_rate
    FROM t_express_company c
    LEFT JOIN t_courier cr ON cr.company_id = c.company_id
    LEFT JOIN t_package p  ON p.courier_id = cr.courier_id
                          OR (p.company_id = c.company_id AND p.direction = 'SEND')
    GROUP BY c.company_id, c.company_name
    ORDER BY total_cnt DESC;
END;
/*OBJECTS_SPLIT*/

-- ----------------------------------------------------------------------------
-- 存储过程 3：最近 N 天每日存取件吞吐量趋势
-- ----------------------------------------------------------------------------
CREATE PROCEDURE sp_daily_throughput(IN p_days INT)
BEGIN
    SELECT
        DATE_FORMAT(d.dt, '%m-%d')                                               AS stat_date,
        SUM(CASE WHEN p.store_time  >= d.dt
                  AND p.store_time  <  d.dt + INTERVAL 1 DAY THEN 1 ELSE 0 END)   AS store_cnt,
        SUM(CASE WHEN p.pickup_time >= d.dt
                  AND p.pickup_time <  d.dt + INTERVAL 1 DAY THEN 1 ELSE 0 END)   AS pickup_cnt
    FROM (
        SELECT CURDATE() - INTERVAL (a.n + 10 * b.n) DAY AS dt
        FROM (SELECT 0 n UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4
              UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9) a,
             (SELECT 0 n UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4) b
        HAVING dt >= CURDATE() - INTERVAL p_days DAY
    ) d
    LEFT JOIN t_package p ON 1 = 1
    GROUP BY d.dt
    ORDER BY d.dt;
END;
/*OBJECTS_SPLIT*/
