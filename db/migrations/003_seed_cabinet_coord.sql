-- ============================================================================
-- 创新点 3 演示种子：柜体经纬度（后续接入高德/北斗定位时由管理端维护）
-- ----------------------------------------------------------------------------
-- 说明：
--   · 坐标采用 WGS84 十进制度，DECIMAL(9,6) 精度约 0.11m，足够柜体定位。
--   · 演示数据取北京（1-15 号柜）与上海（16-30 号柜）两簇真实可用坐标，
--     每簇内部有几百米到几公里的偏移，便于验证「附近柜机距离排序」有区分度。
--   · 幂等：只更新仍为 NULL 的行，重复执行不会覆盖管理端后续手工维护的坐标。
-- 重放：mysql -u root -p < db/migrations/003_seed_cabinet_coord.sql
-- ============================================================================
USE `smart_locker`;

-- 北京簇：以天安门(39.908722, 116.397499)为中心，半径约 0.5~9km 散布
UPDATE t_cabinet SET latitude = 39.908722, longitude = 116.397499 WHERE cabinet_id = 1  AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 39.914512, longitude = 116.403871 WHERE cabinet_id = 2  AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 39.929986, longitude = 116.389310 WHERE cabinet_id = 3  AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 39.899430, longitude = 116.414020 WHERE cabinet_id = 4  AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 39.954120, longitude = 116.352180 WHERE cabinet_id = 5  AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 39.937480, longitude = 116.460210 WHERE cabinet_id = 6  AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 39.868690, longitude = 116.379150 WHERE cabinet_id = 7  AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 39.981520, longitude = 116.403120 WHERE cabinet_id = 8  AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 39.911230, longitude = 116.453780 WHERE cabinet_id = 9  AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 39.882640, longitude = 116.342160 WHERE cabinet_id = 10 AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 40.006910, longitude = 116.381220 WHERE cabinet_id = 11 AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 39.925400, longitude = 116.488150 WHERE cabinet_id = 12 AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 39.895170, longitude = 116.436910 WHERE cabinet_id = 13 AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 39.969830, longitude = 116.413560 WHERE cabinet_id = 14 AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 39.942330, longitude = 116.331120 WHERE cabinet_id = 15 AND latitude IS NULL;

-- 上海簇：以人民广场(31.230416, 121.473701)为中心
UPDATE t_cabinet SET latitude = 31.230416, longitude = 121.473701 WHERE cabinet_id = 16 AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 31.235870, longitude = 121.480920 WHERE cabinet_id = 17 AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 31.219640, longitude = 121.462180 WHERE cabinet_id = 18 AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 31.245210, longitude = 121.447360 WHERE cabinet_id = 19 AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 31.207480, longitude = 121.491530 WHERE cabinet_id = 20 AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 31.259340, longitude = 121.521870 WHERE cabinet_id = 21 AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 31.198820, longitude = 121.431290 WHERE cabinet_id = 22 AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 31.240950, longitude = 121.542460 WHERE cabinet_id = 23 AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 31.223180, longitude = 121.412730 WHERE cabinet_id = 24 AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 31.268470, longitude = 121.469120 WHERE cabinet_id = 25 AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 31.191260, longitude = 121.508940 WHERE cabinet_id = 26 AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 31.251030, longitude = 121.436580 WHERE cabinet_id = 27 AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 31.214470, longitude = 121.531720 WHERE cabinet_id = 28 AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 31.277950, longitude = 121.485330 WHERE cabinet_id = 29 AND latitude IS NULL;
UPDATE t_cabinet SET latitude = 31.203610, longitude = 121.452140 WHERE cabinet_id = 30 AND latitude IS NULL;

-- 校验：应输出 0 行
-- SELECT cabinet_id, cabinet_code, location FROM t_cabinet WHERE latitude IS NULL OR longitude IS NULL;
