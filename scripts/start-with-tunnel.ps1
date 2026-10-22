# ============================================================================
# 一键启动：Flask + cloudflared 内网穿透
# ----------------------------------------------------------------------------
# 为什么需要它：
#   校园网/公共 Wi-Fi 普遍开了 AP 隔离（客户端之间不能互访），手机扫柜机屏幕上的
#   局域网地址（http://10.x.x.x:5000）会一直转圈打不开。这不是代码能绕过的限制，
#   必须让手机走**公网**回来 —— 内网穿透把本机端口映射成一个公网 HTTPS 域名。
#
# 它做的事：
#   1) 启动 Flask（后台进程），等 /api/health 就绪；
#   2) 启动 cloudflared 快速隧道，从日志里抓出 https://xxx.trycloudflare.com；
#   3) 把该地址写进 logs/public_base_url.txt —— 柜机建二维码时会优先读它，
#      于是二维码内容自动变成公网地址，手机用流量也能扫开（不需要重启 Flask）。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\start-with-tunnel.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\start-with-tunnel.ps1 -Port 8000
#   powershell -ExecutionPolicy Bypass -File scripts\start-with-tunnel.ps1 -NoTunnel   # 只起服务
#
# 前置：下载 cloudflared.exe 放进 scripts\ 目录或加入 PATH
#       https://github.com/cloudflare/cloudflared/releases/latest
# ============================================================================
param(
    [int]$Port = 5000,
    [switch]$NoTunnel
)

$ErrorActionPreference = "Stop"

# 若环境里同时存在 HTTPS_PROXY 与 https_proxy（仅大小写不同的同名变量），
# 进程启动与 Env: 提供程序会抛"已添加了具有相同键的项"。这两个代理变量对本脚本
# 无用（Flask 与 cloudflared 都直连），先清掉再启动进程，避免踩这个坑。
foreach ($n in @("http_proxy", "https_proxy", "all_proxy", "no_proxy")) {
    try { [Environment]::SetEnvironmentVariable($n, $null) } catch { }
}
$root = Split-Path -Parent $PSScriptRoot
$logs = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

$baseFile = Join-Path $logs "public_base_url.txt"
if (Test-Path $baseFile) { Remove-Item $baseFile -Force }   # 清掉上次的隧道地址

function Write-Step($msg) { Write-Host "[*] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "[+] $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "[!] $msg" -ForegroundColor Yellow }

# ---- 1) 选解释器：优先项目虚拟环境 ----
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $py = "python"
    Write-Warn2 "未找到 .venv，使用系统 python（依赖需自行安装）"
}

# ---- 2) 启动 Flask ----
$env:PORT = "$Port"
$appOut = Join-Path $logs "server.log"
$appErr = Join-Path $logs "server.err.log"
Write-Step "启动 Flask（端口 $Port）…"
$flask = Start-Process -FilePath $py -ArgumentList "backend/app.py" `
    -WorkingDirectory $root -RedirectStandardOutput $appOut `
    -RedirectStandardError $appErr -PassThru -WindowStyle Hidden

# 等健康检查通过（最多 20 秒）
$healthy = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $healthy = $true; break }
    } catch { }
}
if (-not $healthy) {
    Write-Host "[x] 服务未能启动，请查看 logs\server.err.log" -ForegroundColor Red
    if (-not $flask.HasExited) { Stop-Process -Id $flask.Id -Force }
    exit 1
}
Write-Ok "服务已就绪：http://127.0.0.1:$Port"

# 局域网地址（同一 Wi-Fi 且未开 AP 隔离时可用）
$lanIp = (Get-NetIPAddress -AddressFamily IPv4 |
          Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
          Select-Object -First 1).IPAddress
if ($lanIp) { Write-Host "    局域网访问：http://${lanIp}:$Port  （柜机用这个地址打开）" }

if ($NoTunnel) {
    Write-Warn2 "已指定 -NoTunnel，跳过内网穿透。柜机二维码将使用局域网地址。"
    Write-Host "按 Ctrl+C 结束。" -ForegroundColor DarkGray
    Wait-Process -Id $flask.Id
    exit 0
}

# ---- 3) 找 cloudflared ----
$cfPath = Join-Path $PSScriptRoot "cloudflared.exe"
if (-not (Test-Path $cfPath)) {
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) { $cfPath = $cmd.Source }
}
if (-not (Test-Path $cfPath)) {
    Write-Warn2 "未找到 cloudflared，跳过内网穿透（手机只能在同一 Wi-Fi 下访问）。"
    Write-Host "    下载：https://github.com/cloudflare/cloudflared/releases/latest" -ForegroundColor DarkGray
    Write-Host "    放到 scripts\cloudflared.exe 或加入 PATH 后重跑本脚本即可。" -ForegroundColor DarkGray
    Wait-Process -Id $flask.Id
    exit 0
}

# ---- 4) 起隧道并抓公网地址 ----
$cfLog = Join-Path $logs "cloudflared.log"
if (Test-Path $cfLog) { Remove-Item $cfLog -Force }
Write-Step "启动 cloudflared 隧道…"
$cf = Start-Process -FilePath $cfPath `
    -ArgumentList "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:$Port" `
    -RedirectStandardOutput $cfLog -RedirectStandardError "$cfLog.err" `
    -PassThru -WindowStyle Hidden

$public = $null
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    foreach ($f in @($cfLog, "$cfLog.err")) {
        if (Test-Path $f) {
            $m = Select-String -Path $f -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -AllMatches |
                 Select-Object -First 1
            if ($m) { $public = $m.Matches[0].Value; break }
        }
    }
    if ($public) { break }
    if ($cf.HasExited) { break }
}

if (-not $public) {
    Write-Warn2 "隧道未拿到公网地址（可能是网络受限）。柜机二维码将退回局域网地址。"
    Write-Host "    日志：$cfLog" -ForegroundColor DarkGray
    Wait-Process -Id $flask.Id
    exit 0
}

# 关键一步：把公网地址交给后端，二维码内容随之变成公网地址
Set-Content -Path $baseFile -Value $public -Encoding ASCII
Write-Ok "公网地址：$public"
Write-Host ""
Write-Host "==================== 手机访问地址 ====================" -ForegroundColor White
Write-Host "  手机端：  $public/m" -ForegroundColor Yellow
Write-Host "  柜机端：  $public/   （本机也可继续用 http://127.0.0.1:$Port）" -ForegroundColor Yellow
Write-Host "======================================================" -ForegroundColor White
Write-Host "柜机首页二维码已指向公网地址，手机用流量即可扫码。" -ForegroundColor Green
Write-Host "按 Ctrl+C 结束（会同时关闭隧道与服务）。" -ForegroundColor DarkGray

try {
    Wait-Process -Id $flask.Id
} finally {
    if ($cf -and -not $cf.HasExited) { Stop-Process -Id $cf.Id -Force }
    if (Test-Path $baseFile) { Remove-Item $baseFile -Force }
    Write-Host "已停止。" -ForegroundColor DarkGray
}
