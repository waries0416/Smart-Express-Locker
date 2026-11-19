-- ==========================================================
-- 智能快递柜管理系统 · 初始化脚本 init_database.sql
-- 由 tools/sync_init_dumps.py 自动生成（请勿手工编辑）
-- 包含: 所有表结构(DDL) + 全量测试数据(DML)
-- 重放: mysql -u root -p < init_database.sql
-- 提示: 推荐用 python scripts/init_db.py --fresh 一键初始化
--       （python 侧切分语句，能正确处理触发器/存储过程的 BEGIN…END）
-- ==========================================================

DROP DATABASE IF EXISTS smart_locker;
CREATE DATABASE smart_locker DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE smart_locker;

SET FOREIGN_KEY_CHECKS=0;

DROP TABLE IF EXISTS `t_pay_callback_log`;
DROP TABLE IF EXISTS `t_pay_order`;
DROP TABLE IF EXISTS `t_qr_ticket`;
DROP TABLE IF EXISTS `t_device_command`;
DROP TABLE IF EXISTS `t_sms_code`;
DROP TABLE IF EXISTS `t_notice`;
DROP TABLE IF EXISTS `t_exception_log`;
DROP TABLE IF EXISTS `t_pickup_record`;
DROP TABLE IF EXISTS `t_pack_task_item`;
DROP TABLE IF EXISTS `t_pack_recommend_item`;
DROP TABLE IF EXISTS `t_pack_task`;
DROP TABLE IF EXISTS `t_package`;
DROP TABLE IF EXISTS `t_pack_material`;
DROP TABLE IF EXISTS `t_pack_recommendation`;
DROP TABLE IF EXISTS `t_cell`;
DROP TABLE IF EXISTS `t_courier`;
DROP TABLE IF EXISTS `t_cabinet`;
DROP TABLE IF EXISTS `t_user`;
DROP TABLE IF EXISTS `t_express_company`;
DROP TABLE IF EXISTS `t_schema_migration`;
DROP VIEW IF EXISTS `v_cabinet_occupancy`;
DROP VIEW IF EXISTS `v_package_detail`;

-- ----- 表结构 -----
-- ----- 表 t_schema_migration -----
CREATE TABLE `t_schema_migration` (
  `filename` varchar(120) NOT NULL COMMENT '迁移文件名',
  `applied_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`filename`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='数据库迁移应用记录（旧库升级幂等依据）';
-- ----- 表 t_express_company -----
CREATE TABLE `t_express_company` (
  `company_id` int NOT NULL AUTO_INCREMENT COMMENT '快递公司ID(PK)',
  `company_code` varchar(20) NOT NULL COMMENT '公司简码(如 SF/YT/ZTO)',
  `company_name` varchar(50) NOT NULL COMMENT '公司全称',
  `hotline` varchar(20) DEFAULT NULL COMMENT '客服热线',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入驻时间',
  PRIMARY KEY (`company_id`),
  UNIQUE KEY `uk_company_code` (`company_code`),
  CONSTRAINT `chk_company_name_not_empty` CHECK ((char_length(`company_name`) >= 2))
) ENGINE=InnoDB AUTO_INCREMENT=110 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- ----- 表 t_user -----
CREATE TABLE `t_user` (
  `user_id` int NOT NULL AUTO_INCREMENT COMMENT '用户ID(PK)',
  `name` varchar(30) NOT NULL COMMENT '姓名',
  `phone` varchar(20) NOT NULL COMMENT '手机号(唯一,登录标识)',
  `register_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '注册时间',
  PRIMARY KEY (`user_id`),
  UNIQUE KEY `uk_user_phone` (`phone`),
  KEY `idx_user_phone` (`phone`),
  CONSTRAINT `chk_user_phone` CHECK (regexp_like(`phone`,_utf8mb4'^1[3-9][0-9]{9}$'))
) ENGINE=InnoDB AUTO_INCREMENT=205 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- ----- 表 t_cabinet -----
CREATE TABLE `t_cabinet` (
  `cabinet_id` int NOT NULL AUTO_INCREMENT COMMENT '快递柜ID(PK)',
  `cabinet_code` varchar(20) NOT NULL COMMENT '柜体编号(如 CAB-001)',
  `location` varchar(100) NOT NULL COMMENT '安装位置/小区',
  `latitude` decimal(9,6) DEFAULT NULL COMMENT '纬度(WGS84，-90~90)，创新点3 附近柜机距离计算',
  `longitude` decimal(9,6) DEFAULT NULL COMMENT '经度(WGS84，-180~180)，创新点3 附近柜机距离计算',
  `cabinet_type` varchar(20) NOT NULL COMMENT '类型(社区柜/校园柜/商圈柜)',
  `total_cells` int NOT NULL DEFAULT '0' COMMENT '格口总数(冗余统计)',
  `status` varchar(15) NOT NULL DEFAULT 'NORMAL' COMMENT '状态 NORMAL/OFFLINE/MAINTENANCE',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '投运时间',
  PRIMARY KEY (`cabinet_id`),
  UNIQUE KEY `uk_cabinet_code` (`cabinet_code`),
  KEY `idx_cabinet_location` (`location`),
  KEY `idx_cabinet_status` (`status`),
  KEY `idx_cabinet_coord` (`latitude`,`longitude`),
  CONSTRAINT `chk_cabinet_status` CHECK ((`status` in (_utf8mb4'NORMAL',_utf8mb4'OFFLINE',_utf8mb4'MAINTENANCE'))),
  CONSTRAINT `chk_cabinet_type` CHECK ((`cabinet_type` in (_utf8mb4'社区柜',_utf8mb4'校园柜',_utf8mb4'商圈柜',_utf8mb4'园区柜'))),
  CONSTRAINT `chk_total_cells` CHECK ((`total_cells` >= 0))
) ENGINE=InnoDB AUTO_INCREMENT=109 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- ----- 表 t_courier -----
CREATE TABLE `t_courier` (
  `courier_id` int NOT NULL AUTO_INCREMENT COMMENT '快递员ID(PK)',
  `company_id` int NOT NULL COMMENT '所属公司ID(FK)',
  `employee_no` varchar(30) NOT NULL COMMENT '工号(全局唯一)',
  `name` varchar(30) NOT NULL COMMENT '姓名',
  `phone` varchar(20) NOT NULL COMMENT '手机号',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入职时间',
  PRIMARY KEY (`courier_id`),
  UNIQUE KEY `uk_employee_no` (`employee_no`),
  KEY `idx_courier_company` (`company_id`),
  KEY `idx_courier_phone` (`phone`),
  CONSTRAINT `fk_courier_company` FOREIGN KEY (`company_id`) REFERENCES `t_express_company` (`company_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `chk_courier_phone` CHECK (regexp_like(`phone`,_utf8mb4'^1[3-9][0-9]{9}$'))
) ENGINE=InnoDB AUTO_INCREMENT=156 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- ----- 表 t_cell -----
CREATE TABLE `t_cell` (
  `cell_id` int NOT NULL AUTO_INCREMENT COMMENT '格口ID(PK)',
  `cabinet_id` int NOT NULL COMMENT '所属柜体ID(FK)',
  `cell_code` varchar(20) NOT NULL COMMENT '格口号(如 A01, 同柜唯一)',
  `size_type` varchar(10) NOT NULL COMMENT '规格 LARGE/MEDIUM/SMALL',
  `status` varchar(15) NOT NULL DEFAULT 'FREE' COMMENT '状态 FREE/OCCUPIED/FAULT',
  PRIMARY KEY (`cell_id`),
  UNIQUE KEY `uk_cabinet_cell` (`cabinet_id`,`cell_code`),
  KEY `idx_cell_cabinet` (`cabinet_id`),
  KEY `idx_cell_cabinet_status` (`cabinet_id`,`status`),
  CONSTRAINT `fk_cell_cabinet` FOREIGN KEY (`cabinet_id`) REFERENCES `t_cabinet` (`cabinet_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `chk_cell_size` CHECK ((`size_type` in (_utf8mb4'LARGE',_utf8mb4'MEDIUM',_utf8mb4'SMALL'))),
  CONSTRAINT `chk_cell_status` CHECK ((`status` in (_utf8mb4'FREE',_utf8mb4'OCCUPIED',_utf8mb4'FAULT')))
) ENGINE=InnoDB AUTO_INCREMENT=955 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- ----- 表 t_pack_recommendation -----
CREATE TABLE `t_pack_recommendation` (
  `recommendation_id` int NOT NULL AUTO_INCREMENT COMMENT '推荐ID(PK)',
  `description` varchar(500) NOT NULL COMMENT '用户物品描述',
  `source` varchar(10) NOT NULL DEFAULT 'rule' COMMENT '结果来源 deepseek/rule',
  `degraded` tinyint NOT NULL DEFAULT '0' COMMENT '是否降级到本地规则 0/1',
  `degraded_reason` varchar(200) DEFAULT NULL COMMENT '降级原因（中文）',
  `size_type` varchar(10) NOT NULL DEFAULT 'MEDIUM' COMMENT '建议格口规格 SMALL/MEDIUM/LARGE',
  `size_reason` varchar(255) DEFAULT NULL COMMENT '规格理由',
  `elapsed_ms` int NOT NULL DEFAULT '0' COMMENT '服务端耗时(ms)',
  `notice` varchar(200) DEFAULT NULL COMMENT '免责提示',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '生成时间',
  PRIMARY KEY (`recommendation_id`),
  KEY `idx_rec_created` (`created_at`),
  KEY `idx_rec_source` (`source`),
  CONSTRAINT `chk_rec_degraded` CHECK ((`degraded` in (0,1))),
  CONSTRAINT `chk_rec_size` CHECK ((`size_type` in (_utf8mb4'SMALL',_utf8mb4'MEDIUM',_utf8mb4'LARGE'))),
  CONSTRAINT `chk_rec_source` CHECK ((`source` in (_utf8mb4'deepseek',_utf8mb4'rule')))
) ENGINE=InnoDB AUTO_INCREMENT=58 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='AI/规则包装推荐结果（创新点 1）';
-- ----- 表 t_pack_material -----
CREATE TABLE `t_pack_material` (
  `material_id` int NOT NULL AUTO_INCREMENT COMMENT '材料ID(PK)',
  `name` varchar(50) NOT NULL COMMENT '材料名',
  `spec` varchar(50) DEFAULT NULL COMMENT '规格描述',
  `unit` varchar(20) NOT NULL DEFAULT '件' COMMENT '计量单位',
  `stock` int NOT NULL DEFAULT '0' COMMENT '当前库存',
  `threshold` int NOT NULL DEFAULT '5' COMMENT '低库存阈值',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`material_id`),
  UNIQUE KEY `uk_material_name` (`name`),
  CONSTRAINT `chk_material_stock` CHECK ((`stock` >= 0)),
  CONSTRAINT `chk_material_threshold` CHECK ((`threshold` >= 0))
) ENGINE=InnoDB AUTO_INCREMENT=19 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='备包装材料台账（创新点 2）';
-- ----- 表 t_package -----
CREATE TABLE `t_package` (
  `package_id` int NOT NULL AUTO_INCREMENT COMMENT '包裹ID(PK)',
  `direction` varchar(8) NOT NULL DEFAULT 'RECEIVE' COMMENT '业务方向 RECEIVE(收件)/SEND(寄件)',
  `tracking_no` varchar(40) NOT NULL COMMENT '运单号(唯一)',
  `courier_id` int DEFAULT NULL COMMENT '存件/揽收快递员ID(FK)，寄件件揽收前为 NULL',
  `user_id` int NOT NULL COMMENT '收件/寄件用户ID(FK)',
  `company_id` int DEFAULT NULL COMMENT '寄送公司ID(FK)，寄件下单时选定（收件件由快递员所属公司推导）',
  `cabinet_id` int NOT NULL COMMENT '存放柜体ID(FK)',
  `cell_id` int NOT NULL COMMENT '存放格口ID(FK)',
  `size_type` varchar(10) NOT NULL COMMENT '包裹规格 LARGE/MEDIUM/SMALL',
  `weight` decimal(8,2) NOT NULL DEFAULT '0.00' COMMENT '重量(kg)',
  `status` varchar(20) NOT NULL DEFAULT 'STORED' COMMENT '状态 RECEIVE:STORED/PICKED/EXPIRED/EXCEPTION/RETURNED, SEND:SEND_WAIT_PICKUP/SEND_COLLECTED/SEND_CANCELLED',
  `pickup_code` varchar(6) NOT NULL COMMENT '取件码/揽收码(6位数字,唯一)',
  `store_time` datetime NOT NULL COMMENT '存入/下单时间',
  `expire_time` datetime NOT NULL COMMENT '免费取件/揽收截止时间',
  `pickup_time` datetime DEFAULT NULL COMMENT '实际取件/揽收时间',
  `recipient_name` varchar(30) DEFAULT NULL COMMENT '收件人姓名（寄件单填写）',
  `recipient_phone` varchar(20) DEFAULT NULL COMMENT '收件人手机号（寄件单填写）',
  `from_send_id` int DEFAULT NULL COMMENT '投递包裹关联的寄件单ID（自引用，SEND方向）',
  `note` varchar(200) DEFAULT NULL COMMENT '备注',
  `pack_recommendation_id` int DEFAULT NULL COMMENT '引用的包装推荐ID(FK，可空，创新点2)',
  `overtime_fee` decimal(6,2) DEFAULT NULL COMMENT '超时保管费(元)，超时未取时计收',
  `overtime_fee_paid` tinyint NOT NULL DEFAULT '0' COMMENT '超时保管费是否已支付 0/1',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  PRIMARY KEY (`package_id`),
  UNIQUE KEY `uk_tracking_no` (`tracking_no`),
  UNIQUE KEY `uk_pickup_code` (`pickup_code`),
  KEY `fk_pkg_company` (`company_id`),
  KEY `idx_pkg_courier` (`courier_id`),
  KEY `idx_pkg_user` (`user_id`),
  KEY `idx_pkg_cabinet` (`cabinet_id`),
  KEY `idx_pkg_cell` (`cell_id`),
  KEY `idx_pkg_status` (`status`),
  KEY `idx_pkg_direction` (`direction`),
  KEY `idx_pkg_dir_status` (`direction`,`status`),
  KEY `idx_pkg_store` (`store_time`),
  KEY `idx_pkg_expire` (`expire_time`),
  KEY `idx_pkg_pickup` (`pickup_time`),
  KEY `idx_pkg_recipient_phone` (`recipient_phone`),
  KEY `idx_pkg_from_send` (`from_send_id`),
  KEY `idx_pkg_overtime` (`overtime_fee_paid`),
  KEY `idx_pkg_pack_rec` (`pack_recommendation_id`),
  CONSTRAINT `fk_pkg_cabinet` FOREIGN KEY (`cabinet_id`) REFERENCES `t_cabinet` (`cabinet_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_pkg_cell` FOREIGN KEY (`cell_id`) REFERENCES `t_cell` (`cell_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_pkg_company` FOREIGN KEY (`company_id`) REFERENCES `t_express_company` (`company_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_pkg_courier` FOREIGN KEY (`courier_id`) REFERENCES `t_courier` (`courier_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_pkg_from_send` FOREIGN KEY (`from_send_id`) REFERENCES `t_package` (`package_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_pkg_pack_rec` FOREIGN KEY (`pack_recommendation_id`) REFERENCES `t_pack_recommendation` (`recommendation_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_pkg_user` FOREIGN KEY (`user_id`) REFERENCES `t_user` (`user_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `chk_pkg_code` CHECK (regexp_like(`pickup_code`,_utf8mb4'^[0-9]{6}$')),
  CONSTRAINT `chk_pkg_direction` CHECK ((`direction` in (_utf8mb4'RECEIVE',_utf8mb4'SEND'))),
  CONSTRAINT `chk_pkg_size` CHECK ((`size_type` in (_utf8mb4'LARGE',_utf8mb4'MEDIUM',_utf8mb4'SMALL'))),
  CONSTRAINT `chk_pkg_status` CHECK ((`status` in (_utf8mb4'STORED',_utf8mb4'PICKED',_utf8mb4'EXPIRED',_utf8mb4'EXCEPTION',_utf8mb4'RETURNED',_utf8mb4'SEND_WAIT_PICKUP',_utf8mb4'SEND_COLLECTED',_utf8mb4'SEND_CANCELLED'))),
  CONSTRAINT `chk_pkg_time` CHECK ((`expire_time` > `store_time`)),
  CONSTRAINT `chk_pkg_weight` CHECK ((`weight` >= 0)),
  CONSTRAINT `chk_recipient_phone` CHECK (((`recipient_phone` is null) or regexp_like(`recipient_phone`,_utf8mb4'^1[3-9][0-9]{9}$')))
) ENGINE=InnoDB AUTO_INCREMENT=372 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- ----- 表 t_pack_task -----
CREATE TABLE `t_pack_task` (
  `task_id` int NOT NULL AUTO_INCREMENT COMMENT '任务ID(PK)',
  `package_id` int DEFAULT NULL COMMENT '关联包裹ID(FK)',
  `recommendation_id` int DEFAULT NULL COMMENT '引用推荐ID(FK)',
  `assignee_courier_id` int DEFAULT NULL COMMENT '指派快递员ID(FK)',
  `cabinet_id` int DEFAULT NULL COMMENT '柜体ID(FK)',
  `size_type` varchar(10) DEFAULT NULL COMMENT '建议格口规格',
  `status` varchar(12) NOT NULL DEFAULT 'PENDING' COMMENT '状态 PENDING/DONE/CANCELED',
  `note` varchar(200) DEFAULT NULL COMMENT '备注',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `done_at` datetime DEFAULT NULL COMMENT '完成时间',
  PRIMARY KEY (`task_id`),
  KEY `idx_task_assignee_status` (`assignee_courier_id`,`status`,`created_at`),
  KEY `idx_task_package` (`package_id`),
  KEY `idx_task_status` (`status`,`created_at`),
  KEY `fk_task_rec` (`recommendation_id`),
  KEY `fk_task_cabinet` (`cabinet_id`),
  CONSTRAINT `fk_task_cabinet` FOREIGN KEY (`cabinet_id`) REFERENCES `t_cabinet` (`cabinet_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_task_courier` FOREIGN KEY (`assignee_courier_id`) REFERENCES `t_courier` (`courier_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_task_package` FOREIGN KEY (`package_id`) REFERENCES `t_package` (`package_id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_task_rec` FOREIGN KEY (`recommendation_id`) REFERENCES `t_pack_recommendation` (`recommendation_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `chk_task_size` CHECK (((`size_type` is null) or (`size_type` in (_utf8mb4'SMALL',_utf8mb4'MEDIUM',_utf8mb4'LARGE')))),
  CONSTRAINT `chk_task_status` CHECK ((`status` in (_utf8mb4'PENDING',_utf8mb4'DONE',_utf8mb4'CANCELED')))
) ENGINE=InnoDB AUTO_INCREMENT=19 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='快递员备包装任务（创新点 2）';
-- ----- 表 t_pack_recommend_item -----
CREATE TABLE `t_pack_recommend_item` (
  `item_id` int NOT NULL AUTO_INCREMENT COMMENT '明细ID(PK)',
  `recommendation_id` int NOT NULL COMMENT '所属推荐ID(FK)',
  `kind` varchar(12) NOT NULL COMMENT '类型 FORBIDDEN/SENSITIVE/STEP/MATERIAL',
  `seq` int NOT NULL DEFAULT '0' COMMENT '顺序号',
  `name` varchar(100) DEFAULT NULL COMMENT '名称',
  `detail` varchar(500) DEFAULT NULL COMMENT '说明',
  `qty` int DEFAULT NULL COMMENT '数量',
  `unit` varchar(20) DEFAULT NULL COMMENT '单位',
  PRIMARY KEY (`item_id`),
  KEY `idx_recitem_rec` (`recommendation_id`,`kind`,`seq`),
  CONSTRAINT `fk_recitem_rec` FOREIGN KEY (`recommendation_id`) REFERENCES `t_pack_recommendation` (`recommendation_id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `chk_recitem_kind` CHECK ((`kind` in (_utf8mb4'FORBIDDEN',_utf8mb4'SENSITIVE',_utf8mb4'STEP',_utf8mb4'MATERIAL')))
) ENGINE=InnoDB AUTO_INCREMENT=451 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='包装推荐明细';
-- ----- 表 t_pack_task_item -----
CREATE TABLE `t_pack_task_item` (
  `task_item_id` int NOT NULL AUTO_INCREMENT COMMENT '明细ID(PK)',
  `task_id` int NOT NULL COMMENT '所属任务ID(FK)',
  `material_id` int DEFAULT NULL COMMENT '材料台账ID(FK)',
  `name` varchar(50) NOT NULL COMMENT '材料名快照',
  `qty` int NOT NULL DEFAULT '1' COMMENT '数量',
  `unit` varchar(20) NOT NULL DEFAULT '件' COMMENT '单位快照',
  PRIMARY KEY (`task_item_id`),
  KEY `idx_taskitem_task` (`task_id`),
  KEY `fk_taskitem_material` (`material_id`),
  CONSTRAINT `fk_taskitem_material` FOREIGN KEY (`material_id`) REFERENCES `t_pack_material` (`material_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_taskitem_task` FOREIGN KEY (`task_id`) REFERENCES `t_pack_task` (`task_id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `chk_taskitem_qty` CHECK ((`qty` > 0))
) ENGINE=InnoDB AUTO_INCREMENT=72 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='备包装任务材料快照';
-- ----- 表 t_pickup_record -----
CREATE TABLE `t_pickup_record` (
  `record_id` int NOT NULL AUTO_INCREMENT COMMENT '记录ID(PK)',
  `package_id` int NOT NULL COMMENT '包裹ID(FK)',
  `pickup_method` varchar(15) NOT NULL COMMENT '方式 CODE/APP/ADMIN',
  `pickup_time` datetime NOT NULL COMMENT '取件/尝试时间',
  `operator_role` varchar(15) NOT NULL COMMENT '操作角色 USER/COURIER/ADMIN',
  `result` varchar(15) NOT NULL COMMENT '结果 SUCCESS/FAIL',
  `fail_reason` varchar(100) DEFAULT NULL COMMENT '失败原因',
  PRIMARY KEY (`record_id`),
  KEY `idx_rec_pkg` (`package_id`),
  KEY `idx_rec_time` (`pickup_time`),
  KEY `idx_rec_result` (`result`),
  CONSTRAINT `fk_rec_pkg` FOREIGN KEY (`package_id`) REFERENCES `t_package` (`package_id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `chk_rec_method` CHECK ((`pickup_method` in (_utf8mb4'CODE',_utf8mb4'APP',_utf8mb4'ADMIN'))),
  CONSTRAINT `chk_rec_result` CHECK ((`result` in (_utf8mb4'SUCCESS',_utf8mb4'FAIL'))),
  CONSTRAINT `chk_rec_role` CHECK ((`operator_role` in (_utf8mb4'USER',_utf8mb4'COURIER',_utf8mb4'ADMIN')))
) ENGINE=InnoDB AUTO_INCREMENT=235 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- ----- 表 t_exception_log -----
CREATE TABLE `t_exception_log` (
  `exception_id` int NOT NULL AUTO_INCREMENT COMMENT '异常ID(PK)',
  `package_id` int NOT NULL COMMENT '包裹ID(FK)',
  `exception_type` varchar(30) NOT NULL COMMENT '类型 TIMEOUT/OVERWEIGHT/DAMAGED/WRONG_CELL/MISSED/RETURNED',
  `occur_time` datetime NOT NULL COMMENT '发生时间',
  `handle_time` datetime DEFAULT NULL COMMENT '处理时间',
  `handler` varchar(30) DEFAULT NULL COMMENT '处理人',
  `handle_result` varchar(30) DEFAULT NULL COMMENT 'PENDING/RESOLVED/AUTO_RETURNED',
  `remark` varchar(200) DEFAULT NULL COMMENT '备注',
  PRIMARY KEY (`exception_id`),
  KEY `idx_exc_pkg` (`package_id`),
  KEY `idx_exc_type` (`exception_type`),
  KEY `idx_exc_occur` (`occur_time`),
  CONSTRAINT `fk_exc_pkg` FOREIGN KEY (`package_id`) REFERENCES `t_package` (`package_id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `chk_exc_result` CHECK ((`handle_result` in (_utf8mb4'PENDING',_utf8mb4'RESOLVED',_utf8mb4'AUTO_RETURNED'))),
  CONSTRAINT `chk_exc_type` CHECK ((`exception_type` in (_utf8mb4'TIMEOUT',_utf8mb4'OVERWEIGHT',_utf8mb4'DAMAGED',_utf8mb4'WRONG_CELL',_utf8mb4'MISSED',_utf8mb4'RETURNED')))
) ENGINE=InnoDB AUTO_INCREMENT=233 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- ----- 表 t_notice -----
CREATE TABLE `t_notice` (
  `notice_id` int NOT NULL AUTO_INCREMENT COMMENT '通知ID(PK)',
  `notice_type` varchar(30) NOT NULL COMMENT '通知类型(见 chk_notice_type)',
  `biz_key` varchar(100) NOT NULL COMMENT '业务事件键(幂等用) 如 store_arrival:pkg:SF123456789012（用运单号而非包裹ID，防重灌后 ID 复用导致通知被幂等吞掉）',
  `channel` varchar(10) NOT NULL COMMENT '发送渠道 SMS/INBOX/PUSH',
  `package_id` int DEFAULT NULL COMMENT '关联包裹ID(FK)，系统级通知为 NULL',
  `recipient_role` varchar(10) NOT NULL COMMENT '接收人角色 USER/COURIER/ADMIN',
  `recipient_id` int DEFAULT NULL COMMENT '接收人ID(user_id/courier_id)，管理员为 NULL',
  `recipient_name` varchar(30) DEFAULT NULL COMMENT '接收人姓名(发送时快照)',
  `recipient_phone` varchar(20) DEFAULT NULL COMMENT '接收人手机号(发送时快照)',
  `title` varchar(100) NOT NULL COMMENT '通知标题',
  `content` varchar(500) NOT NULL COMMENT '通知正文(模板渲染后)',
  `status` varchar(10) NOT NULL DEFAULT 'PENDING' COMMENT '状态 PENDING/SENT/FAILED/DEAD',
  `retry_count` tinyint NOT NULL DEFAULT '0' COMMENT '已重试次数',
  `next_retry_at` datetime DEFAULT NULL COMMENT '下次重试时间(退避后)',
  `last_error` varchar(200) DEFAULT NULL COMMENT '最近一次失败原因',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入队时间',
  `sent_at` datetime DEFAULT NULL COMMENT '发送成功时间',
  `read_at` datetime DEFAULT NULL COMMENT '站内信已读时间(INBOX 用户端)',
  PRIMARY KEY (`notice_id`),
  UNIQUE KEY `uk_notice_idem` (`biz_key`,`channel`),
  KEY `idx_notice_dispatch` (`status`,`next_retry_at`),
  KEY `idx_notice_pkg` (`package_id`),
  KEY `idx_notice_created` (`created_at`),
  KEY `idx_notice_phone` (`recipient_phone`),
  CONSTRAINT `fk_notice_pkg` FOREIGN KEY (`package_id`) REFERENCES `t_package` (`package_id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `chk_notice_chan` CHECK ((`channel` in (_utf8mb4'SMS',_utf8mb4'INBOX',_utf8mb4'PUSH'))),
  CONSTRAINT `chk_notice_phone` CHECK (((`recipient_phone` is null) or regexp_like(`recipient_phone`,_utf8mb4'^1[3-9][0-9]{9}$'))),
  CONSTRAINT `chk_notice_role` CHECK ((`recipient_role` in (_utf8mb4'USER',_utf8mb4'COURIER',_utf8mb4'ADMIN'))),
  CONSTRAINT `chk_notice_status` CHECK ((`status` in (_utf8mb4'PENDING',_utf8mb4'SENT',_utf8mb4'FAILED',_utf8mb4'DEAD'))),
  CONSTRAINT `chk_notice_type` CHECK ((`notice_type` in (_utf8mb4'STORE_ARRIVAL',_utf8mb4'SEND_ORDER_CREATED',_utf8mb4'SEND_COLLECTED',_utf8mb4'SEND_CANCELLED',_utf8mb4'PICKUP_REMIND',_utf8mb4'EXPIRE_URGE',_utf8mb4'EXCEPTION_ALERT',_utf8mb4'PICKUP_RECEIPT')))
) ENGINE=InnoDB AUTO_INCREMENT=19 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- ----- 表 t_sms_code -----
CREATE TABLE `t_sms_code` (
  `code_id` int NOT NULL AUTO_INCREMENT COMMENT '验证码ID(PK)',
  `phone` varchar(20) NOT NULL COMMENT '接收手机号',
  `code` char(6) NOT NULL COMMENT '6 位数字验证码',
  `purpose` varchar(15) NOT NULL DEFAULT 'LOGIN' COMMENT '用途 LOGIN/SEND',
  `expire_at` datetime NOT NULL COMMENT '过期时间',
  `used` tinyint NOT NULL DEFAULT '0' COMMENT '是否已使用 0/1',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '发送时间',
  PRIMARY KEY (`code_id`),
  KEY `idx_sms_phone` (`phone`,`purpose`,`used`),
  KEY `idx_sms_expire` (`expire_at`),
  CONSTRAINT `chk_sms_phone` CHECK (regexp_like(`phone`,_utf8mb4'^1[3-9][0-9]{9}$')),
  CONSTRAINT `chk_sms_purpose` CHECK ((`purpose` in (_utf8mb4'LOGIN',_utf8mb4'SEND'))),
  CONSTRAINT `chk_sms_used` CHECK ((`used` in (0,1)))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='手机端短信验证码（一次性，5 分钟有效）';
-- ----- 表 t_device_command -----
CREATE TABLE `t_device_command` (
  `command_id` int NOT NULL AUTO_INCREMENT COMMENT '指令ID(PK)',
  `cabinet_id` int NOT NULL COMMENT '目标柜体ID(FK)',
  `cell_id` int NOT NULL COMMENT '目标格口ID(FK)',
  `package_id` int DEFAULT NULL COMMENT '关联包裹ID(FK)',
  `command_type` varchar(20) NOT NULL DEFAULT 'OPEN_CELL' COMMENT '指令类型 OPEN_CELL/DIAGNOSE',
  `source` varchar(15) NOT NULL DEFAULT 'MOBILE' COMMENT '来源 MOBILE/KIOSK/ADMIN',
  `status` varchar(15) NOT NULL DEFAULT 'PENDING' COMMENT '状态 PENDING/SENT/ACK/FAILED/EXPIRED',
  `idempotency_key` varchar(64) DEFAULT NULL COMMENT '幂等键（客户端生成，防重复开柜）',
  `payload` varchar(200) DEFAULT NULL COMMENT '指令参数快照',
  `response_json` text COMMENT '下发时的响应快照（重复请求直接复用）',
  `error_msg` varchar(200) DEFAULT NULL COMMENT '失败原因',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入队时间',
  `sent_at` datetime DEFAULT NULL COMMENT '柜机取走时间',
  `ack_at` datetime DEFAULT NULL COMMENT '柜机回执时间',
  PRIMARY KEY (`command_id`),
  UNIQUE KEY `uk_cmd_idem` (`idempotency_key`),
  KEY `fk_cmd_cell` (`cell_id`),
  KEY `fk_cmd_pkg` (`package_id`),
  KEY `idx_cmd_cabinet_status` (`cabinet_id`,`status`),
  KEY `idx_cmd_created` (`created_at`),
  CONSTRAINT `fk_cmd_cabinet` FOREIGN KEY (`cabinet_id`) REFERENCES `t_cabinet` (`cabinet_id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_cmd_cell` FOREIGN KEY (`cell_id`) REFERENCES `t_cell` (`cell_id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_cmd_pkg` FOREIGN KEY (`package_id`) REFERENCES `t_package` (`package_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `chk_cmd_source` CHECK ((`source` in (_utf8mb4'MOBILE',_utf8mb4'KIOSK',_utf8mb4'ADMIN'))),
  CONSTRAINT `chk_cmd_status` CHECK ((`status` in (_utf8mb4'PENDING',_utf8mb4'SENT',_utf8mb4'ACK',_utf8mb4'FAILED',_utf8mb4'EXPIRED'))),
  CONSTRAINT `chk_cmd_type` CHECK ((`command_type` in (_utf8mb4'OPEN_CELL',_utf8mb4'DIAGNOSE')))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='柜机指令队列（手机远程开柜闭环）';
-- ----- 表 t_qr_ticket -----
CREATE TABLE `t_qr_ticket` (
  `ticket_id` int NOT NULL AUTO_INCREMENT COMMENT '票据ID(PK)',
  `ticket` char(32) NOT NULL COMMENT '随机票据(token_hex(16))',
  `purpose` varchar(15) NOT NULL DEFAULT 'KIOSK_LOGIN' COMMENT '用途 KIOSK_LOGIN/PICKUP',
  `cabinet_id` int NOT NULL COMMENT '绑定柜体ID(FK)',
  `status` varchar(12) NOT NULL DEFAULT 'PENDING' COMMENT '状态 PENDING/CONFIRMED/CONSUMED/EXPIRED/CANCELLED',
  `confirm_role` varchar(10) DEFAULT NULL COMMENT '确认人身份 USER/COURIER',
  `confirm_id` int DEFAULT NULL COMMENT '确认人ID(多态，不加外键)',
  `poll_count` int NOT NULL DEFAULT '0' COMMENT '柜机轮询次数(限流用)',
  `confirmed_at` datetime DEFAULT NULL COMMENT '手机确认时间',
  `consumed_at` datetime DEFAULT NULL COMMENT '柜机换取 token 时间',
  `expire_at` datetime NOT NULL COMMENT '过期时间(NOW()+120s)',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '签发时间',
  PRIMARY KEY (`ticket_id`),
  UNIQUE KEY `uk_qr_ticket` (`ticket`),
  KEY `idx_qr_cabinet_status` (`cabinet_id`,`status`,`created_at`),
  KEY `idx_qr_status_expire` (`status`,`expire_at`),
  CONSTRAINT `fk_qr_cabinet` FOREIGN KEY (`cabinet_id`) REFERENCES `t_cabinet` (`cabinet_id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `chk_qr_confirm` CHECK ((((`confirm_role` is null) and (`confirm_id` is null)) or ((`confirm_role` is not null) and (`confirm_id` is not null)))),
  CONSTRAINT `chk_qr_expire` CHECK ((`expire_at` > `created_at`)),
  CONSTRAINT `chk_qr_purpose` CHECK ((`purpose` in (_utf8mb4'KIOSK_LOGIN',_utf8mb4'PICKUP'))),
  CONSTRAINT `chk_qr_role` CHECK (((`confirm_role` is null) or (`confirm_role` in (_utf8mb4'USER',_utf8mb4'COURIER')))),
  CONSTRAINT `chk_qr_status` CHECK ((`status` in (_utf8mb4'PENDING',_utf8mb4'CONFIRMED',_utf8mb4'CONSUMED',_utf8mb4'EXPIRED',_utf8mb4'CANCELLED')))
) ENGINE=InnoDB AUTO_INCREMENT=14 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='柜机扫码登录票据（一次性，2 分钟有效）';
-- ----- 表 t_pay_order -----
CREATE TABLE `t_pay_order` (
  `pay_id` int NOT NULL AUTO_INCREMENT COMMENT '支付单ID(PK)',
  `pay_no` varchar(40) NOT NULL COMMENT '商户订单号（唯一）',
  `biz_type` varchar(15) NOT NULL COMMENT '业务类型 OVERTIME/SEND',
  `biz_id` int NOT NULL COMMENT '业务ID（package_id）',
  `user_id` int DEFAULT NULL COMMENT '付款用户ID(FK)',
  `amount` decimal(10,2) NOT NULL COMMENT '金额(元)——服务端快照',
  `provider` varchar(20) NOT NULL DEFAULT 'mock' COMMENT '渠道 mock/alipay_sandbox',
  `provider_label` varchar(20) NOT NULL DEFAULT '模拟支付' COMMENT '中文展示文案',
  `is_mock` tinyint NOT NULL DEFAULT '1' COMMENT '是否模拟渠道 0/1',
  `status` varchar(12) NOT NULL DEFAULT 'PENDING' COMMENT '状态 PENDING/SUCCESS/FAILED/CLOSED',
  `idempotency_key` varchar(80) DEFAULT NULL COMMENT '业务幂等键（唯一）',
  `trade_no` varchar(64) DEFAULT NULL COMMENT '第三方交易号（唯一）',
  `fail_reason` varchar(200) DEFAULT NULL COMMENT '失败/关闭原因',
  `raw_payload` text COMMENT '原始响应摘要（不含密钥）',
  `expire_at` datetime NOT NULL COMMENT '支付单过期时间',
  `paid_at` datetime DEFAULT NULL COMMENT '支付成功时间',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`pay_id`),
  UNIQUE KEY `uk_pay_no` (`pay_no`),
  UNIQUE KEY `uk_pay_idem` (`idempotency_key`),
  UNIQUE KEY `uk_pay_trade_no` (`trade_no`),
  KEY `idx_pay_biz` (`biz_type`,`biz_id`),
  KEY `idx_pay_status` (`status`,`created_at`),
  KEY `idx_pay_user` (`user_id`,`created_at`),
  KEY `idx_pay_provider` (`provider`,`created_at`),
  CONSTRAINT `fk_pay_user` FOREIGN KEY (`user_id`) REFERENCES `t_user` (`user_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `chk_pay_amount` CHECK ((`amount` >= 0)),
  CONSTRAINT `chk_pay_biz` CHECK ((`biz_type` in (_utf8mb4'OVERTIME',_utf8mb4'SEND'))),
  CONSTRAINT `chk_pay_mock` CHECK ((`is_mock` in (0,1))),
  CONSTRAINT `chk_pay_provider` CHECK ((`provider` in (_utf8mb4'mock',_utf8mb4'alipay_sandbox'))),
  CONSTRAINT `chk_pay_status` CHECK ((`status` in (_utf8mb4'PENDING',_utf8mb4'SUCCESS',_utf8mb4'FAILED',_utf8mb4'CLOSED')))
) ENGINE=InnoDB AUTO_INCREMENT=18 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='统一支付单（创新点 4）';
-- ----- 表 t_pay_callback_log -----
CREATE TABLE `t_pay_callback_log` (
  `log_id` int NOT NULL AUTO_INCREMENT COMMENT '日志ID(PK)',
  `pay_id` int DEFAULT NULL COMMENT '关联支付单ID(FK)',
  `pay_no` varchar(40) DEFAULT NULL COMMENT '商户订单号',
  `trade_no` varchar(64) DEFAULT NULL COMMENT '第三方交易号',
  `idem_key` varchar(120) NOT NULL COMMENT '回调幂等键 pay_no:trade_no（唯一）',
  `provider` varchar(20) NOT NULL DEFAULT 'alipay_sandbox' COMMENT '渠道',
  `trade_status` varchar(30) DEFAULT NULL COMMENT '第三方交易状态原文',
  `verify_ok` tinyint NOT NULL DEFAULT '0' COMMENT '验签是否通过 0/1',
  `amount_ok` tinyint NOT NULL DEFAULT '0' COMMENT '金额/订单号核验是否通过 0/1',
  `applied` tinyint NOT NULL DEFAULT '0' COMMENT '是否实际入账 0/1',
  `result` varchar(20) NOT NULL DEFAULT 'IGNORED' COMMENT 'APPLIED/DUPLICATE/VERIFY_FAIL/AMOUNT_MISMATCH/IGNORED',
  `reason` varchar(200) DEFAULT NULL COMMENT '原因',
  `raw_payload` text COMMENT '回调原始参数（已脱敏）',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`log_id`),
  UNIQUE KEY `uk_cb_idem` (`idem_key`),
  KEY `idx_cb_pay` (`pay_id`,`created_at`),
  KEY `idx_cb_result` (`result`,`created_at`)
) ENGINE=InnoDB AUTO_INCREMENT=10 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='支付回调流水（幂等键唯一，防重复入账）';

-- ----- 数据 t_schema_migration -----
INSERT INTO `t_schema_migration` (`filename`,`applied_at`) VALUES ('001_mobile.sql','2026-11-18 19:59:55');
INSERT INTO `t_schema_migration` (`filename`,`applied_at`) VALUES ('002_qr_login.sql','2026-11-18 19:59:55');
INSERT INTO `t_schema_migration` (`filename`,`applied_at`) VALUES ('003_innovations.sql','2026-11-18 19:59:55');
INSERT INTO `t_schema_migration` (`filename`,`applied_at`) VALUES ('003_seed_cabinet_coord.sql','2026-11-18 19:59:55');

-- ----- 数据 t_express_company -----
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (1,'SF','顺丰速运','13029936086','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (2,'YT','圆通速递','13568423203','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (3,'ZTO','中通快递','13590736886','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (4,'YD','韵达快递','13546420526','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (5,'HT','百世汇通','15399251976','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (6,'JD','京东物流','15080763767','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (7,'EMS','中国邮政EMS','18223053497','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (8,'DBL','德邦快递','15649373717','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (9,'ST','申通快递','18188787834','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (10,'ZT','宅急送','15617874880','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (11,'UC','优速快递','18000422361','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (12,'TT','天天快递','13848637969','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (13,'GW','国通快递','18095180510','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (14,'QB','全峰快递','18773917178','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (15,'FN','丰巢自营','18915543276','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (16,'XF','速递易','14793434173','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (17,'RF','如风达','15519599890','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (18,'LB','龙邦速运','18173049996','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (19,'KL','跨越速运','18710820315','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (20,'YS','远成快运','15320088953','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (21,'TD','天地华宇','13070492844','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (22,'MN','民航快递','18022635328','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (23,'CN','中铁快运','18887194977','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (24,'SY','顺邮物流','13619615039','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (25,'HJ','汇强快递','15605492821','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (26,'ZT2','众通快递','13847729848','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (27,'AJ','安捷快递','13760651923','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (28,'FL','飞鸿速运','13282911894','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (29,'XD','迅达快递','14730491337','2026-09-29 22:52:38');
INSERT INTO `t_express_company` (`company_id`,`company_code`,`company_name`,`hotline`,`created_at`) VALUES (30,'HK','恒康物流','13834980468','2026-09-29 22:52:38');

-- ----- 数据 t_user -----
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (1,'卢秀华','15800000001','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (2,'曹芳','15800000002','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (3,'曹平','15800000003','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (4,'李淑兰','18850616547','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (5,'邢莹','13249405105','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (6,'唐荣','17975074027','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (7,'万博','18922459399','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (8,'王建华','13045634847','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (9,'杜秀荣','16617190300','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (10,'柳志强','13628248999','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (11,'王凤英','13851400947','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (12,'牟杨','16417589265','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (13,'周秀云','18633636832','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (14,'杨海燕','15622810865','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (15,'苏颖','13486950237','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (16,'张文','13426932003','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (17,'敖明','18770432403','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (18,'任静','19081077035','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (19,'杨欢','18018495445','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (20,'李玉英','18529881854','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (21,'陈杨','13971523082','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (22,'何秀芳','13536865397','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (23,'王坤','14243328067','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (24,'张丹','17036064505','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (25,'李玉梅','13606946476','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (26,'曾龙','13560695107','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (27,'岑鑫','16277976542','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (28,'马亮','14361076315','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (29,'李晨','13241371327','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (30,'郭秀华','18283258772','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (31,'倪旭','17965213679','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (32,'何兰英','16988739267','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (33,'关晶','19379955502','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (34,'赖凯','15167326631','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (35,'余建华','19116184076','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (36,'马婷婷','13094829318','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (37,'周凤兰','16612420314','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (38,'高霞','17820517449','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (39,'颜建军','15419444333','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (40,'郑晶','16745171835','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (41,'吴慧','15734174349','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (42,'陈兰英','19845715109','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (43,'周婷婷','18331705193','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (44,'刘勇','16256616285','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (45,'陈梅','15691955325','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (46,'杨杰','13076074705','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (47,'宋淑英','14268572501','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (48,'曾磊','19916551713','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (49,'彭杰','17734239343','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (50,'朱兵','19596509310','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (51,'申柳','18931697871','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (52,'郑健','14929833822','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (53,'韦莉','16257370925','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (54,'田想','18973590874','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (55,'郭桂芝','18184199529','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (56,'吴欣','13558023207','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (57,'邓洋','18671951877','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (58,'王波','14821721899','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (59,'张雷','17362851177','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (60,'叶璐','15622547072','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (61,'曾倩','14079752344','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (62,'项杰','16482279189','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (63,'宋玉兰','16468640893','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (64,'岑桂兰','19938079632','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (65,'彭柳','14978829500','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (66,'刁琴','16238022381','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (67,'谭丽','14485280085','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (68,'翟想','18281679582','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (69,'康芳','19607970889','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (70,'霍淑兰','14369770387','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (71,'苏彬','15054178127','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (72,'卢洋','18354115763','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (73,'杨玲','13723198671','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (74,'邓杰','17318022704','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (75,'张丽丽','18910790984','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (76,'陈峰','19432286739','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (77,'宋亮','15063720352','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (78,'王玉','19367094359','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (79,'汪秀珍','13393762822','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (80,'鄢建','13829498716','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (81,'董楠','18183788485','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (82,'胡斌','19324012584','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (83,'孙明','13373591978','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (84,'黄涛','17925219548','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (85,'潘丹','18874042228','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (86,'陈畅','17980266610','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (87,'窦彬','17457085148','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (88,'薛琴','19516334655','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (89,'王桂香','15601377188','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (90,'甘玉梅','19753833479','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (91,'庄杰','17012313851','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (92,'王静','18001120151','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (93,'何琴','14311899145','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (94,'姚丽丽','14801802574','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (95,'张婷','19808003369','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (96,'章晨','15653898875','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (97,'程淑珍','13862395037','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (98,'宋勇','18540654689','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (99,'周秀云','16817017958','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (100,'黄晶','14530436601','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (101,'丁鹏','15570419334','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (102,'蔡玉兰','18063608454','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (103,'甘娟','16937965389','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (104,'周倩','15910133831','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (105,'王云','13804559945','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (106,'王欣','19617098572','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (107,'张荣','14500193876','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (108,'覃丹丹','13942760784','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (109,'杨秀珍','19856862679','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (110,'张艳','19091157716','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (111,'萧宁','18787238412','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (112,'孙敏','14336032933','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (113,'陈雷','13775436749','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (114,'李芳','15168914710','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (115,'李红霞','19137316155','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (116,'管建','14956454450','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (117,'张丹丹','16357251655','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (118,'张雪梅','14502505505','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (119,'张文','16271645850','2026-09-29 22:52:38');
INSERT INTO `t_user` (`user_id`,`name`,`phone`,`register_time`) VALUES (120,'孙丽华','18696541922','2026-09-29 22:52:38');

-- ----- 数据 t_cabinet -----
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (1,'CAB-001','阳光花园小区','39.908722','116.397499','社区柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (2,'CAB-002','碧水蓝天社区','39.914512','116.403871','社区柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (3,'CAB-003','学府路1号院','39.929986','116.389310','社区柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (4,'CAB-004','中央公馆','39.899430','116.414020','社区柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (5,'CAB-005','和谐家园','39.954120','116.352180','校园柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (6,'CAB-006','金桂苑','39.937480','116.460210','园区柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (7,'CAB-007','梧桐里','39.868690','116.379150','商圈柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (8,'CAB-008','滨江世纪城','39.981520','116.403120','社区柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (9,'CAB-009','文苑小区','39.911230','116.453780','社区柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (10,'CAB-010','锦绣华庭','39.882640','116.342160','园区柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (11,'CAB-011','山大软件园','40.006910','116.381220','园区柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (12,'CAB-012','创客大厦','39.925400','116.488150','商圈柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (13,'CAB-013','青年公寓','39.895170','116.436910','商圈柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (14,'CAB-014','云栖小镇','39.969830','116.413560','商圈柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (15,'CAB-015','湖畔名居','39.942330','116.331120','园区柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (16,'CAB-016','香缇雅郡','31.230416','121.473701','商圈柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (17,'CAB-017','龙湖天街','31.235870','121.480920','商圈柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (18,'CAB-018','万科城','31.219640','121.462180','商圈柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (19,'CAB-019','保利花园','31.245210','121.447360','校园柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (20,'CAB-020','绿地之窗','31.207480','121.491530','社区柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (21,'CAB-021','清华园','31.259340','121.521870','商圈柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (22,'CAB-022','明湖小区','31.198820','121.431290','园区柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (23,'CAB-023','翠湖天地','31.240950','121.542460','商圈柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (24,'CAB-024','天悦湾','31.223180','121.412730','商圈柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (25,'CAB-025','江悦府','31.268470','121.469120','园区柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (26,'CAB-026','星河湾','31.191260','121.508940','商圈柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (27,'CAB-027','华润悦府','31.251030','121.436580','商圈柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (28,'CAB-028','中海国际','31.214470','121.531720','园区柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (29,'CAB-029','富力城','31.277950','121.485330','园区柜',24,'NORMAL','2026-09-29 22:52:38');
INSERT INTO `t_cabinet` (`cabinet_id`,`cabinet_code`,`location`,`latitude`,`longitude`,`cabinet_type`,`total_cells`,`status`,`created_at`) VALUES (30,'CAB-030','世茂广场','31.203610','121.452140','校园柜',24,'NORMAL','2026-09-29 22:52:38');

-- ----- 数据 t_courier -----
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (1,1,'E00001','王强','13900000001','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (2,25,'E00002','田刚','14993608606','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (3,17,'E00003','王晨','18423203090','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (4,15,'E00004','周建','19368860464','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (5,6,'E00005','郭刚','13526992519','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (6,22,'E00006','王玉英','16638076376','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (7,15,'E00007','张建国','16230534974','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (8,19,'E00008','王雷','14737178878','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (9,15,'E00009','邱慧','17341787488','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (10,2,'E00010','王桂花','19004223612','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (11,23,'E00011','罗淑珍','15863796995','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (12,27,'E00012','赵艳','13805107739','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (13,25,'E00013','熊龙','13717815543','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (14,30,'E00014','蔡桂香','14763934341','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (15,16,'E00015','张燕','18319599890','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (16,28,'E00016','戴秀英','16304999671','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (17,28,'E00017','翁婷婷','19082031520','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (18,2,'E00018','黄东','18889538704','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (19,20,'E00019','秦文','14844226353','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (20,30,'E00020','朱丽丽','19287871949','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (21,28,'E00021','张凤英','16711961503','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (22,19,'E00022','潘玉华','18054928212','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (23,10,'E00023','贾荣','16729848160','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (24,14,'E00024','陈楠','15192398291','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (25,26,'E00025','王玉华','13894330491','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (26,8,'E00026','周鑫','14723498046','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (27,28,'E00027','朱瑜','17450407285','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (28,14,'E00028','李秀芳','14238040543','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (29,10,'E00029','李玉梅','18920032558','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (30,23,'E00030','屈磊','13081886762','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (31,21,'E00031','李平','19371376304','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (32,22,'E00032','杨秀珍','13639296058','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (33,24,'E00033','高玉梅','19263477235','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (34,23,'E00034','马丽','14860676436','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (35,2,'E00035','祁璐','19656127784','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (36,3,'E00036','韦想','16419549062','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (37,16,'E00037','韩静','17005948085','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (38,19,'E00038','李凤英','16749378825','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (39,7,'E00039','汪玉珍','13930115655','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (40,13,'E00040','王凤兰','13982658444','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (41,1,'E00041','徐桂花','19166795502','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (42,8,'E00042','辛婷','13589657312','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (43,12,'E00043','薛海燕','16775506561','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (44,3,'E00044','胡云','17740658930','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (45,2,'E00045','曹成','14272489099','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (46,20,'E00046','李凤英','13352109734','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (47,24,'E00047','杨岩','13437833450','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (48,13,'E00048','李丽丽','13680609097','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (49,2,'E00049','徐云','19230920866','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (50,30,'E00050','王秀云','13200552356','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (51,12,'E00051','牟桂荣','16656245422','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (52,7,'E00052','王玉','14980653051','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (53,15,'E00053','王玉英','13257432847','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (54,26,'E00054','鞠杰','14013624511','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (55,24,'E00055','李丽华','18958412127','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (56,30,'E00056','区莉','14412488749','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (57,4,'E00057','宾明','17838549501','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (58,26,'E00058','杨晨','18981121766','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (59,22,'E00059','王瑜','17168848422','2026-09-29 22:52:38');
INSERT INTO `t_courier` (`courier_id`,`company_id`,`employee_no`,`name`,`phone`,`created_at`) VALUES (60,8,'E00060','陈佳','17056605341','2026-09-29 22:52:38');

-- ----- 数据 t_cell -----
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (1,1,'A01','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (2,1,'A02','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (3,1,'A03','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (4,1,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (5,1,'A05','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (6,1,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (7,1,'A07','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (8,1,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (9,1,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (10,1,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (11,1,'B03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (12,1,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (13,1,'B05','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (14,1,'B06','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (15,1,'B07','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (16,1,'B08','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (17,1,'C01','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (18,1,'C02','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (19,1,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (20,1,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (21,1,'C05','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (22,1,'C06','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (23,1,'C07','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (24,1,'C08','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (25,2,'A01','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (26,2,'A02','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (27,2,'A03','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (28,2,'A04','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (29,2,'A05','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (30,2,'A06','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (31,2,'A07','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (32,2,'A08','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (33,2,'B01','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (34,2,'B02','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (35,2,'B03','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (36,2,'B04','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (37,2,'B05','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (38,2,'B06','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (39,2,'B07','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (40,2,'B08','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (41,2,'C01','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (42,2,'C02','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (43,2,'C03','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (44,2,'C04','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (45,2,'C05','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (46,2,'C06','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (47,2,'C07','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (48,2,'C08','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (49,3,'A01','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (50,3,'A02','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (51,3,'A03','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (52,3,'A04','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (53,3,'A05','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (54,3,'A06','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (55,3,'A07','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (56,3,'A08','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (57,3,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (58,3,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (59,3,'B03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (60,3,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (61,3,'B05','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (62,3,'B06','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (63,3,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (64,3,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (65,3,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (66,3,'C02','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (67,3,'C03','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (68,3,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (69,3,'C05','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (70,3,'C06','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (71,3,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (72,3,'C08','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (73,4,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (74,4,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (75,4,'A03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (76,4,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (77,4,'A05','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (78,4,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (79,4,'A07','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (80,4,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (81,4,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (82,4,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (83,4,'B03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (84,4,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (85,4,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (86,4,'B06','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (87,4,'B07','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (88,4,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (89,4,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (90,4,'C02','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (91,4,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (92,4,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (93,4,'C05','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (94,4,'C06','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (95,4,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (96,4,'C08','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (97,5,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (98,5,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (99,5,'A03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (100,5,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (101,5,'A05','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (102,5,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (103,5,'A07','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (104,5,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (105,5,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (106,5,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (107,5,'B03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (108,5,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (109,5,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (110,5,'B06','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (111,5,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (112,5,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (113,5,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (114,5,'C02','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (115,5,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (116,5,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (117,5,'C05','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (118,5,'C06','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (119,5,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (120,5,'C08','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (121,6,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (122,6,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (123,6,'A03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (124,6,'A04','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (125,6,'A05','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (126,6,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (127,6,'A07','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (128,6,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (129,6,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (130,6,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (131,6,'B03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (132,6,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (133,6,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (134,6,'B06','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (135,6,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (136,6,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (137,6,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (138,6,'C02','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (139,6,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (140,6,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (141,6,'C05','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (142,6,'C06','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (143,6,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (144,6,'C08','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (145,7,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (146,7,'A02','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (147,7,'A03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (148,7,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (149,7,'A05','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (150,7,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (151,7,'A07','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (152,7,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (153,7,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (154,7,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (155,7,'B03','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (156,7,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (157,7,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (158,7,'B06','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (159,7,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (160,7,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (161,7,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (162,7,'C02','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (163,7,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (164,7,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (165,7,'C05','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (166,7,'C06','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (167,7,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (168,7,'C08','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (169,8,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (170,8,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (171,8,'A03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (172,8,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (173,8,'A05','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (174,8,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (175,8,'A07','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (176,8,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (177,8,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (178,8,'B02','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (179,8,'B03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (180,8,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (181,8,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (182,8,'B06','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (183,8,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (184,8,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (185,8,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (186,8,'C02','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (187,8,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (188,8,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (189,8,'C05','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (190,8,'C06','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (191,8,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (192,8,'C08','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (193,9,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (194,9,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (195,9,'A03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (196,9,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (197,9,'A05','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (198,9,'A06','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (199,9,'A07','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (200,9,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (201,9,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (202,9,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (203,9,'B03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (204,9,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (205,9,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (206,9,'B06','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (207,9,'B07','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (208,9,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (209,9,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (210,9,'C02','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (211,9,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (212,9,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (213,9,'C05','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (214,9,'C06','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (215,9,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (216,9,'C08','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (217,10,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (218,10,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (219,10,'A03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (220,10,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (221,10,'A05','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (222,10,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (223,10,'A07','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (224,10,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (225,10,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (226,10,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (227,10,'B03','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (228,10,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (229,10,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (230,10,'B06','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (231,10,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (232,10,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (233,10,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (234,10,'C02','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (235,10,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (236,10,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (237,10,'C05','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (238,10,'C06','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (239,10,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (240,10,'C08','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (241,11,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (242,11,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (243,11,'A03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (244,11,'A04','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (245,11,'A05','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (246,11,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (247,11,'A07','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (248,11,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (249,11,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (250,11,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (251,11,'B03','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (252,11,'B04','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (253,11,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (254,11,'B06','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (255,11,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (256,11,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (257,11,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (258,11,'C02','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (259,11,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (260,11,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (261,11,'C05','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (262,11,'C06','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (263,11,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (264,11,'C08','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (265,12,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (266,12,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (267,12,'A03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (268,12,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (269,12,'A05','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (270,12,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (271,12,'A07','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (272,12,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (273,12,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (274,12,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (275,12,'B03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (276,12,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (277,12,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (278,12,'B06','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (279,12,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (280,12,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (281,12,'C01','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (282,12,'C02','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (283,12,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (284,12,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (285,12,'C05','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (286,12,'C06','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (287,12,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (288,12,'C08','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (289,13,'A01','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (290,13,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (291,13,'A03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (292,13,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (293,13,'A05','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (294,13,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (295,13,'A07','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (296,13,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (297,13,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (298,13,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (299,13,'B03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (300,13,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (301,13,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (302,13,'B06','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (303,13,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (304,13,'B08','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (305,13,'C01','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (306,13,'C02','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (307,13,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (308,13,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (309,13,'C05','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (310,13,'C06','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (311,13,'C07','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (312,13,'C08','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (313,14,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (314,14,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (315,14,'A03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (316,14,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (317,14,'A05','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (318,14,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (319,14,'A07','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (320,14,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (321,14,'B01','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (322,14,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (323,14,'B03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (324,14,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (325,14,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (326,14,'B06','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (327,14,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (328,14,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (329,14,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (330,14,'C02','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (331,14,'C03','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (332,14,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (333,14,'C05','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (334,14,'C06','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (335,14,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (336,14,'C08','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (337,15,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (338,15,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (339,15,'A03','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (340,15,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (341,15,'A05','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (342,15,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (343,15,'A07','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (344,15,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (345,15,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (346,15,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (347,15,'B03','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (348,15,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (349,15,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (350,15,'B06','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (351,15,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (352,15,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (353,15,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (354,15,'C02','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (355,15,'C03','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (356,15,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (357,15,'C05','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (358,15,'C06','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (359,15,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (360,15,'C08','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (361,16,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (362,16,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (363,16,'A03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (364,16,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (365,16,'A05','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (366,16,'A06','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (367,16,'A07','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (368,16,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (369,16,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (370,16,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (371,16,'B03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (372,16,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (373,16,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (374,16,'B06','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (375,16,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (376,16,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (377,16,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (378,16,'C02','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (379,16,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (380,16,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (381,16,'C05','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (382,16,'C06','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (383,16,'C07','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (384,16,'C08','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (385,17,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (386,17,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (387,17,'A03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (388,17,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (389,17,'A05','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (390,17,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (391,17,'A07','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (392,17,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (393,17,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (394,17,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (395,17,'B03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (396,17,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (397,17,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (398,17,'B06','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (399,17,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (400,17,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (401,17,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (402,17,'C02','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (403,17,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (404,17,'C04','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (405,17,'C05','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (406,17,'C06','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (407,17,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (408,17,'C08','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (409,18,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (410,18,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (411,18,'A03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (412,18,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (413,18,'A05','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (414,18,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (415,18,'A07','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (416,18,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (417,18,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (418,18,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (419,18,'B03','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (420,18,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (421,18,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (422,18,'B06','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (423,18,'B07','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (424,18,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (425,18,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (426,18,'C02','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (427,18,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (428,18,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (429,18,'C05','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (430,18,'C06','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (431,18,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (432,18,'C08','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (433,19,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (434,19,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (435,19,'A03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (436,19,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (437,19,'A05','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (438,19,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (439,19,'A07','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (440,19,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (441,19,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (442,19,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (443,19,'B03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (444,19,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (445,19,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (446,19,'B06','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (447,19,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (448,19,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (449,19,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (450,19,'C02','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (451,19,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (452,19,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (453,19,'C05','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (454,19,'C06','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (455,19,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (456,19,'C08','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (457,20,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (458,20,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (459,20,'A03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (460,20,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (461,20,'A05','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (462,20,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (463,20,'A07','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (464,20,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (465,20,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (466,20,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (467,20,'B03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (468,20,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (469,20,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (470,20,'B06','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (471,20,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (472,20,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (473,20,'C01','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (474,20,'C02','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (475,20,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (476,20,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (477,20,'C05','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (478,20,'C06','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (479,20,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (480,20,'C08','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (481,21,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (482,21,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (483,21,'A03','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (484,21,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (485,21,'A05','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (486,21,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (487,21,'A07','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (488,21,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (489,21,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (490,21,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (491,21,'B03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (492,21,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (493,21,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (494,21,'B06','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (495,21,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (496,21,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (497,21,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (498,21,'C02','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (499,21,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (500,21,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (501,21,'C05','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (502,21,'C06','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (503,21,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (504,21,'C08','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (505,22,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (506,22,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (507,22,'A03','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (508,22,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (509,22,'A05','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (510,22,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (511,22,'A07','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (512,22,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (513,22,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (514,22,'B02','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (515,22,'B03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (516,22,'B04','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (517,22,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (518,22,'B06','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (519,22,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (520,22,'B08','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (521,22,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (522,22,'C02','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (523,22,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (524,22,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (525,22,'C05','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (526,22,'C06','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (527,22,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (528,22,'C08','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (529,23,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (530,23,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (531,23,'A03','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (532,23,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (533,23,'A05','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (534,23,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (535,23,'A07','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (536,23,'A08','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (537,23,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (538,23,'B02','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (539,23,'B03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (540,23,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (541,23,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (542,23,'B06','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (543,23,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (544,23,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (545,23,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (546,23,'C02','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (547,23,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (548,23,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (549,23,'C05','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (550,23,'C06','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (551,23,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (552,23,'C08','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (553,24,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (554,24,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (555,24,'A03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (556,24,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (557,24,'A05','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (558,24,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (559,24,'A07','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (560,24,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (561,24,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (562,24,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (563,24,'B03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (564,24,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (565,24,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (566,24,'B06','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (567,24,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (568,24,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (569,24,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (570,24,'C02','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (571,24,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (572,24,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (573,24,'C05','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (574,24,'C06','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (575,24,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (576,24,'C08','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (577,25,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (578,25,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (579,25,'A03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (580,25,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (581,25,'A05','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (582,25,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (583,25,'A07','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (584,25,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (585,25,'B01','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (586,25,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (587,25,'B03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (588,25,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (589,25,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (590,25,'B06','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (591,25,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (592,25,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (593,25,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (594,25,'C02','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (595,25,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (596,25,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (597,25,'C05','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (598,25,'C06','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (599,25,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (600,25,'C08','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (601,26,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (602,26,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (603,26,'A03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (604,26,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (605,26,'A05','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (606,26,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (607,26,'A07','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (608,26,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (609,26,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (610,26,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (611,26,'B03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (612,26,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (613,26,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (614,26,'B06','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (615,26,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (616,26,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (617,26,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (618,26,'C02','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (619,26,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (620,26,'C04','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (621,26,'C05','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (622,26,'C06','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (623,26,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (624,26,'C08','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (625,27,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (626,27,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (627,27,'A03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (628,27,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (629,27,'A05','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (630,27,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (631,27,'A07','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (632,27,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (633,27,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (634,27,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (635,27,'B03','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (636,27,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (637,27,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (638,27,'B06','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (639,27,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (640,27,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (641,27,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (642,27,'C02','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (643,27,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (644,27,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (645,27,'C05','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (646,27,'C06','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (647,27,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (648,27,'C08','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (649,28,'A01','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (650,28,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (651,28,'A03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (652,28,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (653,28,'A05','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (654,28,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (655,28,'A07','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (656,28,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (657,28,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (658,28,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (659,28,'B03','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (660,28,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (661,28,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (662,28,'B06','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (663,28,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (664,28,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (665,28,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (666,28,'C02','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (667,28,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (668,28,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (669,28,'C05','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (670,28,'C06','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (671,28,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (672,28,'C08','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (673,29,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (674,29,'A02','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (675,29,'A03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (676,29,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (677,29,'A05','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (678,29,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (679,29,'A07','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (680,29,'A08','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (681,29,'B01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (682,29,'B02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (683,29,'B03','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (684,29,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (685,29,'B05','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (686,29,'B06','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (687,29,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (688,29,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (689,29,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (690,29,'C02','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (691,29,'C03','MEDIUM','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (692,29,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (693,29,'C05','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (694,29,'C06','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (695,29,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (696,29,'C08','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (697,30,'A01','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (698,30,'A02','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (699,30,'A03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (700,30,'A04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (701,30,'A05','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (702,30,'A06','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (703,30,'A07','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (704,30,'A08','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (705,30,'B01','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (706,30,'B02','SMALL','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (707,30,'B03','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (708,30,'B04','SMALL','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (709,30,'B05','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (710,30,'B06','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (711,30,'B07','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (712,30,'B08','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (713,30,'C01','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (714,30,'C02','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (715,30,'C03','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (716,30,'C04','MEDIUM','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (717,30,'C05','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (718,30,'C06','LARGE','OCCUPIED');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (719,30,'C07','LARGE','FREE');
INSERT INTO `t_cell` (`cell_id`,`cabinet_id`,`cell_code`,`size_type`,`status`) VALUES (720,30,'C08','LARGE','FREE');

-- ----- 数据 t_pack_recommendation -----
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (1,'两本书','rule',1,'上游错误 HTTP 400','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (2,'两本书','rule',1,'AI 功能已被 AI_ENABLED=0 关闭','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (3,'两本书','rule',1,'返回结构校验失败','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (4,'两本书','rule',1,'上游错误 HTTP 429','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (5,'两本书','rule',1,'上游错误 HTTP 500','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (6,'两本书','rule',1,'返回结构校验失败','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (7,'两本书','rule',1,'网络不可达','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (8,'两本书','rule',1,'调用超时','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (9,'两本书','rule',1,'调用超时','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (10,'一个玻璃杯和两本书','deepseek',0,NULL,'MEDIUM','两本书+玻璃杯体积中等，需留缓冲空间',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (11,'一个玻璃杯和两本书','rule',1,'未配置 DEEPSEEK_API_KEY','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (12,'两节锂电池和一个充电宝','rule',1,'未配置 DEEPSEEK_API_KEY','MEDIUM','无可识别线索，按体积中等估算；但含禁寄/限寄物品，需人工审核后方可收寄',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (13,'书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书书','rule',1,'未配置 DEEPSEEK_API_KEY','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (14,'书','rule',1,'未配置 DEEPSEEK_API_KEY','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (15,'书','rule',1,'未配置 DEEPSEEK_API_KEY','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (16,'书','rule',1,'未配置 DEEPSEEK_API_KEY','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (17,'书','rule',1,'未配置 DEEPSEEK_API_KEY','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (18,'书','rule',1,'未配置 DEEPSEEK_API_KEY','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (19,'书','rule',1,'未配置 DEEPSEEK_API_KEY','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (20,'书','rule',1,'未配置 DEEPSEEK_API_KEY','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (21,'书','rule',1,'未配置 DEEPSEEK_API_KEY','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (22,'书','rule',1,'未配置 DEEPSEEK_API_KEY','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (23,'书','rule',1,'未配置 DEEPSEEK_API_KEY','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (24,'书','rule',1,'未配置 DEEPSEEK_API_KEY','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (25,'书','rule',1,'未配置 DEEPSEEK_API_KEY','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (26,'书','rule',1,'未配置 DEEPSEEK_API_KEY','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (27,'书','rule',1,'未配置 DEEPSEEK_API_KEY','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (28,'书','rule',1,'未配置 DEEPSEEK_API_KEY','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (29,'书','rule',1,'未配置 DEEPSEEK_API_KEY','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (30,'书','rule',1,'未配置 DEEPSEEK_API_KEY','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (31,'书','rule',1,'未配置 DEEPSEEK_API_KEY','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (32,'书','rule',1,'未配置 DEEPSEEK_API_KEY','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (33,'书','rule',1,'未配置 DEEPSEEK_API_KEY','MEDIUM','描述含日常中件物品',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (34,'一个大件家电','deepseek',0,NULL,'LARGE','很大',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (35,'一个充电宝和耳机','deepseek',0,NULL,'SMALL','小件',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (36,'耳机','deepseek',0,NULL,'SMALL','x',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (37,'两本书','deepseek',0,NULL,'MEDIUM','中等',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');
INSERT INTO `t_pack_recommendation` (`recommendation_id`,`description`,`source`,`degraded`,`degraded_reason`,`size_type`,`size_reason`,`elapsed_ms`,`notice`,`created_at`) VALUES (38,'两本书','deepseek',0,NULL,'MEDIUM','中等',0,'结果仅供参考，以快递员/承运商审核为准','2026-11-18 20:00:31');

-- ----- 数据 t_pack_material -----
INSERT INTO `t_pack_material` (`material_id`,`name`,`spec`,`unit`,`stock`,`threshold`,`updated_at`) VALUES (1,'气泡膜','宽 50cm 卷装','卷',12,5,'2026-11-18 20:00:32');
INSERT INTO `t_pack_material` (`material_id`,`name`,`spec`,`unit`,`stock`,`threshold`,`updated_at`) VALUES (2,'5 号纸箱','标准 5 号','个',20,8,'2026-11-18 19:59:55');
INSERT INTO `t_pack_material` (`material_id`,`name`,`spec`,`unit`,`stock`,`threshold`,`updated_at`) VALUES (3,'易碎标签','红色不干胶','张',50,20,'2026-11-18 19:59:55');
INSERT INTO `t_pack_material` (`material_id`,`name`,`spec`,`unit`,`stock`,`threshold`,`updated_at`) VALUES (4,'缠绕膜','宽 30cm 卷装','卷',8,3,'2026-11-18 19:59:55');
INSERT INTO `t_pack_material` (`material_id`,`name`,`spec`,`unit`,`stock`,`threshold`,`updated_at`) VALUES (5,'泡沫板','厚 2cm','块',15,5,'2026-11-18 19:59:55');
INSERT INTO `t_pack_material` (`material_id`,`name`,`spec`,`unit`,`stock`,`threshold`,`updated_at`) VALUES (6,'封箱胶带','宽 4.5cm','卷',10,4,'2026-11-18 19:59:55');

-- ----- 数据 t_package -----
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (1,'RECEIVE','HK061596834874',20,1,NULL,1,13,'MEDIUM','13.80','STORED','549548','2026-09-29 18:33:38','2026-10-02 18:33:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (2,'RECEIVE','YT145454641170',10,1,NULL,1,1,'SMALL','14.31','STORED','878905','2026-09-29 17:02:38','2026-10-02 17:02:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (3,'RECEIVE','YD220498432734',57,2,NULL,1,15,'MEDIUM','12.13','STORED','274653','2026-09-28 23:44:38','2026-09-30 23:44:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (4,'RECEIVE','XF456266768736',15,79,NULL,8,179,'SMALL','11.30','PICKED','065868','2026-08-02 08:04:38','2026-08-04 08:04:38','2026-08-02 21:04:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (5,'RECEIVE','HK795211262819',14,70,NULL,7,159,'MEDIUM','0.22','PICKED','143524','2026-07-06 07:46:38','2026-07-08 07:46:38','2026-07-06 19:46:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (6,'RECEIVE','FN237222546569',4,22,NULL,17,390,'SMALL','7.92','RETURNED','872788','2026-08-06 11:45:38','2026-08-08 11:45:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (7,'RECEIVE','EMS829458916017',52,1,NULL,2,45,'LARGE','0.79','EXPIRED','733855','2026-06-12 23:29:38','2026-06-15 23:29:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (8,'RECEIVE','AJ872713569117',12,1,NULL,24,564,'SMALL','3.97','PICKED','115898','2026-07-16 04:00:38','2026-07-18 04:00:38','2026-07-16 21:00:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (9,'RECEIVE','HJ839057568597',13,111,NULL,9,205,'MEDIUM','0.56','PICKED','923859','2026-06-21 11:41:38','2026-06-23 11:41:38','2026-06-21 12:41:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (10,'RECEIVE','TT403711958471',43,2,NULL,12,270,'SMALL','11.90','PICKED','937696','2026-06-26 20:50:38','2026-06-28 20:50:38','2026-06-27 23:50:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (11,'RECEIVE','RF074035012905',3,20,NULL,24,565,'MEDIUM','19.30','PICKED','524055','2026-09-06 06:28:38','2026-09-09 06:28:38','2026-09-09 04:28:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (12,'RECEIVE','JD747505711226',5,3,NULL,1,17,'MEDIUM','15.11','STORED','379747','2026-09-29 04:49:38','2026-10-01 04:49:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (13,'RECEIVE','MN229487753944',59,107,NULL,16,378,'MEDIUM','2.75','PICKED','195715','2026-06-17 22:56:38','2026-06-20 22:56:38','2026-06-19 16:56:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (14,'RECEIVE','ZT2197211443699',54,22,NULL,12,272,'SMALL','12.34','PICKED','053183','2026-06-08 03:39:38','2026-06-10 03:39:38','2026-06-09 11:39:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (15,'RECEIVE','YS006517544559',19,63,NULL,16,361,'SMALL','4.04','PICKED','209603','2026-08-31 05:39:38','2026-09-02 05:39:38','2026-09-01 12:39:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (16,'RECEIVE','SY544082704251',55,74,NULL,21,481,'SMALL','2.29','PICKED','081043','2026-08-03 21:47:38','2026-08-05 21:47:38','2026-08-04 11:47:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (17,'RECEIVE','QB450311056255',28,41,NULL,29,680,'SMALL','6.05','PICKED','207190','2026-07-02 11:00:38','2026-07-04 11:00:38','2026-07-04 07:00:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (18,'RECEIVE','KL828625509649',38,1,NULL,1,14,'MEDIUM','4.05','EXPIRED','641497','2026-07-30 04:19:38','2026-08-02 04:19:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (19,'RECEIVE','HK040473416464',14,2,NULL,1,16,'MEDIUM','16.84','EXPIRED','293687','2026-09-28 06:14:38','2026-09-30 06:14:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (20,'RECEIVE','YS938157596380',46,2,NULL,1,2,'SMALL','18.58','STORED','618251','2026-09-29 17:24:38','2026-10-02 17:24:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (21,'RECEIVE','YT350350213045',45,76,NULL,13,311,'LARGE','9.65','EXCEPTION','866821','2026-06-01 11:36:38','2026-06-04 11:36:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (22,'RECEIVE','ZT2718688584453',54,25,NULL,21,494,'MEDIUM','12.53','PICKED','587378','2026-08-27 13:14:38','2026-08-30 13:14:38','2026-08-28 04:14:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (23,'RECEIVE','YT715354164714',35,75,NULL,27,638,'MEDIUM','5.62','PICKED','326485','2026-09-09 20:12:38','2026-09-11 20:12:38','2026-09-10 02:12:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (24,'RECEIVE','HJ140468365228',2,78,NULL,21,502,'LARGE','11.75','PICKED','765375','2026-07-15 21:26:38','2026-07-18 21:26:38','2026-07-16 13:26:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (25,'RECEIVE','ZT382132506996',23,103,NULL,28,668,'MEDIUM','17.32','PICKED','672463','2026-08-08 09:42:38','2026-08-11 09:42:38','2026-08-08 20:42:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (26,'RECEIVE','ZT2538727022287',58,28,NULL,27,636,'SMALL','17.59','PICKED','052704','2026-09-22 06:00:38','2026-09-24 06:00:38','2026-09-22 20:00:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (27,'RECEIVE','CN429707778135',11,3,NULL,1,3,'SMALL','14.47','STORED','850991','2026-09-29 08:47:38','2026-10-02 08:47:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (28,'RECEIVE','ZT663999460732',29,63,NULL,17,404,'MEDIUM','16.83','STORED','121657','2026-09-29 10:39:38','2026-10-01 10:39:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (29,'RECEIVE','ZT618813046193',23,101,NULL,4,94,'LARGE','6.44','EXPIRED','205166','2026-07-14 03:28:38','2026-07-17 03:28:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (30,'RECEIVE','FN287044933111',4,69,NULL,24,573,'LARGE','19.18','PICKED','568572','2026-09-24 11:28:38','2026-09-27 11:28:38','2026-09-27 05:28:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (31,'RECEIVE','JD090892552674',5,29,NULL,3,54,'SMALL','19.61','RETURNED','393733','2026-07-15 00:38:38','2026-07-17 00:38:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (32,'RECEIVE','YT367221083592',49,2,NULL,16,373,'MEDIUM','3.69','PICKED','700090','2026-08-17 11:43:38','2026-08-20 11:43:38','2026-08-18 15:43:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (33,'RECEIVE','CN382014380660',11,108,NULL,18,419,'SMALL','1.44','EXCEPTION','352648','2026-09-23 06:10:38','2026-09-25 06:10:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (34,'RECEIVE','ZTO230520214105',36,1,NULL,1,21,'LARGE','9.53','STORED','782116','2026-09-29 13:48:38','2026-10-02 13:48:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (35,'RECEIVE','KL138961665146',38,78,NULL,19,443,'SMALL','2.00','PICKED','927111','2026-07-13 12:38:38','2026-07-16 12:38:38','2026-07-15 05:38:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (36,'RECEIVE','ZTO180366998424',44,67,NULL,15,355,'MEDIUM','2.64','STORED','673692','2026-09-29 05:10:38','2026-10-02 05:10:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (37,'RECEIVE','SF492195048647',41,71,NULL,23,546,'MEDIUM','9.86','EXCEPTION','337367','2026-08-18 16:53:38','2026-08-21 16:53:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (38,'RECEIVE','HJ484991979628',13,16,NULL,14,326,'MEDIUM','7.30','EXCEPTION','762153','2026-08-08 01:08:38','2026-08-11 01:08:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (39,'RECEIVE','YT181424190004',49,88,NULL,17,385,'SMALL','15.53','PICKED','253832','2026-06-24 14:18:38','2026-06-27 14:18:38','2026-06-26 09:18:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (40,'RECEIVE','FN448247240592',4,50,NULL,27,642,'MEDIUM','12.47','PICKED','233187','2026-07-05 12:45:38','2026-07-07 12:45:38','2026-07-06 02:45:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (41,'RECEIVE','SF678754670573',41,33,NULL,26,604,'SMALL','5.28','PICKED','294938','2026-09-20 03:00:38','2026-09-22 03:00:38','2026-09-20 22:00:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (42,'RECEIVE','HK146660363504',20,26,NULL,11,252,'SMALL','12.42','STORED','466088','2026-09-29 18:16:38','2026-10-02 18:16:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (43,'RECEIVE','HK557787881875',50,51,NULL,7,151,'SMALL','16.85','EXPIRED','502646','2026-08-05 04:31:38','2026-08-08 04:31:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (44,'RECEIVE','RF015681364136',3,108,NULL,11,260,'MEDIUM','1.79','PICKED','870112','2026-08-18 03:37:38','2026-08-20 03:37:38','2026-08-19 18:37:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (45,'RECEIVE','AJ369707893872',12,82,NULL,25,593,'MEDIUM','4.92','PICKED','580008','2026-06-29 15:27:38','2026-07-01 15:27:38','2026-07-01 05:27:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (46,'RECEIVE','HK986772229566',56,84,NULL,20,458,'SMALL','5.42','PICKED','397710','2026-07-29 13:55:38','2026-08-01 13:55:38','2026-07-31 01:55:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (47,'RECEIVE','GW357869395845',48,31,NULL,4,86,'MEDIUM','1.95','STORED','938988','2026-09-29 15:18:38','2026-10-02 15:18:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (48,'RECEIVE','AJ896759641909',12,85,NULL,7,153,'SMALL','15.15','PICKED','089990','2026-09-14 12:38:38','2026-09-17 12:38:38','2026-09-16 12:38:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (49,'RECEIVE','SY208545972901',55,74,NULL,30,706,'SMALL','11.52','EXCEPTION','318454','2026-08-14 17:32:38','2026-08-16 17:32:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (50,'RECEIVE','MN274433729601',59,85,NULL,15,344,'SMALL','17.48','PICKED','034779','2026-06-15 07:04:38','2026-06-17 07:04:38','2026-06-15 21:04:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (51,'RECEIVE','FL813515878017',21,15,NULL,20,471,'MEDIUM','17.94','PICKED','836454','2026-08-30 13:00:38','2026-09-02 13:00:38','2026-09-01 08:00:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (52,'RECEIVE','YT818479067425',18,44,NULL,4,78,'SMALL','13.61','PICKED','648283','2026-08-28 03:19:38','2026-08-31 03:19:38','2026-08-30 20:19:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (53,'RECEIVE','ZT386360089135',23,98,NULL,18,423,'MEDIUM','17.82','STORED','687100','2026-09-29 06:09:38','2026-10-02 06:09:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (54,'RECEIVE','YS092483142041',46,100,NULL,17,395,'SMALL','15.82','PICKED','712019','2026-09-04 03:18:38','2026-09-06 03:18:38','2026-09-06 01:18:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (55,'RECEIVE','SF064029441431',1,18,NULL,2,29,'SMALL','13.86','EXCEPTION','181550','2026-09-12 18:17:38','2026-09-15 18:17:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (56,'RECEIVE','YS295974881119',46,88,NULL,25,582,'SMALL','3.70','PICKED','499225','2026-08-06 19:35:38','2026-08-08 19:35:38','2026-08-06 21:35:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (57,'RECEIVE','ZT217932963556',29,3,NULL,1,18,'MEDIUM','9.12','EXPIRED','055856','2026-08-05 20:52:38','2026-08-08 20:52:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:38');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (58,'RECEIVE','TT347128651681',51,32,NULL,5,111,'MEDIUM','1.74','PICKED','916866','2026-07-19 05:26:38','2026-07-21 05:26:38','2026-07-21 01:26:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (59,'RECEIVE','DBL875438658818',42,77,NULL,27,635,'SMALL','8.48','EXCEPTION','893513','2026-09-07 05:16:38','2026-09-09 05:16:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (60,'RECEIVE','YT510734043418',35,22,NULL,18,426,'MEDIUM','17.61','PICKED','316212','2026-07-09 00:47:38','2026-07-11 00:47:38','2026-07-09 02:47:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (61,'RECEIVE','QB784671908433',24,45,NULL,4,77,'SMALL','19.58','STORED','123380','2026-09-29 09:46:38','2026-10-01 09:46:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (62,'RECEIVE','SY537660773231',55,49,NULL,21,504,'LARGE','4.72','EXCEPTION','692020','2026-06-24 05:47:38','2026-06-27 05:47:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (63,'RECEIVE','TT768086940689',51,26,NULL,7,146,'SMALL','19.28','STORED','860874','2026-09-29 04:10:38','2026-10-01 04:10:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (64,'RECEIVE','ZT600006336188',23,106,NULL,10,221,'SMALL','14.25','EXCEPTION','723199','2026-07-31 14:42:38','2026-08-02 14:42:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (65,'RECEIVE','TD441562251884',31,37,NULL,26,614,'MEDIUM','7.47','PICKED','484696','2026-06-07 03:32:38','2026-06-09 03:32:38','2026-06-09 01:32:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (66,'RECEIVE','YS547602178147',19,110,NULL,25,578,'SMALL','5.67','PICKED','905977','2026-06-14 12:50:38','2026-06-17 12:50:38','2026-06-15 23:50:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (67,'RECEIVE','DBL738979408264',42,1,NULL,16,370,'SMALL','18.06','PICKED','508657','2026-07-18 04:15:38','2026-07-20 04:15:38','2026-07-18 18:15:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (68,'RECEIVE','XF511452258698',37,45,NULL,17,401,'MEDIUM','10.82','PICKED','448441','2026-08-29 07:50:38','2026-08-31 07:50:38','2026-08-31 03:50:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (69,'RECEIVE','YT513845425192',35,70,NULL,12,282,'MEDIUM','9.74','RETURNED','902257','2026-08-11 07:13:38','2026-08-14 07:13:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (70,'RECEIVE','FN909550869672',7,51,NULL,30,707,'SMALL','15.09','PICKED','735199','2026-06-20 08:50:38','2026-06-22 08:50:38','2026-06-21 00:50:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (71,'RECEIVE','MN824905216876',6,83,NULL,2,28,'SMALL','12.58','PICKED','142974','2026-06-27 19:27:38','2026-06-30 19:27:38','2026-06-30 09:27:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (72,'RECEIVE','FN299344223395',4,98,NULL,7,149,'SMALL','4.04','PICKED','310511','2026-09-19 16:08:38','2026-09-22 16:08:38','2026-09-21 05:08:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (73,'RECEIVE','ZT755502377419',23,45,NULL,20,478,'LARGE','16.29','EXPIRED','158748','2026-07-17 17:24:38','2026-07-19 17:24:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (74,'RECEIVE','HK544152879205',56,53,NULL,3,67,'MEDIUM','12.86','EXPIRED','432761','2026-09-13 20:21:38','2026-09-15 20:21:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (75,'RECEIVE','SY425542962044',33,32,NULL,24,554,'SMALL','1.34','PICKED','465197','2026-08-29 04:27:38','2026-08-31 04:27:38','2026-08-29 23:27:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (76,'RECEIVE','JD122872288918',5,22,NULL,25,596,'MEDIUM','19.02','PICKED','581637','2026-06-22 10:52:38','2026-06-24 10:52:38','2026-06-23 02:52:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (77,'RECEIVE','JD499500567625',5,110,NULL,7,155,'SMALL','12.22','STORED','284240','2026-09-29 04:26:38','2026-10-01 04:26:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (78,'RECEIVE','JD374305427241',5,68,NULL,23,544,'MEDIUM','3.21','PICKED','909698','2026-09-23 17:50:38','2026-09-25 17:50:38','2026-09-25 14:50:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (79,'RECEIVE','ZT849278908516',23,90,NULL,18,431,'LARGE','18.27','PICKED','873072','2026-07-20 12:12:38','2026-07-23 12:12:38','2026-07-22 12:12:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (80,'RECEIVE','DBL918304370091',26,30,NULL,8,188,'MEDIUM','4.22','PICKED','909198','2026-08-21 06:17:38','2026-08-23 06:17:38','2026-08-22 01:17:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (81,'RECEIVE','FL697018281982',27,28,NULL,15,357,'LARGE','15.51','PICKED','466826','2026-06-13 18:03:38','2026-06-16 18:03:38','2026-06-14 13:03:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (82,'RECEIVE','TT949223537770',51,107,NULL,14,320,'SMALL','5.51','PICKED','534539','2026-09-09 16:12:38','2026-09-11 16:12:38','2026-09-10 10:12:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (83,'RECEIVE','HK256054001285',50,2,NULL,1,22,'LARGE','16.23','STORED','033993','2026-09-29 14:08:38','2026-10-02 14:08:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (84,'RECEIVE','FL408029150421',16,97,NULL,12,268,'SMALL','18.74','PICKED','994546','2026-09-10 15:42:38','2026-09-13 15:42:38','2026-09-11 03:42:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (85,'RECEIVE','AJ260267080015',12,6,NULL,10,224,'SMALL','5.86','PICKED','184652','2026-09-01 10:20:38','2026-09-03 10:20:38','2026-09-01 16:20:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (86,'RECEIVE','DBL825461763060',26,21,NULL,21,487,'SMALL','7.29','PICKED','557884','2026-09-07 18:37:38','2026-09-09 18:37:38','2026-09-08 15:37:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (87,'RECEIVE','FL678530063439',16,25,NULL,23,531,'SMALL','14.18','EXPIRED','532852','2026-09-12 02:07:38','2026-09-15 02:07:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (88,'RECEIVE','YT653480627882',10,85,NULL,7,157,'MEDIUM','12.06','PICKED','172145','2026-07-18 00:59:38','2026-07-20 00:59:38','2026-07-18 13:59:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (89,'RECEIVE','MN470635721092',6,55,NULL,12,279,'MEDIUM','13.05','PICKED','554818','2026-08-29 03:18:38','2026-08-31 03:18:38','2026-08-29 05:18:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (90,'RECEIVE','SY952615897158',33,85,NULL,25,583,'SMALL','10.64','STORED','279518','2026-09-29 14:32:38','2026-10-01 14:32:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (91,'RECEIVE','DBL796619271469',60,58,NULL,30,701,'SMALL','6.66','EXPIRED','338061','2026-07-06 11:04:38','2026-07-09 11:04:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (92,'RECEIVE','HK897979076400',56,113,NULL,21,483,'SMALL','13.35','STORED','581489','2026-09-29 16:02:38','2026-10-01 16:02:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (93,'RECEIVE','DBL755379029313',60,39,NULL,8,185,'MEDIUM','10.65','PICKED','685409','2026-07-26 01:03:38','2026-07-28 01:03:38','2026-07-27 21:03:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (94,'RECEIVE','CN877494576083',30,3,NULL,7,158,'MEDIUM','2.79','STORED','134069','2026-09-29 10:43:38','2026-10-01 10:43:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (95,'RECEIVE','ZT2216765546228',58,10,NULL,2,31,'SMALL','15.75','PICKED','563228','2026-08-03 12:03:38','2026-08-06 12:03:38','2026-08-04 03:03:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (96,'RECEIVE','HK680168698890',50,60,NULL,22,520,'MEDIUM','5.52','EXPIRED','736820','2026-06-23 12:27:38','2026-06-26 12:27:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (97,'RECEIVE','QB074744611691',24,34,NULL,1,9,'SMALL','10.70','PICKED','208668','2026-08-25 00:17:38','2026-08-27 00:17:38','2026-08-26 19:17:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (98,'RECEIVE','ZT2108264986115',25,33,NULL,2,32,'SMALL','8.00','PICKED','169162','2026-07-08 00:43:38','2026-07-10 00:43:38','2026-07-08 06:43:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (99,'RECEIVE','MN322683541584',59,55,NULL,18,414,'SMALL','17.77','PICKED','453295','2026-08-25 17:45:38','2026-08-28 17:45:38','2026-08-28 09:45:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (100,'RECEIVE','MN272890102935',6,88,NULL,9,197,'SMALL','1.49','PICKED','134496','2026-08-30 05:59:38','2026-09-02 05:59:38','2026-08-31 02:59:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (101,'RECEIVE','DBL067478283924',26,108,NULL,13,294,'SMALL','16.75','PICKED','669880','2026-09-01 03:59:38','2026-09-03 03:59:38','2026-09-02 17:59:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (102,'RECEIVE','YD201524709522',57,104,NULL,10,223,'SMALL','19.70','EXCEPTION','286754','2026-09-28 09:34:38','2026-10-01 09:34:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (103,'RECEIVE','YT951127399976',49,7,NULL,16,362,'SMALL','13.85','PICKED','996369','2026-08-20 01:13:38','2026-08-23 01:13:38','2026-08-22 18:13:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (104,'RECEIVE','MN073046056962',59,15,NULL,10,229,'MEDIUM','7.61','PICKED','618409','2026-07-17 02:22:38','2026-07-20 02:22:38','2026-07-18 09:22:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (105,'RECEIVE','ZT497463854582',23,48,NULL,29,686,'MEDIUM','18.92','PICKED','467752','2026-08-12 02:32:38','2026-08-15 02:32:38','2026-08-14 05:32:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (106,'RECEIVE','HK534854635272',50,29,NULL,22,522,'MEDIUM','8.00','EXPIRED','308462','2026-08-19 08:57:38','2026-08-21 08:57:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (107,'RECEIVE','ZT919017465260',23,5,NULL,15,347,'SMALL','19.59','EXCEPTION','862332','2026-06-03 03:47:38','2026-06-05 03:47:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (108,'RECEIVE','JD103674572035',5,35,NULL,15,339,'SMALL','17.91','STORED','212966','2026-09-29 05:04:38','2026-10-02 05:04:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (109,'RECEIVE','YS225675008037',19,79,NULL,17,407,'LARGE','13.14','PICKED','314513','2026-07-08 12:21:38','2026-07-10 12:21:38','2026-07-10 03:21:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (110,'RECEIVE','YT798720308775',18,64,NULL,10,227,'SMALL','3.75','EXPIRED','103894','2026-08-05 15:50:38','2026-08-08 15:50:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (111,'RECEIVE','FN694232575194',9,27,NULL,28,649,'SMALL','14.89','STORED','180127','2026-09-29 14:07:38','2026-10-01 14:07:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (112,'RECEIVE','HJ092915017417',2,109,NULL,13,299,'SMALL','10.47','PICKED','130428','2026-06-26 05:50:38','2026-06-28 05:50:38','2026-06-28 04:50:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (113,'RECEIVE','CN988420916365',34,102,NULL,20,461,'SMALL','18.57','PICKED','094163','2026-06-10 19:31:38','2026-06-12 19:31:38','2026-06-11 23:31:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (114,'RECEIVE','QB483382115019',28,92,NULL,29,688,'MEDIUM','5.07','PICKED','221835','2026-09-03 11:54:38','2026-09-05 11:54:38','2026-09-04 03:54:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (115,'RECEIVE','ZT705033082092',23,62,NULL,23,536,'SMALL','0.58','STORED','343810','2026-09-29 20:18:38','2026-10-02 20:18:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (116,'RECEIVE','YT210256447888',45,105,NULL,22,516,'SMALL','6.01','STORED','406674','2026-09-29 19:56:38','2026-10-02 19:56:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (117,'RECEIVE','HJ216626592178',13,98,NULL,12,288,'LARGE','4.55','EXPIRED','292733','2026-09-07 07:54:38','2026-09-09 07:54:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (118,'RECEIVE','YT524992632466',45,29,NULL,29,685,'MEDIUM','5.86','EXCEPTION','889774','2026-08-13 08:52:38','2026-08-15 08:52:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (119,'RECEIVE','FL620931576224',16,81,NULL,4,75,'SMALL','12.54','PICKED','225923','2026-06-11 12:28:38','2026-06-14 12:28:38','2026-06-12 21:28:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (120,'RECEIVE','FL036588370190',16,17,NULL,19,446,'MEDIUM','6.98','PICKED','827976','2026-06-04 23:02:38','2026-06-06 23:02:38','2026-06-06 04:02:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (121,'RECEIVE','MN987431609683',32,102,NULL,12,287,'LARGE','6.08','PICKED','629353','2026-07-22 13:02:38','2026-07-25 13:02:38','2026-07-23 16:02:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (122,'RECEIVE','HK956420152669',14,4,NULL,17,388,'SMALL','10.21','PICKED','340878','2026-09-01 06:02:38','2026-09-04 06:02:38','2026-09-03 21:02:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (123,'RECEIVE','ZT2967414037355',54,25,NULL,14,334,'LARGE','5.10','PICKED','949000','2026-06-26 19:41:38','2026-06-28 19:41:38','2026-06-27 22:41:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (124,'RECEIVE','TT591280396112',51,3,NULL,1,23,'LARGE','2.45','STORED','018390','2026-09-29 11:54:38','2026-10-01 11:54:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (125,'RECEIVE','HJ698736127108',2,8,NULL,29,676,'SMALL','16.10','PICKED','031350','2026-08-17 22:27:38','2026-08-20 22:27:38','2026-08-19 22:27:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (126,'RECEIVE','SY339930440533',47,70,NULL,9,207,'MEDIUM','14.54','EXPIRED','338952','2026-06-26 06:36:38','2026-06-29 06:36:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (127,'RECEIVE','ZT2899927626437',54,96,NULL,7,150,'SMALL','18.84','PICKED','491635','2026-07-13 04:01:38','2026-07-16 04:01:38','2026-07-13 12:01:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (128,'RECEIVE','SY582876683695',47,80,NULL,23,529,'SMALL','1.56','PICKED','844635','2026-08-08 05:53:38','2026-08-10 05:53:38','2026-08-10 02:53:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (129,'RECEIVE','SY464669561377',55,19,NULL,30,718,'LARGE','13.46','EXPIRED','158019','2026-08-03 00:56:38','2026-08-05 00:56:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (130,'RECEIVE','FL544350534788',16,87,NULL,4,76,'SMALL','1.34','PICKED','149480','2026-08-04 03:17:38','2026-08-07 03:17:38','2026-08-04 15:17:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (131,'RECEIVE','HJ589597468961',13,41,NULL,14,313,'SMALL','18.44','PICKED','374780','2026-07-17 05:37:38','2026-07-19 05:37:38','2026-07-18 01:37:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (132,'RECEIVE','YD498897558264',57,65,NULL,21,493,'MEDIUM','2.36','PICKED','073647','2026-07-01 13:40:38','2026-07-04 13:40:38','2026-07-04 04:40:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (133,'RECEIVE','DBL021937631711',26,11,NULL,12,275,'SMALL','1.80','PICKED','244437','2026-09-01 21:16:38','2026-09-04 21:16:38','2026-09-02 07:16:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (134,'RECEIVE','YT889528513174',35,19,NULL,9,194,'SMALL','13.02','PICKED','602173','2026-07-15 11:03:38','2026-07-17 11:03:38','2026-07-16 23:03:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (135,'RECEIVE','AJ388603431859',12,29,NULL,20,477,'LARGE','10.13','RETURNED','927212','2026-08-27 18:45:38','2026-08-29 18:45:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (136,'RECEIVE','SF827370154853',1,111,NULL,23,549,'LARGE','17.87','STORED','835665','2026-09-29 18:31:38','2026-10-02 18:31:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (137,'RECEIVE','YT911442223217',45,59,NULL,2,42,'MEDIUM','8.54','EXPIRED','547580','2026-06-06 18:42:38','2026-06-09 18:42:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (138,'RECEIVE','EMS500591746825',39,119,NULL,17,408,'LARGE','6.53','RETURNED','719700','2026-08-08 08:59:38','2026-08-10 08:59:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (139,'RECEIVE','YS751749787018',46,12,NULL,8,189,'LARGE','13.42','PICKED','576746','2026-06-19 04:06:38','2026-06-22 04:06:38','2026-06-19 21:06:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (140,'RECEIVE','FL576655689272',17,8,NULL,20,473,'MEDIUM','8.77','STORED','623947','2026-09-29 11:26:38','2026-10-02 11:26:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (141,'RECEIVE','HK462722797770',56,102,NULL,7,160,'MEDIUM','8.64','PICKED','178745','2026-06-24 22:22:38','2026-06-26 22:22:38','2026-06-26 11:22:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (142,'RECEIVE','CN699842273132',11,69,NULL,16,383,'LARGE','19.23','EXPIRED','864222','2026-06-06 21:32:38','2026-06-08 21:32:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (143,'RECEIVE','HJ029726001003',13,105,NULL,5,115,'MEDIUM','6.03','PICKED','432580','2026-07-30 03:17:38','2026-08-01 03:17:38','2026-07-30 12:17:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (144,'RECEIVE','GW298694509150',40,66,NULL,25,585,'SMALL','1.42','EXCEPTION','953951','2026-06-30 07:46:38','2026-07-02 07:46:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (145,'RECEIVE','TT331247252955',43,120,NULL,11,244,'SMALL','12.88','STORED','069739','2026-09-29 01:17:38','2026-10-01 01:17:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (146,'RECEIVE','YT835538599451',45,26,NULL,19,450,'MEDIUM','14.44','STORED','958782','2026-09-29 06:47:38','2026-10-02 06:47:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (147,'RECEIVE','SF396877211098',1,4,NULL,9,198,'SMALL','6.07','EXPIRED','838631','2026-08-17 15:11:38','2026-08-19 15:11:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (148,'RECEIVE','FN890816682846',7,115,NULL,18,428,'MEDIUM','14.78','RETURNED','585106','2026-09-01 10:08:38','2026-09-04 10:08:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (149,'RECEIVE','FN760498640830',4,38,NULL,26,618,'MEDIUM','10.53','EXPIRED','744683','2026-06-18 17:33:38','2026-06-21 17:33:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (150,'RECEIVE','ZT2641438606881',54,91,NULL,8,187,'MEDIUM','19.06','PICKED','585918','2026-07-19 06:20:38','2026-07-21 06:20:38','2026-07-20 01:20:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (151,'RECEIVE','YT612563628890',49,76,NULL,7,168,'LARGE','3.48','STORED','253314','2026-09-29 04:59:38','2026-10-01 04:59:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (152,'RECEIVE','YS167619079421',46,94,NULL,28,656,'SMALL','14.96','PICKED','647575','2026-09-16 04:57:38','2026-09-19 04:57:38','2026-09-18 05:57:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (153,'RECEIVE','MN509689979812',59,85,NULL,28,672,'LARGE','9.53','STORED','629180','2026-09-29 02:05:38','2026-10-01 02:05:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (154,'RECEIVE','XF282591773052',15,37,NULL,8,180,'SMALL','3.67','PICKED','059922','2026-08-21 10:38:38','2026-08-23 10:38:38','2026-08-21 18:38:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (155,'RECEIVE','YT655649107549',18,33,NULL,13,293,'SMALL','6.49','STORED','215676','2026-09-29 11:09:38','2026-10-01 11:09:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (156,'RECEIVE','TT087741993688',43,21,NULL,20,457,'SMALL','3.61','PICKED','813547','2026-06-24 07:58:38','2026-06-26 07:58:38','2026-06-24 08:58:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (157,'RECEIVE','ZTO244681131554',36,91,NULL,6,124,'SMALL','8.69','EXCEPTION','556629','2026-08-25 17:12:38','2026-08-28 17:12:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (158,'RECEIVE','CN626280016094',34,59,NULL,26,608,'SMALL','13.54','PICKED','045160','2026-07-15 13:23:38','2026-07-18 13:23:38','2026-07-16 23:23:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (159,'RECEIVE','TT861987830761',43,18,NULL,16,374,'MEDIUM','12.25','PICKED','174255','2026-06-30 12:59:38','2026-07-02 12:59:38','2026-06-30 16:59:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (160,'RECEIVE','TT224863733288',51,104,NULL,14,317,'SMALL','2.58','STORED','245655','2026-09-29 04:44:38','2026-10-01 04:44:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (161,'RECEIVE','HK207974551564',14,37,NULL,19,442,'SMALL','7.47','PICKED','885746','2026-08-01 18:50:38','2026-08-03 18:50:38','2026-08-03 02:50:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (162,'RECEIVE','FL750781264612',21,79,NULL,26,620,'MEDIUM','9.05','STORED','276974','2026-09-29 01:16:38','2026-10-02 01:16:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (163,'RECEIVE','SY367770855139',47,85,NULL,5,113,'MEDIUM','6.20','PICKED','192423','2026-06-12 19:56:38','2026-06-14 19:56:38','2026-06-14 01:56:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (164,'RECEIVE','YS808058446210',46,99,NULL,29,689,'MEDIUM','19.29','PICKED','682964','2026-09-26 10:04:38','2026-09-28 10:04:38','2026-09-27 14:04:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (165,'RECEIVE','KL358847642421',22,57,NULL,16,381,'LARGE','14.03','EXPIRED','470382','2026-06-14 08:07:38','2026-06-17 08:07:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (166,'RECEIVE','AJ991470300504',12,119,NULL,13,295,'SMALL','13.62','STORED','284948','2026-09-29 16:45:38','2026-10-01 16:45:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (167,'RECEIVE','YT510142187014',49,40,NULL,5,112,'MEDIUM','1.50','PICKED','447050','2026-08-26 15:24:38','2026-08-29 15:24:38','2026-08-27 05:24:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (168,'RECEIVE','ZT979096103710',29,80,NULL,11,251,'SMALL','1.86','STORED','761806','2026-09-29 01:43:38','2026-10-02 01:43:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (169,'RECEIVE','DBL105332069255',60,47,NULL,22,514,'SMALL','5.47','EXCEPTION','550824','2026-09-02 03:50:38','2026-09-05 03:50:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:39');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (170,'RECEIVE','KL073953976836',22,95,NULL,29,674,'SMALL','1.27','EXPIRED','261983','2026-08-09 23:58:38','2026-08-11 23:58:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (171,'RECEIVE','KL271339070382',22,76,NULL,28,664,'MEDIUM','16.40','PICKED','006612','2026-09-18 04:11:38','2026-09-20 04:11:38','2026-09-18 19:11:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (172,'RECEIVE','QB704701444583',28,32,NULL,15,337,'SMALL','10.54','PICKED','117884','2026-08-13 04:59:38','2026-08-15 04:59:38','2026-08-15 02:59:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (173,'RECEIVE','ZT2868090879794',54,104,NULL,24,557,'SMALL','6.92','PICKED','375267','2026-09-17 19:01:38','2026-09-19 19:01:38','2026-09-19 10:01:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (174,'RECEIVE','FL885979714759',16,84,NULL,8,178,'SMALL','8.29','STORED','105226','2026-09-29 21:46:38','2026-10-02 21:46:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (175,'RECEIVE','EMS293364005582',39,73,NULL,13,305,'MEDIUM','16.67','STORED','729837','2026-09-29 05:43:38','2026-10-02 05:43:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (176,'RECEIVE','HK985864595281',20,29,NULL,20,464,'SMALL','1.02','PICKED','171640','2026-06-30 09:49:38','2026-07-02 09:49:38','2026-07-01 05:49:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (177,'RECEIVE','FN310583793695',9,24,NULL,17,406,'LARGE','4.04','PICKED','292460','2026-08-27 11:09:38','2026-08-29 11:09:38','2026-08-28 09:09:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (178,'RECEIVE','YS734431733192',19,120,NULL,4,96,'LARGE','0.39','PICKED','018712','2026-08-25 17:01:38','2026-08-27 17:01:38','2026-08-27 02:01:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (179,'RECEIVE','FL401539107396',27,14,NULL,12,281,'MEDIUM','14.69','EXPIRED','079107','2026-07-08 17:36:38','2026-07-11 17:36:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (180,'RECEIVE','JD786385579321',5,34,NULL,24,562,'SMALL','14.36','PICKED','808204','2026-06-18 10:03:38','2026-06-21 10:03:38','2026-06-19 03:03:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (181,'RECEIVE','YS890617260381',19,92,NULL,24,567,'MEDIUM','6.33','PICKED','585134','2026-06-10 08:11:38','2026-06-13 08:11:38','2026-06-12 16:11:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (182,'RECEIVE','TT420209978757',51,71,NULL,16,376,'MEDIUM','19.85','PICKED','986381','2026-07-05 23:22:38','2026-07-08 23:22:38','2026-07-08 07:22:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (183,'RECEIVE','ZTO463960122599',36,16,NULL,13,290,'SMALL','6.34','PICKED','257340','2026-06-24 01:52:38','2026-06-27 01:52:38','2026-06-24 07:52:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (184,'RECEIVE','FL582342092482',16,116,NULL,6,137,'MEDIUM','1.70','RETURNED','596481','2026-08-17 01:16:38','2026-08-19 01:16:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (185,'RECEIVE','TT111825824146',51,104,NULL,8,190,'LARGE','0.80','STORED','290031','2026-09-29 03:27:38','2026-10-01 03:27:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (186,'RECEIVE','MN703149264386',6,53,NULL,13,289,'SMALL','1.58','EXCEPTION','458590','2026-08-11 05:46:38','2026-08-14 05:46:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (187,'RECEIVE','ZTO472494768941',44,86,NULL,3,68,'MEDIUM','14.49','RETURNED','360894','2026-08-16 23:51:38','2026-08-18 23:51:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (188,'RECEIVE','KL198418063359',22,80,NULL,10,225,'SMALL','1.34','PICKED','015496','2026-07-19 09:08:38','2026-07-22 09:08:38','2026-07-20 18:08:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (189,'RECEIVE','KL347983179293',38,61,NULL,30,705,'SMALL','0.69','STORED','210403','2026-09-29 13:00:38','2026-10-02 13:00:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (190,'RECEIVE','YS455456925703',19,45,NULL,2,38,'MEDIUM','11.40','PICKED','227178','2026-07-25 12:28:38','2026-07-27 12:28:38','2026-07-27 03:28:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (191,'RECEIVE','HJ719959175592',13,4,NULL,17,397,'MEDIUM','14.77','PICKED','518151','2026-08-01 14:49:38','2026-08-04 14:49:38','2026-08-02 03:49:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (192,'RECEIVE','SF930935089508',1,118,NULL,21,491,'SMALL','8.89','PICKED','857876','2026-08-31 12:00:38','2026-09-02 12:00:38','2026-08-31 15:00:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (193,'RECEIVE','FN560117017952',7,80,NULL,13,306,'MEDIUM','19.36','PICKED','404172','2026-09-29 09:19:38','2026-10-02 09:19:38','2026-09-29 21:52:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (194,'RECEIVE','ZTO326795617134',44,21,NULL,7,152,'SMALL','7.20','PICKED','943316','2026-08-11 05:39:38','2026-08-13 05:39:38','2026-08-11 14:39:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (195,'RECEIVE','XF954421102684',37,97,NULL,23,541,'MEDIUM','2.22','PICKED','230203','2026-07-14 18:21:38','2026-07-16 18:21:38','2026-07-16 02:21:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (196,'RECEIVE','YT082414167639',10,117,NULL,2,28,'SMALL','4.45','EXPIRED','266255','2026-09-21 10:05:38','2026-09-23 10:05:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (197,'RECEIVE','YT876029415480',18,18,NULL,5,118,'LARGE','0.10','STORED','595028','2026-09-29 03:13:38','2026-10-01 03:13:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (198,'RECEIVE','ZT290529092622',23,48,NULL,27,641,'MEDIUM','17.78','PICKED','802510','2026-08-26 19:20:38','2026-08-28 19:20:38','2026-08-27 18:20:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (199,'RECEIVE','DBL395974189079',60,111,NULL,24,572,'MEDIUM','7.89','PICKED','647204','2026-08-14 10:38:38','2026-08-17 10:38:38','2026-08-14 22:38:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (200,'RECEIVE','FL683261025096',16,117,NULL,13,304,'MEDIUM','7.45','EXPIRED','663063','2026-07-11 21:00:38','2026-07-13 21:00:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (201,'RECEIVE','FL199416550377',17,11,NULL,30,719,'LARGE','6.20','PICKED','913955','2026-08-21 02:09:38','2026-08-23 02:09:38','2026-08-22 07:09:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (202,'RECEIVE','YT687748058281',18,83,NULL,8,169,'SMALL','2.44','RETURNED','169412','2026-06-06 18:26:38','2026-06-08 18:26:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (203,'RECEIVE','RF442763938202',3,2,NULL,21,495,'MEDIUM','2.24','PICKED','580390','2026-07-09 18:09:38','2026-07-11 18:09:38','2026-07-10 16:09:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (204,'RECEIVE','ZT2370223937107',54,37,NULL,16,366,'SMALL','12.11','EXPIRED','764981','2026-06-19 23:04:38','2026-06-22 23:04:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (205,'RECEIVE','SY114590406066',33,117,NULL,11,242,'SMALL','19.95','PICKED','383669','2026-07-27 02:52:38','2026-07-29 02:52:38','2026-07-28 12:52:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (206,'RECEIVE','SF367425397770',1,64,NULL,3,70,'LARGE','7.97','PICKED','877754','2026-09-10 03:47:38','2026-09-12 03:47:38','2026-09-11 08:47:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (207,'RECEIVE','SF583856118566',41,111,NULL,2,30,'SMALL','7.07','PICKED','794555','2026-08-11 17:22:38','2026-08-14 17:22:38','2026-08-13 09:22:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (208,'RECEIVE','KL749071395182',22,104,NULL,4,90,'MEDIUM','11.41','EXCEPTION','103751','2026-07-25 09:52:38','2026-07-27 09:52:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (209,'RECEIVE','SY688388969993',33,59,NULL,14,321,'SMALL','12.06','STORED','005594','2026-09-29 17:54:38','2026-10-01 17:54:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (210,'RECEIVE','FN682263947444',9,41,NULL,2,37,'MEDIUM','4.61','STORED','216378','2026-09-29 17:50:38','2026-10-01 17:50:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (211,'RECEIVE','DBL764608005071',26,106,NULL,28,659,'SMALL','5.11','STORED','211906','2026-09-29 05:22:38','2026-10-01 05:22:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (212,'RECEIVE','KL482403841017',22,35,NULL,15,351,'MEDIUM','8.07','PICKED','522877','2026-09-29 01:52:38','2026-10-01 01:52:38','2026-09-29 18:52:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (213,'RECEIVE','QB464869923804',28,54,NULL,25,590,'MEDIUM','7.55','STORED','795723','2026-09-29 03:32:38','2026-10-02 03:32:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (214,'RECEIVE','YS746715633875',19,78,NULL,29,683,'SMALL','12.39','EXCEPTION','966602','2026-07-24 16:14:38','2026-07-26 16:14:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (215,'RECEIVE','FN633975324858',53,37,NULL,6,134,'MEDIUM','14.95','PICKED','855354','2026-08-01 18:51:38','2026-08-04 18:51:38','2026-08-03 01:51:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (216,'RECEIVE','ZT2388377205030',25,10,NULL,25,589,'MEDIUM','7.86','PICKED','564750','2026-06-28 07:49:38','2026-07-01 07:49:38','2026-06-28 21:49:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (217,'RECEIVE','HK757587790501',20,13,NULL,24,566,'MEDIUM','6.07','PICKED','798352','2026-08-14 14:02:38','2026-08-17 14:02:38','2026-08-17 05:02:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (218,'RECEIVE','XF973796183709',15,118,NULL,26,613,'MEDIUM','14.89','PICKED','562723','2026-08-01 03:25:38','2026-08-03 03:25:38','2026-08-01 18:25:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (219,'RECEIVE','HJ430421165047',13,46,NULL,3,61,'MEDIUM','4.78','EXPIRED','963244','2026-06-18 02:07:38','2026-06-20 02:07:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (220,'RECEIVE','ZT2053166066260',58,92,NULL,15,358,'LARGE','7.37','PICKED','336504','2026-09-13 19:44:38','2026-09-16 19:44:38','2026-09-15 04:44:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (221,'RECEIVE','SY141713334124',33,49,NULL,11,258,'MEDIUM','18.65','STORED','941733','2026-09-29 02:58:38','2026-10-01 02:58:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (222,'RECEIVE','HK835965182938',56,8,NULL,26,622,'LARGE','5.15','PICKED','662331','2026-08-13 03:29:38','2026-08-15 03:29:38','2026-08-14 08:29:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (223,'RECEIVE','ZTO980454863794',44,66,NULL,27,643,'MEDIUM','1.31','PICKED','014193','2026-08-10 00:07:38','2026-08-12 00:07:38','2026-08-10 08:07:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (224,'RECEIVE','ZT2608664609321',25,46,NULL,27,646,'LARGE','5.77','STORED','369049','2026-09-29 07:43:38','2026-10-01 07:43:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (225,'RECEIVE','ZTO650287405826',44,28,NULL,28,653,'SMALL','17.25','PICKED','160964','2026-08-13 21:12:38','2026-08-15 21:12:38','2026-08-14 13:12:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (226,'RECEIVE','ZT2994366997000',25,29,NULL,17,386,'SMALL','12.32','PICKED','122858','2026-08-29 00:17:38','2026-08-31 00:17:38','2026-08-30 18:17:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (227,'RECEIVE','TD435578264681',31,37,NULL,15,346,'SMALL','10.88','PICKED','359360','2026-07-24 02:51:38','2026-07-27 02:51:38','2026-07-25 19:51:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (228,'RECEIVE','RF191492910890',3,5,NULL,9,213,'LARGE','19.00','STORED','672122','2026-09-29 02:59:38','2026-10-02 02:59:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (229,'RECEIVE','EMS211246137227',52,7,NULL,5,98,'SMALL','4.53','PICKED','143374','2026-07-08 15:44:38','2026-07-10 15:44:38','2026-07-09 01:44:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (230,'RECEIVE','SY612318305443',47,106,NULL,29,678,'SMALL','12.64','PICKED','101810','2026-06-17 21:55:38','2026-06-19 21:55:38','2026-06-19 02:55:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (231,'RECEIVE','HK319620483544',50,101,NULL,5,107,'SMALL','5.93','PICKED','158196','2026-07-29 19:33:38','2026-07-31 19:33:38','2026-07-31 15:33:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (232,'RECEIVE','CN184182200223',30,71,NULL,23,552,'LARGE','17.66','EXCEPTION','155897','2026-09-19 00:38:38','2026-09-22 00:38:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (233,'RECEIVE','KL952742689012',8,105,NULL,13,301,'MEDIUM','8.34','PICKED','112815','2026-07-28 01:51:38','2026-07-30 01:51:38','2026-07-28 06:51:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (234,'RECEIVE','TT607144341081',43,120,NULL,6,125,'SMALL','2.19','PICKED','923462','2026-09-09 08:07:38','2026-09-12 08:07:38','2026-09-11 21:07:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (235,'RECEIVE','FN831103322609',53,52,NULL,3,58,'SMALL','13.48','PICKED','968159','2026-07-23 17:57:38','2026-07-26 17:57:38','2026-07-25 23:57:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (236,'RECEIVE','AJ896789643619',12,101,NULL,10,218,'SMALL','19.96','PICKED','295037','2026-06-15 14:14:38','2026-06-18 14:14:38','2026-06-15 16:14:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (237,'RECEIVE','EMS895286109550',39,56,NULL,22,507,'SMALL','9.10','STORED','760668','2026-09-29 20:01:38','2026-10-01 20:01:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (238,'RECEIVE','HK399589644452',20,89,NULL,12,285,'LARGE','17.40','PICKED','735922','2026-08-23 05:18:38','2026-08-25 05:18:38','2026-08-23 09:18:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (239,'RECEIVE','SY422044749382',55,117,NULL,23,538,'SMALL','4.23','STORED','697256','2026-09-29 19:39:38','2026-10-01 19:39:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (240,'RECEIVE','MN372129893186',6,66,NULL,5,100,'SMALL','13.26','PICKED','368316','2026-06-17 07:12:38','2026-06-19 07:12:38','2026-06-17 16:12:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (241,'RECEIVE','HK566160649212',56,45,NULL,10,220,'SMALL','15.86','PICKED','993146','2026-09-20 00:57:38','2026-09-22 00:57:38','2026-09-21 15:57:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (242,'RECEIVE','JD921773443214',5,49,NULL,25,586,'SMALL','18.49','PICKED','846644','2026-06-26 17:59:38','2026-06-29 17:59:38','2026-06-28 16:59:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (243,'RECEIVE','CN205655557414',30,16,NULL,27,640,'MEDIUM','0.41','PICKED','754685','2026-07-02 09:10:38','2026-07-04 09:10:38','2026-07-03 05:10:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (244,'RECEIVE','DBL375528551977',60,53,NULL,10,219,'SMALL','9.28','PICKED','297145','2026-06-20 19:14:38','2026-06-22 19:14:38','2026-06-20 22:14:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (245,'RECEIVE','FL405726753136',21,96,NULL,4,87,'MEDIUM','5.97','EXPIRED','353008','2026-08-20 17:27:38','2026-08-23 17:27:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (246,'RECEIVE','YD926065396119',57,14,NULL,24,556,'SMALL','10.04','PICKED','976183','2026-08-25 04:25:38','2026-08-27 04:25:38','2026-08-25 05:25:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (247,'RECEIVE','CN897165844025',30,102,NULL,8,176,'SMALL','6.10','PICKED','955442','2026-08-03 22:50:38','2026-08-05 22:50:38','2026-08-05 21:50:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (248,'RECEIVE','ZT056694206657',29,80,NULL,29,693,'LARGE','13.53','PICKED','437080','2026-09-06 16:04:38','2026-09-09 16:04:38','2026-09-08 06:04:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (249,'RECEIVE','ZT2537248110396',25,71,NULL,7,147,'SMALL','4.97','PICKED','071632','2026-07-29 23:42:38','2026-07-31 23:42:38','2026-07-30 01:42:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (250,'RECEIVE','FN163054633076',9,74,NULL,29,691,'MEDIUM','3.19','EXPIRED','414131','2026-09-23 04:03:38','2026-09-26 04:03:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (251,'RECEIVE','YT021485647901',18,86,NULL,27,637,'MEDIUM','19.31','PICKED','550902','2026-08-09 07:56:38','2026-08-12 07:56:38','2026-08-11 20:56:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (252,'RECEIVE','ZT2996295580369',25,52,NULL,27,632,'SMALL','6.82','RETURNED','837368','2026-08-13 06:49:38','2026-08-15 06:49:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (253,'RECEIVE','ZTO225624694770',36,88,NULL,22,518,'MEDIUM','5.35','PICKED','620307','2026-08-25 14:22:38','2026-08-27 14:22:38','2026-08-26 19:22:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (254,'RECEIVE','FN813213828840',9,24,NULL,22,512,'SMALL','14.18','PICKED','059092','2026-08-30 02:09:38','2026-09-01 02:09:38','2026-08-31 08:09:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (255,'RECEIVE','YT524804117200',10,111,NULL,10,234,'MEDIUM','2.04','EXCEPTION','125179','2026-06-21 14:32:38','2026-06-24 14:32:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (256,'RECEIVE','TT383404197153',43,29,NULL,11,249,'SMALL','15.74','PICKED','156890','2026-09-19 06:17:38','2026-09-22 06:17:38','2026-09-21 00:17:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (257,'RECEIVE','MN300917483670',59,34,NULL,14,331,'MEDIUM','3.97','EXPIRED','359996','2026-09-06 03:25:38','2026-09-08 03:25:38',NULL,NULL,NULL,NULL,NULL,NULL,'1.00',0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (258,'RECEIVE','QB200725531998',24,93,NULL,7,162,'MEDIUM','12.08','PICKED','110351','2026-06-06 03:58:38','2026-06-08 03:58:38','2026-06-06 17:58:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (259,'RECEIVE','HJ746128238262',2,62,NULL,30,704,'SMALL','10.34','STORED','701157','2026-09-28 23:32:38','2026-10-01 23:32:38',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (260,'RECEIVE','DBL854770450389',42,89,NULL,21,503,'LARGE','0.96','PICKED','252920','2026-08-10 06:10:38','2026-08-13 06:10:38','2026-08-12 12:10:38',NULL,NULL,NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:40');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (261,'SEND','HT161159958276',NULL,43,5,2,46,'LARGE','1.23','SEND_WAIT_PICKUP','715743','2026-09-22 02:52:38','2026-09-24 02:52:38',NULL,'倪莹','14643798853',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (262,'SEND','XD986298375252',NULL,100,29,2,25,'SMALL','8.11','SEND_WAIT_PICKUP','428980','2026-09-10 13:52:38','2026-09-12 13:52:38',NULL,'王婷','17345137306',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (263,'SEND','JD323299222050',NULL,3,6,2,47,'LARGE','5.97','SEND_WAIT_PICKUP','441302','2026-09-01 07:52:38','2026-09-03 07:52:38',NULL,'孙凤英','18424742236',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (264,'SEND','SY936531880877',NULL,101,24,2,26,'SMALL','2.67','SEND_WAIT_PICKUP','653506','2026-09-28 08:52:38','2026-09-30 08:52:38',NULL,'皮凤兰','19703537875',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (265,'SEND','SF834026193805',NULL,55,1,2,27,'SMALL','10.96','SEND_WAIT_PICKUP','548784','2026-09-28 16:52:38','2026-09-30 16:52:38',NULL,'史旭','18670183813',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (266,'SEND','SY612660060329',NULL,42,24,2,30,'SMALL','19.94','SEND_WAIT_PICKUP','033501','2026-09-03 15:52:38','2026-09-05 15:52:38',NULL,'刘桂兰','15765526918',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (267,'SEND','TD686283361435',NULL,44,21,2,48,'LARGE','12.71','SEND_WAIT_PICKUP','260743','2026-09-17 20:52:38','2026-09-19 20:52:38',NULL,'黄畅','15508594567',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (268,'SEND','YT517736106068',NULL,25,2,2,38,'MEDIUM','18.94','SEND_WAIT_PICKUP','342042','2026-09-24 13:52:38','2026-09-26 13:52:38',NULL,'周林','15457049937',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (269,'SEND','GW862196751807',NULL,7,13,2,39,'MEDIUM','18.02','SEND_WAIT_PICKUP','897314','2026-09-20 22:52:38','2026-09-22 22:52:38',NULL,'孙俊','15966205311',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (270,'SEND','ZT450578171895',NULL,104,10,2,31,'SMALL','9.66','SEND_WAIT_PICKUP','284833','2026-09-03 05:52:38','2026-09-05 05:52:38',NULL,'杨静','18185639659',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (271,'SEND','LB741630789766',NULL,31,18,3,69,'LARGE','7.01','SEND_WAIT_PICKUP','603153','2026-09-15 17:52:38','2026-09-17 17:52:38',NULL,'刘玉','15528374047',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (272,'SEND','ZT2241647488450',NULL,54,26,2,32,'SMALL','13.80','SEND_WAIT_PICKUP','266045','2026-09-25 12:52:38','2026-09-27 12:52:38',NULL,'王想','19020948791',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (273,'SEND','SF246346714141',NULL,98,1,2,33,'SMALL','9.56','SEND_WAIT_PICKUP','410589','2026-09-27 16:52:38','2026-09-29 16:52:38',NULL,'鞠红梅','18157911167',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (274,'SEND','YD351110290818',NULL,13,4,3,70,'LARGE','16.22','SEND_WAIT_PICKUP','787760','2026-09-20 22:52:38','2026-09-22 22:52:38',NULL,'叶华','14974169935',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (275,'SEND','ST990254135936',NULL,95,9,2,40,'MEDIUM','16.01','SEND_WAIT_PICKUP','209695','2026-09-10 07:52:38','2026-09-12 07:52:38',NULL,'赖建华','16074844494',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (276,'SEND','LB695960695511',NULL,92,18,2,34,'SMALL','4.27','SEND_WAIT_PICKUP','188998','2026-09-18 01:52:38','2026-09-20 01:52:38',NULL,'金洁','19909784366',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (277,'SEND','KL747539160751',NULL,54,19,2,35,'SMALL','16.39','SEND_WAIT_PICKUP','441686','2026-09-25 23:52:38','2026-09-27 23:52:38',NULL,'刘娜','16352007911',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (278,'SEND','GW870949604337',NULL,57,13,2,41,'MEDIUM','18.13','SEND_WAIT_PICKUP','174824','2026-09-26 12:52:38','2026-09-28 12:52:38',NULL,'李健','13803578058',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (279,'SEND','SY573365768000',NULL,26,24,2,36,'SMALL','2.32','SEND_WAIT_PICKUP','400958','2026-09-14 06:52:38','2026-09-16 06:52:38',NULL,'黄平','14577686932',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (280,'SEND','ST894027137933',NULL,38,9,3,49,'SMALL','15.56','SEND_WAIT_PICKUP','813154','2026-09-03 17:52:38','2026-09-05 17:52:38',NULL,'辛伟','15668582802',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (281,'SEND','MN756905387657',NULL,78,22,2,43,'MEDIUM','7.14','SEND_WAIT_PICKUP','359260','2026-09-16 18:52:38','2026-09-18 18:52:38',NULL,'杨萍','14398553891',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (282,'SEND','FL146419759219',NULL,90,28,3,50,'SMALL','18.34','SEND_WAIT_PICKUP','345092','2026-09-04 04:52:38','2026-09-06 04:52:38',NULL,'任强','16466742117',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (283,'SEND','YD057713216929',NULL,45,4,3,51,'SMALL','18.30','SEND_WAIT_PICKUP','510070','2026-09-26 00:52:38','2026-09-28 00:52:38',NULL,'刘冬梅','16222853354',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (284,'SEND','LB400211904150',NULL,110,18,2,44,'MEDIUM','0.68','SEND_WAIT_PICKUP','015674','2026-09-03 23:52:38','2026-09-05 23:52:38',NULL,'侯颖','13756667122',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (285,'SEND','KL990576348536',NULL,62,19,3,52,'SMALL','2.98','SEND_WAIT_PICKUP','527432','2026-09-07 09:52:38','2026-09-09 09:52:38',NULL,'楚桂香','16223318186',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (286,'SEND','ZT124128832382',NULL,81,10,3,62,'MEDIUM','14.87','SEND_WAIT_PICKUP','860025','2026-09-28 16:52:38','2026-09-30 16:52:38',NULL,'王莹','14524810431',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (287,'SEND','YD011479999343',NULL,69,4,3,53,'SMALL','14.86','SEND_WAIT_PICKUP','943860','2026-09-06 05:52:38','2026-09-08 05:52:38',NULL,'杜秀英','17901190622',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (288,'SEND','DBL308549403248',NULL,54,8,3,54,'SMALL','15.85','SEND_WAIT_PICKUP','605598','2026-09-15 11:52:38','2026-09-17 11:52:38',NULL,'王淑华','14565162490',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (289,'SEND','HJ822659340782',NULL,8,25,3,55,'SMALL','14.76','SEND_WAIT_PICKUP','239939','2026-09-13 03:52:38','2026-09-15 03:52:38',NULL,'陈洋','16811454895',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (290,'SEND','JD020664546942',NULL,102,6,3,56,'SMALL','4.21','SEND_WAIT_PICKUP','914218','2026-09-06 08:52:38','2026-09-08 08:52:38',NULL,'黄春梅','14254423768',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (291,'SEND','YT269653111213',35,94,2,3,63,'MEDIUM','8.04','SEND_COLLECTED','664087','2026-09-20 21:52:38','2026-09-22 21:52:38','2026-09-21 16:52:38','林林','14386742265',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (292,'SEND','HJ782235268746',57,112,25,3,57,'SMALL','3.21','SEND_COLLECTED','508561','2026-09-11 20:52:38','2026-09-13 20:52:38','2026-09-12 01:52:38','詹俊','15997210113',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (293,'SEND','TD012237815447',33,104,21,3,71,'LARGE','15.24','SEND_COLLECTED','144006','2026-09-21 20:52:38','2026-09-23 20:52:38','2026-09-22 01:52:38','夏畅','15307302569',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (294,'SEND','RF600384116079',52,95,17,3,63,'MEDIUM','7.71','SEND_COLLECTED','745280','2026-09-15 08:52:38','2026-09-17 08:52:38','2026-09-16 05:52:38','黄超','15295724201',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (295,'SEND','HT836018230097',29,89,5,3,57,'SMALL','15.78','SEND_COLLECTED','449879','2026-08-22 15:52:38','2026-08-24 15:52:38','2026-08-23 03:52:38','覃杨','13052980647',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (296,'SEND','XF017260829386',48,31,16,3,71,'LARGE','6.18','SEND_COLLECTED','497668','2026-09-06 07:52:38','2026-09-08 07:52:38','2026-09-06 18:52:38','吴帅','18683813281',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (297,'SEND','EMS747835276523',51,73,7,3,63,'MEDIUM','3.95','SEND_COLLECTED','079365','2026-09-16 04:52:38','2026-09-18 04:52:38','2026-09-17 08:52:38','袁慧','16668298597',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (298,'SEND','YT939937858213',1,53,2,3,63,'MEDIUM','9.70','SEND_COLLECTED','530481','2026-09-14 20:52:38','2026-09-16 20:52:38','2026-09-16 02:52:38','王莉','18606157351',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (299,'SEND','YD857992391676',8,25,4,3,63,'MEDIUM','18.26','SEND_COLLECTED','853807','2026-09-28 06:52:38','2026-09-30 06:52:38','2026-09-29 12:52:38','宋楠','18018863472',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (300,'SEND','XF966335327521',14,77,16,3,71,'LARGE','2.49','SEND_COLLECTED','041597','2026-08-29 20:52:38','2026-08-31 20:52:38','2026-08-31 00:52:38','乔鹏','18535823902',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (301,'SEND','CN256029827134',22,69,23,3,57,'SMALL','14.38','SEND_COLLECTED','413947','2026-08-26 03:52:38','2026-08-28 03:52:38','2026-08-26 21:52:38','康想','15811361810',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (302,'SEND','MN838063564655',33,63,22,3,71,'LARGE','15.72','SEND_COLLECTED','330439','2026-09-18 15:52:38','2026-09-20 15:52:38','2026-09-19 06:52:38','王凤兰','16191566793',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (303,'SEND','DBL385614877644',11,40,8,3,63,'MEDIUM','17.76','SEND_COLLECTED','426595','2026-09-18 19:52:38','2026-09-20 19:52:38','2026-09-20 01:52:38','杨燕','17461355350',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:41');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (304,'SEND','JD056111830394',12,116,6,3,71,'LARGE','4.40','SEND_COLLECTED','532197','2026-08-31 20:52:38','2026-09-02 20:52:38','2026-09-01 07:52:38','韩艳','17653048712',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:42');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (305,'SEND','CN974648530451',49,109,23,3,57,'SMALL','15.68','SEND_COLLECTED','282402','2026-09-20 11:52:38','2026-09-22 11:52:38','2026-09-20 23:52:38','宋晶','18789986307',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:42');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (306,'SEND','JD045252456047',14,29,6,3,57,'SMALL','2.96','SEND_COLLECTED','821598','2026-09-22 19:52:38','2026-09-24 19:52:38','2026-09-23 14:52:38','高玉珍','13748600185',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:42');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (307,'SEND','SF676786206392',47,46,1,3,63,'MEDIUM','9.73','SEND_COLLECTED','804016','2026-09-19 04:52:38','2026-09-21 04:52:38','2026-09-19 22:52:38','王浩','17395366351',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:42');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (308,'SEND','KL012574478375',24,30,19,3,57,'SMALL','10.07','SEND_COLLECTED','837713','2026-09-08 17:52:38','2026-09-10 17:52:38','2026-09-09 08:52:38','张艳','13743673810',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:42');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (309,'SEND','TD817397946832',51,12,21,3,57,'SMALL','11.93','SEND_COLLECTED','511174','2026-08-30 04:52:38','2026-09-01 04:52:38','2026-08-30 22:52:38','王平','17883716230',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:42');
INSERT INTO `t_package` (`package_id`,`direction`,`tracking_no`,`courier_id`,`user_id`,`company_id`,`cabinet_id`,`cell_id`,`size_type`,`weight`,`status`,`pickup_code`,`store_time`,`expire_time`,`pickup_time`,`recipient_name`,`recipient_phone`,`from_send_id`,`note`,`pack_recommendation_id`,`overtime_fee`,`overtime_fee_paid`,`created_at`) VALUES (310,'SEND','ST757469675608',40,17,9,3,63,'MEDIUM','17.45','SEND_COLLECTED','382211','2026-09-10 07:52:38','2026-09-12 07:52:38','2026-09-10 20:52:38','田玉梅','15952486044',NULL,NULL,NULL,NULL,0,'2026-09-29 22:52:42');

-- ----- 数据 t_pack_recommend_item -----
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (1,1,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (2,1,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (3,1,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (4,1,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (5,1,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (6,1,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (7,1,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (8,2,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (9,2,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (10,2,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (11,2,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (12,2,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (13,2,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (14,2,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (15,3,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (16,3,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (17,3,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (18,3,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (19,3,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (20,3,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (21,3,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (22,4,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (23,4,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (24,4,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (25,4,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (26,4,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (27,4,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (28,4,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (29,5,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (30,5,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (31,5,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (32,5,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (33,5,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (34,5,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (35,5,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (36,6,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (37,6,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (38,6,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (39,6,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (40,6,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (41,6,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (42,6,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (43,7,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (44,7,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (45,7,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (46,7,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (47,7,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (48,7,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (49,7,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (50,8,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (51,8,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (52,8,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (53,8,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (54,8,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (55,8,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (56,8,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (57,9,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (58,9,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (59,9,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (60,9,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (61,9,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (62,9,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (63,9,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (64,10,'FORBIDDEN',0,'锂电池','航空禁运',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (65,10,'SENSITIVE',0,'玻璃杯','易碎需缓冲',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (66,10,'STEP',1,'气泡膜包裹','玻璃杯至少包 3 层',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (67,10,'STEP',2,'装箱','居中放置并填充',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (68,10,'STEP',3,'封箱贴标','十字加固并贴易碎标签',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (69,10,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (70,10,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (71,10,'MATERIAL',0,'易碎标签',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (72,11,'SENSITIVE',0,'玻璃杯','易碎，需气泡膜多层包裹',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (73,11,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (74,11,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (75,11,'STEP',3,'易碎加固','对易碎/敏感部位额外加缓冲材料并固定，避免运输途中晃动',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (76,11,'STEP',4,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (77,11,'STEP',5,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (78,11,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (79,11,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (80,11,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (81,11,'MATERIAL',0,'易碎标签',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (82,12,'FORBIDDEN',0,'锂电池','航空禁运，禁止寄递',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (83,12,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (84,12,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (85,12,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (86,12,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (87,12,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (88,12,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (89,12,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (90,13,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (91,13,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (92,13,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (93,13,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (94,13,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (95,13,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (96,13,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (97,14,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (98,14,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (99,14,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (100,14,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (101,14,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (102,14,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (103,14,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (104,15,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (105,15,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (106,15,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (107,15,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (108,15,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (109,15,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (110,15,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (111,16,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (112,16,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (113,16,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (114,16,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (115,16,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (116,16,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (117,16,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (118,17,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (119,17,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (120,17,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (121,17,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (122,17,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (123,17,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (124,17,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (125,18,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (126,18,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (127,18,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (128,18,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (129,18,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (130,18,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (131,18,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (132,19,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (133,19,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (134,19,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (135,19,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (136,19,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (137,19,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (138,19,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (139,20,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (140,20,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (141,20,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (142,20,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (143,20,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (144,20,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (145,20,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (146,21,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (147,21,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (148,21,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (149,21,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (150,21,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (151,21,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (152,21,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (153,22,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (154,22,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (155,22,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (156,22,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (157,22,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (158,22,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (159,22,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (160,23,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (161,23,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (162,23,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (163,23,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (164,23,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (165,23,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (166,23,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (167,24,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (168,24,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (169,24,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (170,24,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (171,24,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (172,24,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (173,24,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (174,25,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (175,25,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (176,25,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (177,25,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (178,25,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (179,25,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (180,25,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (181,26,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (182,26,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (183,26,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (184,26,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (185,26,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (186,26,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (187,26,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (188,27,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (189,27,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (190,27,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (191,27,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (192,27,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (193,27,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (194,27,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (195,28,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (196,28,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (197,28,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (198,28,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (199,28,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (200,28,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (201,28,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (202,29,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (203,29,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (204,29,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (205,29,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (206,29,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (207,29,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (208,29,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (209,30,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (210,30,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (211,30,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (212,30,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (213,30,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (214,30,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (215,30,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (216,31,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (217,31,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (218,31,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (219,31,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (220,31,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (221,31,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (222,31,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (223,32,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (224,32,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (225,32,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (226,32,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (227,32,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (228,32,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (229,32,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (230,33,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (231,33,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (232,33,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (233,33,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (234,33,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (235,33,'MATERIAL',0,'5 号纸箱',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (236,33,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (237,34,'STEP',1,'a','b',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (238,34,'STEP',2,'c','d',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (239,34,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (240,35,'FORBIDDEN',0,'锂电池','航空禁运，禁止寄递',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (241,35,'STEP',1,'a','b',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (242,35,'STEP',2,'c','d',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (243,35,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (244,36,'STEP',1,'清点物品','逐件清点数量并拍照留底，确认无禁寄品、无渗漏',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (245,36,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (246,36,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (247,36,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (248,36,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (249,36,'MATERIAL',0,'封箱胶带',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (250,37,'STEP',1,'只有一步','x',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (251,37,'STEP',2,'缓冲包装','用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (252,37,'STEP',3,'装入箱体','物品居中放置，四周填充缓冲材料，箱内不留晃动空间',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (253,37,'STEP',4,'封箱贴标','封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (254,37,'MATERIAL',0,'气泡膜',NULL,1,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (255,38,'STEP',1,'步骤1','x',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (256,38,'STEP',2,'步骤2','x',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (257,38,'STEP',3,'步骤3','x',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (258,38,'STEP',4,'步骤4','x',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (259,38,'STEP',5,'步骤5','x',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (260,38,'STEP',6,'步骤6','x',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (261,38,'STEP',7,'步骤7','x',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (262,38,'STEP',8,'步骤8','x',NULL,NULL);
INSERT INTO `t_pack_recommend_item` (`item_id`,`recommendation_id`,`kind`,`seq`,`name`,`detail`,`qty`,`unit`) VALUES (263,38,'MATERIAL',0,'气泡膜',NULL,1,NULL);

-- ----- 数据 t_pickup_record -----
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (1,4,'APP','2026-08-02 21:04:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (2,5,'APP','2026-07-06 19:46:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (3,8,'APP','2026-07-16 21:00:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (4,9,'APP','2026-06-21 12:41:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (5,10,'CODE','2026-06-27 23:50:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (6,11,'APP','2026-09-09 04:28:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (7,13,'CODE','2026-06-19 16:56:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (8,14,'CODE','2026-06-09 11:39:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (9,15,'APP','2026-09-01 12:39:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (10,16,'APP','2026-08-04 11:47:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (11,17,'CODE','2026-07-04 07:00:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (12,22,'CODE','2026-08-28 04:14:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (13,23,'CODE','2026-09-10 02:12:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (14,24,'APP','2026-07-16 13:26:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (15,25,'APP','2026-08-08 20:42:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (16,26,'CODE','2026-09-22 20:00:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (17,30,'APP','2026-09-27 05:28:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (18,32,'CODE','2026-08-18 15:43:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (19,35,'CODE','2026-07-15 05:38:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (20,39,'APP','2026-06-26 09:18:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (21,40,'APP','2026-07-06 02:45:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (22,41,'APP','2026-09-20 22:00:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (23,44,'CODE','2026-08-19 18:37:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (24,45,'CODE','2026-07-01 05:27:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (25,46,'CODE','2026-07-31 01:55:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (26,48,'CODE','2026-09-16 12:38:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (27,50,'CODE','2026-06-15 21:04:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (28,51,'CODE','2026-09-01 08:00:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (29,52,'CODE','2026-08-30 20:19:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (30,54,'APP','2026-09-06 01:18:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (31,56,'APP','2026-08-06 21:35:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (32,58,'APP','2026-07-21 01:26:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (33,60,'APP','2026-07-09 02:47:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (34,65,'APP','2026-06-09 01:32:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (35,66,'CODE','2026-06-15 23:50:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (36,67,'CODE','2026-07-18 18:15:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (37,68,'APP','2026-08-31 03:50:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (38,70,'APP','2026-06-21 00:50:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (39,71,'APP','2026-06-30 09:27:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (40,72,'APP','2026-09-21 05:08:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (41,75,'APP','2026-08-29 23:27:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (42,76,'CODE','2026-06-23 02:52:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (43,78,'CODE','2026-09-25 14:50:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (44,79,'CODE','2026-07-22 12:12:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (45,80,'CODE','2026-08-22 01:17:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (46,81,'CODE','2026-06-14 13:03:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (47,82,'CODE','2026-09-10 10:12:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (48,84,'CODE','2026-09-11 03:42:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (49,85,'CODE','2026-09-01 16:20:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (50,86,'CODE','2026-09-08 15:37:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (51,88,'APP','2026-07-18 13:59:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (52,89,'APP','2026-08-29 05:18:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (53,93,'CODE','2026-07-27 21:03:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (54,95,'APP','2026-08-04 03:03:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (55,97,'APP','2026-08-26 19:17:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (56,98,'APP','2026-07-08 06:43:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (57,99,'CODE','2026-08-28 09:45:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (58,100,'APP','2026-08-31 02:59:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (59,101,'CODE','2026-09-02 17:59:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (60,103,'CODE','2026-08-22 18:13:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (61,104,'APP','2026-07-18 09:22:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (62,105,'CODE','2026-08-14 05:32:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (63,109,'CODE','2026-07-10 03:21:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (64,112,'APP','2026-06-28 04:50:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (65,113,'CODE','2026-06-11 23:31:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (66,114,'APP','2026-09-04 03:54:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (67,119,'APP','2026-06-12 21:28:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (68,120,'CODE','2026-06-06 04:02:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (69,121,'APP','2026-07-23 16:02:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (70,122,'APP','2026-09-03 21:02:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (71,123,'CODE','2026-06-27 22:41:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (72,125,'CODE','2026-08-19 22:27:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (73,127,'CODE','2026-07-13 12:01:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (74,128,'CODE','2026-08-10 02:53:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (75,130,'CODE','2026-08-04 15:17:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (76,131,'APP','2026-07-18 01:37:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (77,132,'APP','2026-07-04 04:40:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (78,133,'APP','2026-09-02 07:16:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (79,134,'APP','2026-07-16 23:03:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (80,139,'APP','2026-06-19 21:06:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (81,141,'CODE','2026-06-26 11:22:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (82,143,'CODE','2026-07-30 12:17:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (83,150,'CODE','2026-07-20 01:20:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (84,152,'APP','2026-09-18 05:57:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (85,154,'APP','2026-08-21 18:38:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (86,156,'CODE','2026-06-24 08:58:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (87,158,'APP','2026-07-16 23:23:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (88,159,'CODE','2026-06-30 16:59:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (89,161,'CODE','2026-08-03 02:50:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (90,163,'CODE','2026-06-14 01:56:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (91,164,'CODE','2026-09-27 14:04:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (92,167,'CODE','2026-08-27 05:24:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (93,171,'CODE','2026-09-18 19:11:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (94,172,'APP','2026-08-15 02:59:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (95,173,'APP','2026-09-19 10:01:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (96,176,'APP','2026-07-01 05:49:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (97,177,'APP','2026-08-28 09:09:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (98,178,'CODE','2026-08-27 02:01:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (99,180,'APP','2026-06-19 03:03:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (100,181,'CODE','2026-06-12 16:11:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (101,182,'CODE','2026-07-08 07:22:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (102,183,'APP','2026-06-24 07:52:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (103,188,'CODE','2026-07-20 18:08:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (104,190,'APP','2026-07-27 03:28:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (105,191,'CODE','2026-08-02 03:49:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (106,192,'APP','2026-08-31 15:00:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (107,193,'CODE','2026-09-29 21:52:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (108,194,'APP','2026-08-11 14:39:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (109,195,'CODE','2026-07-16 02:21:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (110,198,'APP','2026-08-27 18:20:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (111,199,'APP','2026-08-14 22:38:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (112,201,'CODE','2026-08-22 07:09:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (113,203,'APP','2026-07-10 16:09:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (114,205,'CODE','2026-07-28 12:52:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (115,206,'APP','2026-09-11 08:47:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (116,207,'APP','2026-08-13 09:22:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (117,212,'CODE','2026-09-29 18:52:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (118,215,'APP','2026-08-03 01:51:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (119,216,'APP','2026-06-28 21:49:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (120,217,'CODE','2026-08-17 05:02:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (121,218,'APP','2026-08-01 18:25:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (122,220,'CODE','2026-09-15 04:44:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (123,222,'APP','2026-08-14 08:29:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (124,223,'APP','2026-08-10 08:07:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (125,225,'APP','2026-08-14 13:12:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (126,226,'CODE','2026-08-30 18:17:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (127,227,'APP','2026-07-25 19:51:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (128,229,'CODE','2026-07-09 01:44:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (129,230,'APP','2026-06-19 02:55:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (130,231,'CODE','2026-07-31 15:33:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (131,233,'CODE','2026-07-28 06:51:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (132,234,'APP','2026-09-11 21:07:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (133,235,'APP','2026-07-25 23:57:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (134,236,'CODE','2026-06-15 16:14:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (135,238,'APP','2026-08-23 09:18:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (136,240,'APP','2026-06-17 16:12:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (137,241,'APP','2026-09-21 15:57:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (138,242,'CODE','2026-06-28 16:59:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (139,243,'APP','2026-07-03 05:10:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (140,244,'APP','2026-06-20 22:14:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (141,246,'CODE','2026-08-25 05:25:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (142,247,'APP','2026-08-05 21:50:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (143,248,'CODE','2026-09-08 06:04:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (144,249,'APP','2026-07-30 01:42:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (145,251,'CODE','2026-08-11 20:56:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (146,253,'CODE','2026-08-26 19:22:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (147,254,'APP','2026-08-31 08:09:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (148,256,'CODE','2026-09-21 00:17:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (149,258,'APP','2026-06-06 17:58:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (150,260,'CODE','2026-08-12 12:10:38','USER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (151,186,'CODE','2026-08-11 10:46:38','USER','FAIL','取件码错误');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (152,184,'APP','2026-08-17 10:16:38','USER','FAIL','取件码已失效');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (153,92,'APP','2026-09-29 18:52:38','USER','FAIL','取件码已失效');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (154,195,'CODE','2026-07-16 12:21:38','USER','FAIL','多次尝试锁定');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (155,68,'APP','2026-08-29 15:50:38','USER','FAIL','取件码已失效');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (156,30,'CODE','2026-09-24 19:28:38','USER','FAIL','取件码错误');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (157,85,'APP','2026-09-01 18:20:38','USER','FAIL','取件码已失效');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (158,51,'CODE','2026-09-01 03:00:38','USER','FAIL','取件码已失效');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (159,222,'APP','2026-08-13 07:29:38','USER','FAIL','多次尝试锁定');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (160,257,'CODE','2026-09-06 14:25:38','USER','FAIL','取件码已失效');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (161,156,'APP','2026-06-24 12:58:38','USER','FAIL','多次尝试锁定');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (162,158,'APP','2026-07-16 01:23:38','USER','FAIL','多次尝试锁定');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (163,183,'CODE','2026-06-25 22:52:38','USER','FAIL','多次尝试锁定');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (164,230,'CODE','2026-06-19 14:55:38','USER','FAIL','取件码错误');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (165,35,'CODE','2026-07-15 11:38:38','USER','FAIL','取件码错误');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (166,48,'APP','2026-09-15 22:38:38','USER','FAIL','取件码错误');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (167,256,'CODE','2026-09-20 20:17:38','USER','FAIL','取件码已失效');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (168,158,'APP','2026-07-17 02:23:38','USER','FAIL','多次尝试锁定');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (169,122,'CODE','2026-09-02 20:02:38','USER','FAIL','多次尝试锁定');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (170,161,'CODE','2026-08-03 17:50:38','USER','FAIL','取件码错误');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (171,81,'CODE','2026-06-13 21:03:38','USER','FAIL','取件码错误');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (172,120,'APP','2026-06-05 16:02:38','USER','FAIL','取件码错误');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (173,204,'APP','2026-06-20 04:04:38','USER','FAIL','取件码已失效');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (174,247,'CODE','2026-08-04 22:50:38','USER','FAIL','取件码已失效');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (175,76,'APP','2026-06-24 07:52:38','USER','FAIL','多次尝试锁定');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (176,45,'APP','2026-06-30 00:27:38','USER','FAIL','取件码已失效');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (177,129,'CODE','2026-08-03 23:56:38','USER','FAIL','取件码错误');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (178,195,'CODE','2026-07-16 08:21:38','USER','FAIL','多次尝试锁定');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (179,67,'CODE','2026-07-18 21:15:38','USER','FAIL','取件码已失效');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (180,48,'APP','2026-09-15 18:38:38','USER','FAIL','多次尝试锁定');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (181,14,'APP','2026-06-08 23:39:38','USER','FAIL','多次尝试锁定');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (182,243,'CODE','2026-07-04 08:10:38','USER','FAIL','多次尝试锁定');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (183,169,'APP','2026-09-03 06:50:38','USER','FAIL','取件码已失效');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (184,248,'CODE','2026-09-07 15:04:38','USER','FAIL','多次尝试锁定');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (185,83,'APP','2026-09-29 17:52:38','USER','FAIL','多次尝试锁定');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (186,191,'APP','2026-08-03 07:49:38','USER','FAIL','取件码错误');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (187,55,'CODE','2026-09-13 19:17:38','USER','FAIL','多次尝试锁定');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (188,18,'APP','2026-07-31 04:19:38','USER','FAIL','取件码已失效');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (189,158,'APP','2026-07-16 00:23:38','USER','FAIL','多次尝试锁定');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (190,80,'CODE','2026-08-23 06:17:38','USER','FAIL','取件码错误');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (191,253,'APP','2026-08-26 21:22:38','USER','FAIL','多次尝试锁定');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (192,168,'CODE','2026-09-29 10:52:38','USER','FAIL','多次尝试锁定');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (193,30,'APP','2026-09-25 22:28:38','USER','FAIL','取件码已失效');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (194,125,'APP','2026-08-19 12:27:38','USER','FAIL','取件码错误');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (195,227,'CODE','2026-07-26 01:51:38','USER','FAIL','取件码已失效');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (196,164,'APP','2026-09-27 20:04:38','USER','FAIL','取件码错误');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (197,196,'APP','2026-09-21 23:05:38','USER','FAIL','取件码已失效');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (198,234,'CODE','2026-09-10 21:07:38','USER','FAIL','取件码错误');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (199,213,'CODE','2026-09-29 10:52:38','USER','FAIL','多次尝试锁定');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (200,2,'CODE','2026-09-29 13:52:38','USER','FAIL','取件码已失效');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (201,36,'CODE','2026-09-29 20:52:38','USER','FAIL','多次尝试锁定');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (202,257,'CODE','2026-09-07 19:25:38','USER','FAIL','取件码错误');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (203,254,'CODE','2026-08-30 13:09:38','USER','FAIL','取件码错误');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (204,4,'APP','2026-08-03 00:04:38','USER','FAIL','取件码错误');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (205,118,'CODE','2026-08-15 06:52:38','USER','FAIL','多次尝试锁定');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (206,28,'CODE','2026-09-29 17:52:38','USER','FAIL','取件码错误');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (207,33,'CODE','2026-09-24 21:10:38','USER','FAIL','取件码错误');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (208,173,'CODE','2026-09-19 11:01:38','USER','FAIL','取件码错误');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (209,82,'CODE','2026-09-11 03:12:38','USER','FAIL','取件码已失效');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (210,102,'CODE','2026-09-29 19:34:38','USER','FAIL','取件码错误');
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (211,291,'APP','2026-09-21 16:52:38','COURIER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (212,292,'APP','2026-09-12 01:52:38','COURIER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (213,293,'APP','2026-09-22 01:52:38','COURIER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (214,294,'APP','2026-09-16 05:52:38','COURIER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (215,295,'APP','2026-08-23 03:52:38','COURIER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (216,296,'APP','2026-09-06 18:52:38','COURIER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (217,297,'APP','2026-09-17 08:52:38','COURIER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (218,298,'APP','2026-09-16 02:52:38','COURIER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (219,299,'APP','2026-09-29 12:52:38','COURIER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (220,300,'APP','2026-08-31 00:52:38','COURIER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (221,301,'APP','2026-08-26 21:52:38','COURIER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (222,302,'APP','2026-09-19 06:52:38','COURIER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (223,303,'APP','2026-09-20 01:52:38','COURIER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (224,304,'APP','2026-09-01 07:52:38','COURIER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (225,305,'APP','2026-09-20 23:52:38','COURIER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (226,306,'APP','2026-09-23 14:52:38','COURIER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (227,307,'APP','2026-09-19 22:52:38','COURIER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (228,308,'APP','2026-09-09 08:52:38','COURIER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (229,309,'APP','2026-08-30 22:52:38','COURIER','SUCCESS',NULL);
INSERT INTO `t_pickup_record` (`record_id`,`package_id`,`pickup_method`,`pickup_time`,`operator_role`,`result`,`fail_reason`) VALUES (230,310,'APP','2026-09-10 20:52:38','COURIER','SUCCESS',NULL);

-- ----- 数据 t_exception_log -----
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (1,6,'RETURNED','2026-08-11 11:45:38','2026-08-11 17:45:38','鄢雷','AUTO_RETURNED','系统自动退回');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (2,7,'TIMEOUT','2026-06-15 23:29:38',NULL,NULL,'PENDING','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (3,18,'TIMEOUT','2026-08-02 04:19:38',NULL,NULL,'RESOLVED','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (4,19,'TIMEOUT','2026-09-30 06:14:38',NULL,NULL,'RESOLVED','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (5,21,'OVERWEIGHT','2026-06-01 17:36:38','2026-06-02 00:36:38','孙芳','RESOLVED','已现场处理');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (6,29,'TIMEOUT','2026-07-17 03:28:38',NULL,NULL,'PENDING','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (7,31,'RETURNED','2026-07-19 00:38:38','2026-07-19 06:38:38','宋晶','AUTO_RETURNED','系统自动退回');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (8,33,'DAMAGED','2026-09-23 07:10:38','2026-09-23 16:10:38','戴军','RESOLVED','已现场处理');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (9,37,'DAMAGED','2026-08-19 02:53:38','2026-08-19 12:53:38','刘淑兰','RESOLVED','已现场处理');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (10,38,'OVERWEIGHT','2026-08-08 05:08:38','2026-08-08 15:08:38','刘亮','RESOLVED','已现场处理');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (11,43,'TIMEOUT','2026-08-08 04:31:38',NULL,NULL,'PENDING','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (12,49,'OVERWEIGHT','2026-08-14 19:32:38','2026-08-15 14:32:38','夏静','RESOLVED','已现场处理');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (13,55,'OVERWEIGHT','2026-09-13 10:17:38','2026-09-13 16:17:38','柳波','RESOLVED','已现场处理');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (14,57,'TIMEOUT','2026-08-08 20:52:38',NULL,NULL,'PENDING','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (15,59,'WRONG_CELL','2026-09-07 21:16:38','2026-09-08 06:16:38','吴梅','RESOLVED','已现场处理');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (16,62,'DAMAGED','2026-06-24 21:47:38','2026-06-25 15:47:38','徐婷婷','RESOLVED','已现场处理');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (17,64,'OVERWEIGHT','2026-07-31 22:42:38','2026-08-01 10:42:38','王萍','RESOLVED','已现场处理');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (18,69,'RETURNED','2026-08-14 07:13:38','2026-08-14 13:13:38','唐杨','AUTO_RETURNED','系统自动退回');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (19,73,'TIMEOUT','2026-07-19 17:24:38',NULL,NULL,'RESOLVED','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (20,74,'TIMEOUT','2026-09-15 20:21:38',NULL,NULL,'RESOLVED','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (21,87,'TIMEOUT','2026-09-15 02:07:38',NULL,NULL,'PENDING','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (22,91,'TIMEOUT','2026-07-09 11:04:38',NULL,NULL,'RESOLVED','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (23,96,'TIMEOUT','2026-06-26 12:27:38',NULL,NULL,'PENDING','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (24,102,'WRONG_CELL','2026-09-29 00:34:38','2026-09-29 14:34:38','曹淑兰','RESOLVED','已现场处理');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (25,106,'TIMEOUT','2026-08-21 08:57:38',NULL,NULL,'PENDING','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (26,107,'DAMAGED','2026-06-03 07:47:38','2026-06-03 15:47:38','李成','RESOLVED','已现场处理');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (27,110,'TIMEOUT','2026-08-08 15:50:38',NULL,NULL,'PENDING','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (28,117,'TIMEOUT','2026-09-09 07:54:38',NULL,NULL,'PENDING','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (29,118,'WRONG_CELL','2026-08-13 19:52:38','2026-08-14 10:52:38','丁杰','RESOLVED','已现场处理');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (30,126,'TIMEOUT','2026-06-29 06:36:38',NULL,NULL,'RESOLVED','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (31,129,'TIMEOUT','2026-08-05 00:56:38',NULL,NULL,'RESOLVED','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (32,135,'RETURNED','2026-08-30 18:45:38','2026-08-31 00:45:38','王桂英','AUTO_RETURNED','系统自动退回');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (33,137,'TIMEOUT','2026-06-09 18:42:38',NULL,NULL,'RESOLVED','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (34,138,'RETURNED','2026-08-12 08:59:38','2026-08-12 14:59:38','洪玉珍','AUTO_RETURNED','系统自动退回');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (35,142,'TIMEOUT','2026-06-08 21:32:38',NULL,NULL,'PENDING','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (36,144,'DAMAGED','2026-06-30 09:46:38','2026-06-30 17:46:38','姜萍','RESOLVED','已现场处理');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (37,147,'TIMEOUT','2026-08-19 15:11:38',NULL,NULL,'PENDING','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (38,148,'RETURNED','2026-09-04 10:08:38','2026-09-04 16:08:38','焦秀兰','AUTO_RETURNED','系统自动退回');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (39,149,'TIMEOUT','2026-06-21 17:33:38',NULL,NULL,'PENDING','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (40,157,'WRONG_CELL','2026-08-26 01:12:38','2026-08-26 04:12:38','毛欢','RESOLVED','已现场处理');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (41,165,'TIMEOUT','2026-06-17 08:07:38',NULL,NULL,'PENDING','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (42,169,'OVERWEIGHT','2026-09-02 12:50:38','2026-09-02 13:50:38','陈坤','RESOLVED','已现场处理');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (43,170,'TIMEOUT','2026-08-11 23:58:38',NULL,NULL,'PENDING','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (44,179,'TIMEOUT','2026-07-11 17:36:38',NULL,NULL,'PENDING','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (45,184,'RETURNED','2026-08-22 01:16:38','2026-08-22 07:16:38','卞杨','AUTO_RETURNED','系统自动退回');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (46,186,'OVERWEIGHT','2026-08-11 18:46:38','2026-08-12 18:46:38','马红梅','RESOLVED','已现场处理');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (47,187,'RETURNED','2026-08-20 23:51:38','2026-08-21 05:51:38','秦健','AUTO_RETURNED','系统自动退回');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (48,196,'TIMEOUT','2026-09-23 10:05:38',NULL,NULL,'RESOLVED','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (49,200,'TIMEOUT','2026-07-13 21:00:38',NULL,NULL,'RESOLVED','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (50,202,'RETURNED','2026-06-09 18:26:38','2026-06-10 00:26:38','杨金凤','AUTO_RETURNED','系统自动退回');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (51,204,'TIMEOUT','2026-06-22 23:04:38',NULL,NULL,'PENDING','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (52,208,'OVERWEIGHT','2026-07-25 12:52:38','2026-07-25 22:52:38','蔡林','RESOLVED','已现场处理');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (53,214,'OVERWEIGHT','2026-07-25 08:14:38','2026-07-25 19:14:38','路想','RESOLVED','已现场处理');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (54,219,'TIMEOUT','2026-06-20 02:07:38',NULL,NULL,'RESOLVED','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (55,232,'DAMAGED','2026-09-19 15:38:38','2026-09-19 16:38:38','陆婷','RESOLVED','已现场处理');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (56,245,'TIMEOUT','2026-08-23 17:27:38',NULL,NULL,'PENDING','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (57,250,'TIMEOUT','2026-09-26 04:03:38',NULL,NULL,'RESOLVED','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (58,252,'RETURNED','2026-08-17 06:49:38','2026-08-17 12:49:38','胡兰英','AUTO_RETURNED','系统自动退回');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (59,255,'DAMAGED','2026-06-22 10:32:38','2026-06-23 02:32:38','王岩','RESOLVED','已现场处理');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (60,257,'TIMEOUT','2026-09-08 03:25:38',NULL,NULL,'PENDING','超时未取');
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (61,68,'WRONG_CELL','2026-08-30 01:50:38','2026-08-30 04:50:38','韦玉','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (62,106,'DAMAGED','2026-08-21 01:57:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (63,68,'MISSED','2026-08-30 23:50:38','2026-08-31 17:50:38','萧旭','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (64,74,'DAMAGED','2026-09-15 10:21:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (65,45,'RETURNED','2026-06-30 16:27:38','2026-06-30 21:27:38','吴琴','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (66,78,'RETURNED','2026-09-24 04:50:38','2026-09-25 11:50:38','周宁','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (67,80,'RETURNED','2026-08-22 14:17:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (68,149,'OVERWEIGHT','2026-06-18 20:33:38','2026-06-19 21:33:38','蔡晨','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (69,219,'MISSED','2026-06-19 22:07:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (70,56,'MISSED','2026-08-07 03:35:38','2026-08-07 07:35:38','陈林','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (71,184,'RETURNED','2026-08-18 07:16:38','2026-08-19 07:16:38','杨红霞','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (72,119,'WRONG_CELL','2026-06-12 19:28:38','2026-06-13 21:28:38','龙柳','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (73,56,'OVERWEIGHT','2026-08-07 16:35:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (74,174,'DAMAGED','2026-09-29 12:52:38','2026-09-30 11:52:38','王玉','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (75,86,'WRONG_CELL','2026-09-08 05:37:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (76,72,'WRONG_CELL','2026-09-20 02:08:38','2026-09-20 19:08:38','王红','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (77,71,'OVERWEIGHT','2026-06-29 13:27:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (78,109,'RETURNED','2026-07-09 22:21:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (79,188,'DAMAGED','2026-07-21 05:08:38','2026-07-21 06:08:38','叶倩','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (80,184,'WRONG_CELL','2026-08-18 11:16:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (81,178,'DAMAGED','2026-08-27 10:01:38','2026-08-27 12:01:38','孔彬','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (82,195,'MISSED','2026-07-16 00:21:38','2026-07-17 11:21:38','苏柳','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (83,79,'TIMEOUT','2026-07-21 21:12:38','2026-07-22 02:12:38','尤彬','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (84,97,'TIMEOUT','2026-08-26 02:17:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (85,76,'TIMEOUT','2026-06-22 19:52:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (86,48,'WRONG_CELL','2026-09-15 11:38:38','2026-09-15 19:38:38','韦超','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (87,136,'TIMEOUT','2026-09-29 08:52:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (88,24,'TIMEOUT','2026-07-16 00:26:38','2026-07-16 09:26:38','白佳','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (89,28,'TIMEOUT','2026-09-29 18:52:38','2026-09-30 05:52:38','杨凯','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (90,65,'TIMEOUT','2026-06-08 06:32:38','2026-06-08 13:32:38','李瑜','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (91,76,'MISSED','2026-06-22 21:52:38','2026-06-22 23:52:38','刘敏','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (92,161,'TIMEOUT','2026-08-01 23:50:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (93,205,'DAMAGED','2026-07-27 11:52:38','2026-07-28 10:52:38','潘想','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (94,6,'TIMEOUT','2026-08-08 08:45:38','2026-08-08 09:45:38','武婷婷','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (95,224,'WRONG_CELL','2026-09-29 06:52:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (96,200,'TIMEOUT','2026-07-12 16:00:38','2026-07-13 00:00:38','王艳','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (97,130,'MISSED','2026-08-05 19:17:38','2026-08-06 23:17:38','王敏','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (98,173,'DAMAGED','2026-09-19 04:01:38','2026-09-20 07:01:38','吴桂芝','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (99,230,'OVERWEIGHT','2026-06-18 17:55:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (100,127,'WRONG_CELL','2026-07-14 12:01:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (101,94,'TIMEOUT','2026-09-29 17:43:38','2026-09-29 19:43:38','王建军','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (102,12,'OVERWEIGHT','2026-09-29 20:52:38','2026-09-30 22:52:38','张彬','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (103,71,'MISSED','2026-06-29 13:27:38','2026-06-29 19:27:38','马建国','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (104,143,'TIMEOUT','2026-07-30 13:17:38','2026-07-30 22:17:38','朱金凤','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (105,227,'TIMEOUT','2026-07-25 00:51:38','2026-07-25 12:51:38','谢畅','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (106,26,'DAMAGED','2026-09-22 15:00:38','2026-09-22 21:00:38','刘玉梅','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (107,159,'DAMAGED','2026-06-30 23:59:38','2026-07-02 10:59:38','高小红','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (108,198,'OVERWEIGHT','2026-08-28 12:20:38','2026-08-28 23:20:38','杜秀珍','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (109,226,'OVERWEIGHT','2026-08-30 21:17:38','2026-09-01 05:17:38','傅畅','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (110,84,'MISSED','2026-09-10 17:42:38','2026-09-12 02:42:38','陆俊','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (111,114,'OVERWEIGHT','2026-09-04 14:54:38','2026-09-05 10:54:38','袁明','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (112,123,'DAMAGED','2026-06-27 10:41:38','2026-06-28 01:41:38','刘峰','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (113,170,'OVERWEIGHT','2026-08-10 16:58:38','2026-08-11 21:58:38','徐春梅','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (114,86,'DAMAGED','2026-09-08 18:37:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (115,137,'DAMAGED','2026-06-08 06:42:38','2026-06-08 15:42:38','李玉梅','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (116,195,'OVERWEIGHT','2026-07-16 15:21:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (117,128,'WRONG_CELL','2026-08-08 07:53:38','2026-08-09 07:53:38','何淑英','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (118,120,'WRONG_CELL','2026-06-05 17:02:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (119,188,'DAMAGED','2026-07-20 15:08:38','2026-07-21 23:08:38','何帆','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (120,160,'OVERWEIGHT','2026-09-29 03:52:38','2026-09-30 08:52:38','张娜','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (121,109,'MISSED','2026-07-09 20:21:38','2026-07-10 14:21:38','张琴','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (122,198,'WRONG_CELL','2026-08-28 04:20:38','2026-08-28 17:20:38','曹桂芝','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (123,53,'OVERWEIGHT','2026-09-29 13:52:38','2026-09-29 23:52:38','陈瑞','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (124,220,'RETURNED','2026-09-14 16:44:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (125,173,'WRONG_CELL','2026-09-18 21:01:38','2026-09-19 07:01:38','杨秀华','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (126,9,'MISSED','2026-06-22 12:41:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (127,131,'MISSED','2026-07-17 16:37:38','2026-07-18 00:37:38','包丽华','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (128,19,'OVERWEIGHT','2026-09-29 11:14:38','2026-09-30 02:14:38','张桂芝','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (129,114,'TIMEOUT','2026-09-03 12:54:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (130,209,'TIMEOUT','2026-09-29 09:52:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (131,112,'OVERWEIGHT','2026-06-28 01:50:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (132,223,'OVERWEIGHT','2026-08-10 03:07:38','2026-08-10 16:07:38','黄坤','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (133,188,'MISSED','2026-07-19 17:08:38','2026-07-20 17:08:38','陈梅','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (134,175,'RETURNED','2026-09-29 11:52:38','2026-09-30 22:52:38','张波','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (135,34,'WRONG_CELL','2026-09-29 13:52:38','2026-09-29 21:52:38','陈婷婷','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (136,36,'DAMAGED','2026-09-29 18:52:38','2026-09-30 14:52:38','钱强','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (137,89,'OVERWEIGHT','2026-08-30 05:18:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (138,179,'DAMAGED','2026-07-09 02:36:38','2026-07-10 09:36:38','陶想','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (139,222,'WRONG_CELL','2026-08-14 23:29:38','2026-08-15 19:29:38','朱春梅','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (140,193,'WRONG_CELL','2026-09-29 17:19:38','2026-09-30 17:19:38','苏雷','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (141,94,'WRONG_CELL','2026-09-29 11:52:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (142,222,'DAMAGED','2026-08-14 16:29:38','2026-08-15 23:29:38','韩阳','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (143,242,'DAMAGED','2026-06-27 06:59:38','2026-06-28 01:59:38','殷鹏','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (144,67,'OVERWEIGHT','2026-07-18 10:15:38','2026-07-19 17:15:38','赵楠','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (145,117,'WRONG_CELL','2026-09-08 23:54:38','2026-09-09 19:54:38','张建国','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (146,223,'OVERWEIGHT','2026-08-10 06:07:38','2026-08-11 11:07:38','郑宇','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (147,44,'MISSED','2026-08-19 05:37:38','2026-08-19 07:37:38','戴秀兰','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (148,153,'WRONG_CELL','2026-09-29 10:05:38','2026-09-29 16:05:38','张华','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (149,216,'OVERWEIGHT','2026-06-29 06:49:38','2026-06-29 20:49:38','罗东','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (150,193,'RETURNED','2026-09-28 23:52:38','2026-09-29 23:52:38','田丽华','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (151,228,'WRONG_CELL','2026-09-29 04:59:38','2026-09-29 05:59:38','何彬','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (152,257,'DAMAGED','2026-09-06 04:25:38','2026-09-06 14:25:38','王欣','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (153,218,'OVERWEIGHT','2026-08-02 06:25:38','2026-08-03 02:25:38','林建平','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (154,41,'WRONG_CELL','2026-09-20 12:00:38','2026-09-21 22:00:38','曾桂香','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (155,55,'DAMAGED','2026-09-13 05:17:38','2026-09-13 16:17:38','王文','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (156,85,'MISSED','2026-09-03 07:20:38','2026-09-04 01:20:38','杨伟','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (157,219,'OVERWEIGHT','2026-06-19 11:07:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (158,15,'DAMAGED','2026-09-02 03:39:38','2026-09-02 21:39:38','刘秀华','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (159,253,'RETURNED','2026-08-26 22:22:38','2026-08-28 02:22:38','张桂香','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (160,38,'DAMAGED','2026-08-09 04:08:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (161,71,'MISSED','2026-06-29 02:27:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (162,169,'DAMAGED','2026-09-03 23:50:38','2026-09-05 11:50:38','黄红','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (163,56,'TIMEOUT','2026-08-08 12:35:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (164,60,'MISSED','2026-07-09 09:47:38','2026-07-10 05:47:38','蔡倩','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (165,221,'MISSED','2026-09-29 11:52:38','2026-09-30 17:52:38','周建平','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (166,185,'OVERWEIGHT','2026-09-29 14:27:38','2026-09-30 22:27:38','马静','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (167,68,'OVERWEIGHT','2026-08-30 17:50:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (168,182,'WRONG_CELL','2026-07-07 09:22:38','2026-07-08 18:22:38','冯淑珍','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (169,241,'MISSED','2026-09-20 09:57:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (170,71,'OVERWEIGHT','2026-06-28 11:27:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (171,121,'OVERWEIGHT','2026-07-22 23:02:38','2026-07-23 14:02:38','杜斌','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (172,140,'WRONG_CELL','2026-09-29 02:52:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (173,86,'RETURNED','2026-09-07 20:37:38','2026-09-08 03:37:38','李华','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (174,248,'DAMAGED','2026-09-08 09:04:38','2026-09-09 03:04:38','张杰','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (175,47,'RETURNED','2026-09-29 08:52:38','2026-09-30 12:52:38','乔旭','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (176,8,'RETURNED','2026-07-17 07:00:38','2026-07-18 19:00:38','项丹丹','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (177,178,'OVERWEIGHT','2026-08-27 11:01:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (178,46,'DAMAGED','2026-07-30 05:55:38','2026-07-31 15:55:38','邓桂花','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (179,74,'MISSED','2026-09-15 07:21:38','2026-09-16 00:21:38','梅莉','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (180,56,'DAMAGED','2026-08-07 14:35:38','2026-08-09 01:35:38','张秀梅','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (181,129,'MISSED','2026-08-04 18:56:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (182,10,'OVERWEIGHT','2026-06-26 21:50:38','2026-06-27 19:50:38','刘玉梅','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (183,44,'WRONG_CELL','2026-08-19 20:37:38','2026-08-21 01:37:38','钟艳','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (184,243,'MISSED','2026-07-03 17:10:38','2026-07-04 02:10:38','亓彬','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (185,100,'WRONG_CELL','2026-09-01 03:59:38','2026-09-01 19:59:38','张畅','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (186,54,'RETURNED','2026-09-05 02:18:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (187,130,'MISSED','2026-08-06 02:17:38','2026-08-06 15:17:38','毛冬梅','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (188,140,'RETURNED','2026-09-29 19:26:38','2026-09-30 12:26:38','左萍','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (189,59,'OVERWEIGHT','2026-09-07 17:16:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (190,122,'TIMEOUT','2026-09-02 12:02:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (191,82,'WRONG_CELL','2026-09-10 22:12:38','2026-09-11 06:12:38','卢佳','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (192,112,'OVERWEIGHT','2026-06-27 09:50:38','2026-06-28 12:50:38','宋桂芳','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (193,18,'OVERWEIGHT','2026-07-30 16:19:38','2026-07-30 20:19:38','李雷','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (194,243,'MISSED','2026-07-03 21:10:38','2026-07-04 02:10:38','王雷','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (195,52,'WRONG_CELL','2026-08-29 07:19:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (196,61,'WRONG_CELL','2026-09-28 23:52:38','2026-09-30 09:52:38','宋丽丽','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (197,99,'MISSED','2026-08-26 16:45:38','2026-08-27 06:45:38','文秀云','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (198,183,'WRONG_CELL','2026-06-25 02:52:38','2026-06-25 11:52:38','罗桂芳','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (199,159,'WRONG_CELL','2026-06-30 14:59:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (200,199,'TIMEOUT','2026-08-14 14:38:38','2026-08-14 20:38:38','高杨','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (201,127,'WRONG_CELL','2026-07-13 10:01:38','2026-07-14 18:01:38','刘超','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (202,70,'TIMEOUT','2026-06-21 11:50:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (203,120,'DAMAGED','2026-06-06 22:02:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (204,150,'RETURNED','2026-07-19 10:20:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (205,8,'OVERWEIGHT','2026-07-16 22:00:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (206,179,'RETURNED','2026-07-09 21:36:38','2026-07-10 20:36:38','金凤英','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (207,220,'DAMAGED','2026-09-15 06:44:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (208,120,'RETURNED','2026-06-06 14:02:38','2026-06-07 17:02:38','李秀芳','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (209,239,'OVERWEIGHT','2026-09-29 06:52:38','2026-09-29 13:52:38','魏琴','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (210,147,'MISSED','2026-08-19 05:11:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (211,103,'WRONG_CELL','2026-08-20 09:13:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (212,250,'TIMEOUT','2026-09-24 08:03:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (213,130,'WRONG_CELL','2026-08-04 09:17:38','2026-08-04 18:17:38','谢瑞','AUTO_RETURNED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (214,89,'OVERWEIGHT','2026-08-29 11:18:38','2026-08-29 15:18:38','封龙','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (215,83,'MISSED','2026-09-29 06:52:38','2026-09-29 09:52:38','陈金凤','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (216,209,'DAMAGED','2026-09-29 01:52:38','2026-09-29 14:52:38','彭娟','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (217,147,'RETURNED','2026-08-18 07:11:38','2026-08-18 19:11:38','张凤兰','RESOLVED',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (218,81,'MISSED','2026-06-14 16:03:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (219,75,'TIMEOUT','2026-08-30 19:27:38',NULL,NULL,'PENDING',NULL);
INSERT INTO `t_exception_log` (`exception_id`,`package_id`,`exception_type`,`occur_time`,`handle_time`,`handler`,`handle_result`,`remark`) VALUES (220,253,'DAMAGED','2026-08-27 14:22:38','2026-08-28 18:22:38','原东','RESOLVED',NULL);

-- ----- 数据 t_pay_callback_log -----
INSERT INTO `t_pay_callback_log` (`log_id`,`pay_id`,`pay_no`,`trade_no`,`idem_key`,`provider`,`trade_status`,`verify_ok`,`amount_ok`,`applied`,`result`,`reason`,`raw_payload`,`created_at`) VALUES (8,NULL,'P99999999999','T1','P99999999999:T1','alipay_sandbox','TRADE_SUCCESS',1,0,0,'IGNORED','商户订单号不存在','{\'out_trade_no\': \'P99999999999\', \'trade_no\': \'T1\', \'trade_status\': \'TRADE_SUCCESS\', \'total_amount\': \'1.00\'}','2026-11-18 20:00:33');

SET FOREIGN_KEY_CHECKS=1;

-- ----- 视图 / 触发器 / 存储过程 -----
-- 对象定义来自 db/objects.sql（squash 后随快照一起分发，确保一次导入即完整）
-- ============================================================================
-- 智能快递柜管理系统  ·  数据库对象 (视图 / 触发器 / 存储过程)
-- 依赖 schema.sql 已执行。本文件各对象之间以专属标记分隔，
-- 供初始化脚本按块执行（每条 CREATE 作为独立语句提交，无需 DELIMITER）。
-- ============================================================================

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
