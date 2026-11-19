import io, os, re, sys
out = []
ut = sys.argv[1]
skipped, failed, total = [], [], 0
if os.path.exists(ut):
    txt = io.open(ut, encoding='utf-8', errors='replace').read()
    for line in txt.splitlines():
        if re.search(r'\.\.\. skipped', line) or re.search(r'\bskipped ', line):
            skipped.append(line.strip())
        if line.startswith('FAIL:') or line.startswith('ERROR:'):
            failed.append(line.strip())
    m = re.search(r'Ran (\d+) tests?', txt)
    if m:
        total = int(m.group(1))
out.append('# 跳过项清单（由 run_all.ps1 自动生成，数据源：01_unittest.txt）')
out.append('')
out.append('总用例数(Ran)      : %d' % total)
out.append('被跳过(skipped)    : %d' % len(skipped))
out.append('失败/错误(FAIL/ERROR): %d' % len(failed))
out.append('')
if skipped:
    out.append('## 被跳过用例（不计入通过，原因逐条列出）')
    for s in skipped:
        out.append('  ' + s)
else:
    out.append('## 被跳过用例')
    out.append('  本次运行无 skipped 用例。')
    out.append('  说明：测试内的整类跳过条件是 skipUnless(_db_ready())，即"MySQL 不可用时整类跳过"。')
    out.append('  本次 MySQL(smart_locker) 可用，故未触发跳过。')
if failed:
    out.append('')
    out.append('## 失败/错误用例（必须修复，不能算作通过）')
    for s in failed:
        out.append('  ' + s)
io.open(sys.argv[2], 'w', encoding='utf-8').write('\n'.join(out) + '\n')
print('\n'.join(out))
