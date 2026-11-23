# -*- coding: utf-8 -*-
"""在临时库 tmp_delim_probe 上复现：mysql CLI 直接导入含 BEGIN..END 的触发器时是否报 1064。

只操作临时库，不触碰 smart_locker。用完由调用方 DROP。
"""
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

MYSQL = r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe"
DB = "tmp_delim_probe"

TRIGGER_NO_DELIMITER = """
CREATE TRIGGER trg_probe_after_update
AFTER UPDATE ON t_package
FOR EACH ROW
BEGIN
    IF NEW.status = 'PICKED' AND OLD.status <> 'PICKED' THEN
        UPDATE t_cell SET status = 'FREE' WHERE cell_id = NEW.cell_id;
    END IF;
END;
"""


def run(sql_text, label):
    p = subprocess.run(
        [MYSQL, "-uroot", "-p123456", DB],
        input=sql_text, text=True, capture_output=True, encoding="utf-8", errors="replace")
    print(f"--- {label} ---")
    print("  returncode:", p.returncode)
    err = (p.stderr or "").strip()
    # 去掉密码告警行，只看真正的错误
    lines = [l for l in err.splitlines() if "Using a password" not in l]
    print("  stderr:", "\n          ".join(lines) if lines else "(none)")
    return p.returncode, lines


def main():
    rc1, err1 = run(TRIGGER_NO_DELIMITER, "A) 不带 DELIMITER 的 CREATE TRIGGER（模拟 mysql < objects.sql）")

    # 对照组：带 DELIMITER
    with_delim = "DELIMITER $$\n" + TRIGGER_NO_DELIMITER.replace("END;", "END$$") + "\nDELIMITER ;\n"
    rc2, err2 = run(with_delim, "B) 带 DELIMITER 的同一触发器（对照组）")

    print()
    if any("1064" in l for l in err1):
        print("结论：复现成功 —— 缺 DELIMITER 时 mysql CLI 确实报 ERROR 1064，触发器静默丢失。")
    else:
        print("结论：未复现 1064（可能该 mysql 版本/客户端行为不同，需另行确认）。")
    print(f"对照：加 DELIMITER 后 returncode={rc2}（0 表示成功）")


main()
