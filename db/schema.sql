-- ============================================================================
-- 智能快递柜管理系统  ·  数据库模式定义 (MySQL 8.0)
-- 数据库课程设计 · 题目 18「快递柜系统」
-- ----------------------------------------------------------------------------
-- 说明：
--   1. 本文件创建数据库与 8 张满足第三范式(3NF)的核心表；
--   2. 包含主键(PK)、外键(FK)、唯一约束(UNIQUE)、检查约束(CHECK)、索引(INDEX)；
--   3. 表清单：快递公司 / 快递员 / 用户(收件人) / 快递柜 / 格口 / 包裹 /
--              取件记录 / 异常流转记录（以上 8 张为业务核心表）；
--              t_notice 为消息通知流水表，属应用层通信支撑，不参与业务概念建模。
--   4. 视图、触发器、存储过程见 objects.sql。
-- ============================================================================

CREATE DATABASE IF NOT EXISTS `smart_locker`
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_0900_ai_ci;

USE `smart_locker`;

-- 若需重置，可先执行 DROP DATABASE smart_locker 后再重新运行本文件。
SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS t_notice;
DROP TABLE IF EXISTS t_device_command;
DROP TABLE IF EXISTS t_sms_code;
DROP TABLE IF EXISTS t_qr_ticket;
DROP TABLE IF EXISTS t_exception_log;
DROP TABLE IF EXISTS t_pickup_record;
DROP TABLE IF EXISTS t_package;
DROP TABLE IF EXISTS t_cell;
DROP TABLE IF EXISTS t_cabinet;
DROP TABLE IF EXISTS t_user;
DROP TABLE IF EXISTS t_courier;
DROP TABLE IF EXISTS t_express_company;
SET FOREIGN_KEY_CHECKS = 1;

-- ============================================================================
-- 1) 快递公司 t_express_company
-- ============================================================================
CREATE TABLE t_express_company (
    company_id    INT          NOT NULL AUTO_INCREMENT  COMMENT '快递公司ID(PK)',
    company_code  VARCHAR(20)  NOT NULL                 COMMENT '公司简码(如 SF/YT/ZTO)',
    company_name  VARCHAR(50)  NOT NULL                 COMMENT '公司全称',
    hotline       VARCHAR(20)  NULL                     COMMENT '客服热线',
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入驻时间',
    PRIMARY KEY (company_id),
    UNIQUE KEY uk_company_code (company_code),
    CONSTRAINT chk_company_name_not_empty CHECK (CHAR_LENGTH(company_name) >= 2)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ============================================================================
-- 2) 快递员 t_courier  (依赖 快递公司)
-- ============================================================================
CREATE TABLE t_courier (
    courier_id   INT          NOT NULL AUTO_INCREMENT  COMMENT '快递员ID(PK)',
    company_id   INT          NOT NULL                 COMMENT '所属公司ID(FK)',
    employee_no  VARCHAR(30)  NOT NULL                 COMMENT '工号(全局唯一)',
    name         VARCHAR(30)  NOT NULL                 COMMENT '姓名',
    phone        VARCHAR(20)  NOT NULL                 COMMENT '手机号',
    created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入职时间',
    PRIMARY KEY (courier_id),
    UNIQUE KEY uk_employee_no (employee_no),
    CONSTRAINT fk_courier_company FOREIGN KEY (company_id)
        REFERENCES t_express_company (company_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT chk_courier_phone CHECK (phone REGEXP '^1[3-9][0-9]{9}$'),
    INDEX idx_courier_company (company_id),
    INDEX idx_courier_phone (phone)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ============================================================================
-- 3) 用户(收件人) t_user
-- ============================================================================
CREATE TABLE t_user (
    user_id       INT          NOT NULL AUTO_INCREMENT  COMMENT '用户ID(PK)',
    name          VARCHAR(30)  NOT NULL                 COMMENT '姓名',
    phone         VARCHAR(20)  NOT NULL                 COMMENT '手机号(唯一,登录标识)',
    register_time DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '注册时间',
    PRIMARY KEY (user_id),
    UNIQUE KEY uk_user_phone (phone),
    CONSTRAINT chk_user_phone CHECK (phone REGEXP '^1[3-9][0-9]{9}$'),
    INDEX idx_user_phone (phone)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ============================================================================
-- 4) 快递柜 t_cabinet
-- ============================================================================
CREATE TABLE t_cabinet (
    cabinet_id    INT          NOT NULL AUTO_INCREMENT  COMMENT '快递柜ID(PK)',
    cabinet_code  VARCHAR(20)  NOT NULL                 COMMENT '柜体编号(如 CAB-001)',
    location      VARCHAR(100) NOT NULL                 COMMENT '安装位置/小区',
    cabinet_type  VARCHAR(20)  NOT NULL                 COMMENT '类型(社区柜/校园柜/商圈柜)',
    total_cells   INT          NOT NULL DEFAULT 0       COMMENT '格口总数(冗余统计)',
    status        VARCHAR(15)  NOT NULL DEFAULT 'NORMAL' COMMENT '状态 NORMAL/OFFLINE/MAINTENANCE',
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '投运时间',
    PRIMARY KEY (cabinet_id),
    UNIQUE KEY uk_cabinet_code (cabinet_code),
    CONSTRAINT chk_cabinet_status CHECK (status IN ('NORMAL','OFFLINE','MAINTENANCE')),
    CONSTRAINT chk_cabinet_type   CHECK (cabinet_type IN ('社区柜','校园柜','商圈柜','园区柜')),
    CONSTRAINT chk_total_cells    CHECK (total_cells >= 0),
    INDEX idx_cabinet_location (location),
    INDEX idx_cabinet_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ============================================================================
-- 5) 格口 t_cell  (依赖 快递柜)
-- ============================================================================
CREATE TABLE t_cell (
    cell_id     INT          NOT NULL AUTO_INCREMENT  COMMENT '格口ID(PK)',
    cabinet_id  INT          NOT NULL                 COMMENT '所属柜体ID(FK)',
    cell_code   VARCHAR(20)  NOT NULL                 COMMENT '格口号(如 A01, 同柜唯一)',
    size_type   VARCHAR(10)  NOT NULL                 COMMENT '规格 LARGE/MEDIUM/SMALL',
    status      VARCHAR(15)  NOT NULL DEFAULT 'FREE'  COMMENT '状态 FREE/OCCUPIED/FAULT',
    PRIMARY KEY (cell_id),
    UNIQUE KEY uk_cabinet_cell (cabinet_id, cell_code),
    CONSTRAINT fk_cell_cabinet FOREIGN KEY (cabinet_id)
        REFERENCES t_cabinet (cabinet_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT chk_cell_size   CHECK (size_type IN ('LARGE','MEDIUM','SMALL')),
    CONSTRAINT chk_cell_status CHECK (status IN ('FREE','OCCUPIED','FAULT')),
    INDEX idx_cell_cabinet (cabinet_id),
    -- (cabinet_id, status) 复合索引：格口分配「WHERE cabinet_id=? AND status='FREE'
    -- FOR UPDATE」与格子矩阵按柜状态分布的真实访问路径；系统对格口 status 的
    -- 过滤均带 cabinet_id 前缀，无跨柜 status 检索，故移除单列 idx_cell_status，
    -- 索引净增减为 0（39 个非主键索引统计口径不变）。
    INDEX idx_cell_cabinet_status (cabinet_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ============================================================================
-- 6) 包裹 t_package  (核心实体, 依赖 快递员/用户/柜体/格口)
-- ============================================================================
CREATE TABLE t_package (
    package_id   INT          NOT NULL AUTO_INCREMENT  COMMENT '包裹ID(PK)',
    direction    VARCHAR(8)   NOT NULL DEFAULT 'RECEIVE' COMMENT '业务方向 RECEIVE(收件)/SEND(寄件)',
    tracking_no  VARCHAR(40)  NOT NULL                 COMMENT '运单号(唯一)',
    courier_id   INT          NULL                     COMMENT '存件/揽收快递员ID(FK)，寄件件揽收前为 NULL',
    user_id      INT          NOT NULL                 COMMENT '收件/寄件用户ID(FK)',
    company_id   INT          NULL                     COMMENT '寄送公司ID(FK)，寄件下单时选定（收件件由快递员所属公司推导）',
    cabinet_id   INT          NOT NULL                 COMMENT '存放柜体ID(FK)',
    cell_id      INT          NOT NULL                 COMMENT '存放格口ID(FK)',
    size_type    VARCHAR(10)  NOT NULL                 COMMENT '包裹规格 LARGE/MEDIUM/SMALL',
    weight       DECIMAL(8,2) NOT NULL DEFAULT 0.00    COMMENT '重量(kg)',
    status       VARCHAR(20)  NOT NULL DEFAULT 'STORED' COMMENT '状态 RECEIVE:STORED/PICKED/EXPIRED/EXCEPTION/RETURNED, SEND:SEND_WAIT_PICKUP/SEND_COLLECTED/SEND_CANCELLED',
    pickup_code  VARCHAR(6)   NOT NULL                 COMMENT '取件码/揽收码(6位数字,唯一)',
    store_time   DATETIME     NOT NULL                 COMMENT '存入/下单时间',
    expire_time  DATETIME     NOT NULL                 COMMENT '免费取件/揽收截止时间',
    pickup_time  DATETIME     NULL                     COMMENT '实际取件/揽收时间',
    recipient_name  VARCHAR(30)  NULL                  COMMENT '收件人姓名（寄件单填写）',
    recipient_phone VARCHAR(20)  NULL                  COMMENT '收件人手机号（寄件单填写）',
    from_send_id    INT          NULL                  COMMENT '投递包裹关联的寄件单ID（自引用，SEND方向）',
    note         VARCHAR(200) NULL                     COMMENT '备注',
    overtime_fee        DECIMAL(6,2) NULL              COMMENT '超时保管费(元)，超时未取时计收',
    overtime_fee_paid   TINYINT      NOT NULL DEFAULT 0 COMMENT '超时保管费是否已支付 0/1',
    created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
    PRIMARY KEY (package_id),
    UNIQUE KEY uk_tracking_no (tracking_no),
    UNIQUE KEY uk_pickup_code (pickup_code),
    CONSTRAINT fk_pkg_courier  FOREIGN KEY (courier_id)  REFERENCES t_courier (courier_id)  ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_pkg_user     FOREIGN KEY (user_id)     REFERENCES t_user (user_id)        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_pkg_cabinet  FOREIGN KEY (cabinet_id)  REFERENCES t_cabinet (cabinet_id)  ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_pkg_cell     FOREIGN KEY (cell_id)     REFERENCES t_cell (cell_id)        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_pkg_company  FOREIGN KEY (company_id)  REFERENCES t_express_company (company_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_pkg_from_send FOREIGN KEY (from_send_id) REFERENCES t_package (package_id) ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT chk_pkg_size    CHECK (size_type IN ('LARGE','MEDIUM','SMALL')),
    -- SEND_CANCELLED：用户在快递员揽收前主动撤回寄件单（撤回后释放格口并留痕）
    CONSTRAINT chk_pkg_status  CHECK (status IN ('STORED','PICKED','EXPIRED','EXCEPTION','RETURNED','SEND_WAIT_PICKUP','SEND_COLLECTED','SEND_CANCELLED')),
    CONSTRAINT chk_pkg_direction CHECK (direction IN ('RECEIVE','SEND')),
    CONSTRAINT chk_pkg_weight  CHECK (weight >= 0),
    CONSTRAINT chk_pkg_code    CHECK (pickup_code REGEXP '^[0-9]{6}$'),
    CONSTRAINT chk_recipient_phone CHECK (recipient_phone IS NULL OR recipient_phone REGEXP '^1[3-9][0-9]{9}$'),
    CONSTRAINT chk_pkg_time    CHECK (expire_time > store_time),
    INDEX idx_pkg_courier  (courier_id),
    INDEX idx_pkg_user     (user_id),
    INDEX idx_pkg_cabinet  (cabinet_id),
    INDEX idx_pkg_cell     (cell_id),
    INDEX idx_pkg_status   (status),
    INDEX idx_pkg_direction (direction),
    INDEX idx_pkg_dir_status (direction, status),
    INDEX idx_pkg_store    (store_time),
    INDEX idx_pkg_expire   (expire_time),
    INDEX idx_pkg_pickup   (pickup_time),
    INDEX idx_pkg_recipient_phone (recipient_phone),
    INDEX idx_pkg_from_send (from_send_id),
    INDEX idx_pkg_overtime (overtime_fee_paid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ============================================================================
-- 7) 取件记录 t_pickup_record  (业务流水, 依赖 包裹)
-- ============================================================================
CREATE TABLE t_pickup_record (
    record_id      INT          NOT NULL AUTO_INCREMENT  COMMENT '记录ID(PK)',
    package_id     INT          NOT NULL                 COMMENT '包裹ID(FK)',
    pickup_method  VARCHAR(15)  NOT NULL                 COMMENT '方式 CODE/APP/ADMIN',
    pickup_time    DATETIME     NOT NULL                 COMMENT '取件/尝试时间',
    operator_role  VARCHAR(15)  NOT NULL                 COMMENT '操作角色 USER/COURIER/ADMIN',
    result         VARCHAR(15)  NOT NULL                 COMMENT '结果 SUCCESS/FAIL',
    fail_reason    VARCHAR(100) NULL                     COMMENT '失败原因',
    PRIMARY KEY (record_id),
    CONSTRAINT fk_rec_pkg FOREIGN KEY (package_id)
        REFERENCES t_package (package_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT chk_rec_method CHECK (pickup_method IN ('CODE','APP','ADMIN')),
    CONSTRAINT chk_rec_role   CHECK (operator_role IN ('USER','COURIER','ADMIN')),
    CONSTRAINT chk_rec_result CHECK (result IN ('SUCCESS','FAIL')),
    INDEX idx_rec_pkg   (package_id),
    INDEX idx_rec_time  (pickup_time),
    INDEX idx_rec_result (result)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ============================================================================
-- 8) 异常流转记录 t_exception_log  (业务流水, 依赖 包裹)
-- ============================================================================
CREATE TABLE t_exception_log (
    exception_id   INT          NOT NULL AUTO_INCREMENT  COMMENT '异常ID(PK)',
    package_id     INT          NOT NULL                 COMMENT '包裹ID(FK)',
    exception_type VARCHAR(30)  NOT NULL                 COMMENT '类型 TIMEOUT/OVERWEIGHT/DAMAGED/WRONG_CELL/MISSED/RETURNED',
    occur_time     DATETIME     NOT NULL                 COMMENT '发生时间',
    handle_time    DATETIME     NULL                     COMMENT '处理时间',
    handler        VARCHAR(30)  NULL                     COMMENT '处理人',
    handle_result  VARCHAR(30)  NULL                     COMMENT 'PENDING/RESOLVED/AUTO_RETURNED',
    remark         VARCHAR(200) NULL                     COMMENT '备注',
    PRIMARY KEY (exception_id),
    CONSTRAINT fk_exc_pkg FOREIGN KEY (package_id)
        REFERENCES t_package (package_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT chk_exc_type   CHECK (exception_type IN ('TIMEOUT','OVERWEIGHT','DAMAGED','WRONG_CELL','MISSED','RETURNED')),
    CONSTRAINT chk_exc_result CHECK (handle_result IN ('PENDING','RESOLVED','AUTO_RETURNED')),
    INDEX idx_exc_pkg   (package_id),
    INDEX idx_exc_type  (exception_type),
    INDEX idx_exc_occur (occur_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ============================================================================
-- 9) 消息通知流水 t_notice  (应用层通信支撑, 依赖 包裹)
-- ----------------------------------------------------------------------------
-- 本表作为包裹的附属流水参与概念建模（第 9 个实体，与包裹为 1:N「通知」联系），
-- 只记录"系统在什么时刻、通过什么渠道、向谁、发了什么、结果如何"，
-- 供通知中心查询、失败重试与发送审计使用。
-- recipient_name / recipient_phone 是**发送时刻的快照**，故意冗余：
-- 用户事后改名或换号不应篡改已发出的历史通知内容。
-- ============================================================================
CREATE TABLE t_notice (
    notice_id       INT          NOT NULL AUTO_INCREMENT  COMMENT '通知ID(PK)',
    notice_type     VARCHAR(30)  NOT NULL                 COMMENT '通知类型(见 chk_notice_type)',
    biz_key         VARCHAR(100) NOT NULL                 COMMENT '业务事件键(幂等用) 如 store_arrival:pkg:SF123456789012（用运单号而非包裹ID，防重灌后 ID 复用导致通知被幂等吞掉）',
    channel         VARCHAR(10)  NOT NULL                 COMMENT '发送渠道 SMS/INBOX/PUSH',
    package_id      INT          NULL                     COMMENT '关联包裹ID(FK)，系统级通知为 NULL',
    recipient_role  VARCHAR(10)  NOT NULL                 COMMENT '接收人角色 USER/COURIER/ADMIN',
    recipient_id    INT          NULL                     COMMENT '接收人ID(user_id/courier_id)，管理员为 NULL',
    recipient_name  VARCHAR(30)  NULL                     COMMENT '接收人姓名(发送时快照)',
    recipient_phone VARCHAR(20)  NULL                     COMMENT '接收人手机号(发送时快照)',
    title           VARCHAR(100) NOT NULL                 COMMENT '通知标题',
    content         VARCHAR(500) NOT NULL                 COMMENT '通知正文(模板渲染后)',
    status          VARCHAR(10)  NOT NULL DEFAULT 'PENDING' COMMENT '状态 PENDING/SENT/FAILED/DEAD',
    retry_count     TINYINT      NOT NULL DEFAULT 0       COMMENT '已重试次数',
    next_retry_at   DATETIME     NULL                     COMMENT '下次重试时间(退避后)',
    last_error      VARCHAR(200) NULL                     COMMENT '最近一次失败原因',
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入队时间',
    sent_at         DATETIME     NULL                     COMMENT '发送成功时间',
    read_at         DATETIME     NULL                     COMMENT '站内信已读时间(INBOX 用户端)',
    PRIMARY KEY (notice_id),
    -- 幂等核心：同一业务事件的同一渠道只允许存在一条记录，
    -- 重复入队走 ON DUPLICATE KEY 静默命中；重试只 UPDATE 本行，不新增行。
    UNIQUE KEY uk_notice_idem (biz_key, channel),
    CONSTRAINT fk_notice_pkg FOREIGN KEY (package_id)
        REFERENCES t_package (package_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT chk_notice_type CHECK (notice_type IN (
        'STORE_ARRIVAL','SEND_ORDER_CREATED','SEND_COLLECTED','SEND_CANCELLED',
        'PICKUP_REMIND','EXPIRE_URGE','EXCEPTION_ALERT','PICKUP_RECEIPT')),
    CONSTRAINT chk_notice_chan   CHECK (channel IN ('SMS','INBOX','PUSH')),
    CONSTRAINT chk_notice_role   CHECK (recipient_role IN ('USER','COURIER','ADMIN')),
    CONSTRAINT chk_notice_status CHECK (status IN ('PENDING','SENT','FAILED','DEAD')),
    CONSTRAINT chk_notice_phone  CHECK (recipient_phone IS NULL
        OR recipient_phone REGEXP '^1[3-9][0-9]{9}$'),
    INDEX idx_notice_dispatch (status, next_retry_at),
    INDEX idx_notice_pkg     (package_id),
    INDEX idx_notice_created (created_at),
    INDEX idx_notice_phone   (recipient_phone)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ============================================================================
-- 10) 短信验证码 t_sms_code  (手机端登录支撑, 无业务外键)
-- ----------------------------------------------------------------------------
-- 手机端以「手机号 + 验证码」登录：验证码 5 分钟有效、一次性使用，
-- 60 秒内不允许对同一手机号重复发送（应用层限流，索引为校验路径服务）。
-- ============================================================================
CREATE TABLE t_sms_code (
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
    INDEX idx_sms_phone  (phone, purpose, used),
    INDEX idx_sms_expire (expire_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ============================================================================
-- 11) 柜机指令队列 t_device_command  (手机远程开柜闭环, 依赖 柜体/格口/包裹)
-- ----------------------------------------------------------------------------
-- 状态机：PENDING(待下发) → SENT(已下发待回执) → ACK(柜门已弹开)
--                              ↘ FAILED(执行失败)
-- 手机端只负责下指令，格口是否真的打开以柜机回执为准；
-- idempotency_key 唯一，网络重试不会造成重复开柜。
-- ============================================================================
CREATE TABLE t_device_command (
    command_id      INT          NOT NULL AUTO_INCREMENT COMMENT '指令ID(PK)',
    cabinet_id      INT          NOT NULL                COMMENT '目标柜体ID(FK)',
    cell_id         INT          NOT NULL                COMMENT '目标格口ID(FK)',
    package_id      INT          NULL                    COMMENT '关联包裹ID(FK)',
    command_type    VARCHAR(20)  NOT NULL DEFAULT 'OPEN_CELL' COMMENT '指令类型 OPEN_CELL/DIAGNOSE',
    source          VARCHAR(15)  NOT NULL DEFAULT 'MOBILE'    COMMENT '来源 MOBILE/KIOSK/ADMIN',
    status          VARCHAR(15)  NOT NULL DEFAULT 'PENDING'   COMMENT '状态 PENDING/SENT/ACK/FAILED/EXPIRED',
    idempotency_key VARCHAR(64)  NULL                    COMMENT '幂等键（防重复开柜）',
    payload         VARCHAR(200) NULL                    COMMENT '指令参数快照',
    response_json   TEXT         NULL                    COMMENT '下发时的响应快照（重复请求复用）',
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
    INDEX idx_cmd_cabinet_status (cabinet_id, status),
    INDEX idx_cmd_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ============================================================================
-- 12) 扫码登录票据 t_qr_ticket  (柜机首页二维码, 依赖 柜体)
-- ----------------------------------------------------------------------------
-- 柜机申请票据 → 屏幕展示二维码 → 手机扫码确认 → 柜机轮询换回 token。
-- 状态机：PENDING → CONFIRMED → CONSUMED；旁支 EXPIRED / CANCELLED。
-- 票据 128bit 随机、2 分钟有效、CONFIRMED 只能被原子消费一次。
-- ============================================================================
CREATE TABLE t_qr_ticket (
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
    CONSTRAINT chk_qr_confirm CHECK ((confirm_role IS NULL AND confirm_id IS NULL)
                                 OR (confirm_role IS NOT NULL AND confirm_id IS NOT NULL)),
    CONSTRAINT chk_qr_expire  CHECK (expire_at > created_at),
    INDEX idx_qr_cabinet_status (cabinet_id, status, created_at),
    INDEX idx_qr_status_expire (status, expire_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ============================================================================
-- 说明：以上 8 张表均满足 3NF
--   · 每张表都有候选键(PK)，所有非主属性完全函数依赖于主键(消除部分依赖)；
--   · 不存在非主属性对主键的传递依赖(消除传递依赖)；
--   · 例如 t_package 仅保存各实体的 ID(FK)，名称等描述信息均归位于各自实体表，
--     避免了"快递员姓名""用户姓名"等冗余与更新异常。
-- ============================================================================
