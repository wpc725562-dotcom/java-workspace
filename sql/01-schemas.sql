-- =============================================================================
--  java-workspace 数据库初始化脚本
--  -----------------------------------------------------------------------------
--  这一个文件同时被两种运行方式使用，保持单一事实来源：
--    · 便携版：`.runtime\` 里的 MySQL，用 `svc.sh init` / `svc.cmd init` 执行
--    · Docker：docker-compose 把本目录挂进 /docker-entrypoint-initdb.d（首启自动执行）
--
--  因此必须**幂等**（重复执行不报错），也不能依赖 MySQL 8 独有的语法，
--  因为 MySQL 5.7 容器/实例也会跑它。
-- =============================================================================

SET NAMES utf8mb4;

-- ---- P0：eladmin-mp ----
CREATE DATABASE IF NOT EXISTS `eladmin`
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---- P1：yu-ai-agent ----
CREATE DATABASE IF NOT EXISTS `yu_ai_agent`
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---- P2：mall-swarm ----
CREATE DATABASE IF NOT EXISTS `mall`
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---- P3：seckill ----
CREATE DATABASE IF NOT EXISTS `seckill`
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- =============================================================================
--  业务账号
--  -----------------------------------------------------------------------------
--  为什么不直接用 root：项目配置文件里迟早要写数据库密码，
--  万一那份配置被提交进 git，暴露 root 的爆炸半径比暴露一个受限账号大得多。
--
--  5.7 和 8.0 的差异用一个动态 SQL 抹平：
--    8.0 新建用户默认用 caching_sha2_password，老 JDBC 驱动不认，
--        必须显式指定 mysql_native_password；
--    5.7 不认识 WITH 子句，得走普通写法。
-- =============================================================================

SET @is_mysql8 = (SELECT VERSION() LIKE '8.%' OR VERSION() LIKE '9.%');

SET @sql_create_dev = IF(@is_mysql8,
  'CREATE USER IF NOT EXISTS ''dev''@''%'' IDENTIFIED WITH mysql_native_password BY ''dev123456''',
  'CREATE USER IF NOT EXISTS ''dev''@''%'' IDENTIFIED BY ''dev123456'''
);
PREPARE stmt FROM @sql_create_dev;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

GRANT ALL PRIVILEGES ON `eladmin`.*     TO 'dev'@'%';
GRANT ALL PRIVILEGES ON `yu_ai_agent`.* TO 'dev'@'%';
GRANT ALL PRIVILEGES ON `mall`.*        TO 'dev'@'%';
GRANT ALL PRIVILEGES ON `seckill`.*     TO 'dev'@'%';

-- 有些项目的初始化脚本会自己 CREATE DATABASE，给 dev 这个权限省得中途报错
GRANT CREATE ON *.* TO 'dev'@'%';

FLUSH PRIVILEGES;

SELECT
  VERSION()                                         AS mysql_version,
  'schemas: eladmin / yu_ai_agent / mall / seckill' AS created_schemas,
  'accounts: root/123456, dev/dev123456'            AS created_accounts;
