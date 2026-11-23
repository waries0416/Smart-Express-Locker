# Smart Express Locker - start Flask with .env auto-loaded.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\start-with-env.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root ".env"
$pythonExe = "C:\Users\31189\AppData\Local\Programs\Python\Python312\python.exe"

Write-Output "=== Smart Express Locker (loading .env) ==="

if (-not (Test-Path $envFile)) {
    Write-Output "[!] .env not found. Copy .env.example to .env first."
    exit 1
}

# Parse .env line by line: skip blanks and comments, inject KEY=VALUE into process env.
$lines = Get-Content $envFile -Encoding UTF8
foreach ($line in $lines) {
    $t = $line.Trim()
    if ($t -eq "" -or $t.StartsWith("#")) { continue }
    $idx = $t.IndexOf("=")
    if ($idx -le 0) { continue }
    $key = $t.Substring(0, $idx).Trim()
    $val = $t.Substring($idx + 1).Trim()
    if ($val.Length -ge 2) {
        $first = $val.Substring(0, 1)
        $last = $val.Substring($val.Length - 1, 1)
        if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
            $val = $val.Substring(1, $val.Length - 2)
        }
    }
    [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
}

# Show config summary (never print secret values, only set/unset).
$checks = [ordered]@{
    "DeepSeek" = "DEEPSEEK_API_KEY"
    "AMAP_JS"  = "AMAP_JS_KEY"
    "AMAP_WEB" = "AMAP_WEB_KEY"
    "Alipay"   = "ALIPAY_APP_ID"
}
foreach ($name in $checks.Keys) {
    $v = [System.Environment]::GetEnvironmentVariable($checks[$name], "Process")
    $state = if ([string]::IsNullOrWhiteSpace($v)) { "NOT SET (will degrade)" } else { "SET" }
    Write-Output ("  {0,-10}: {1}" -f $name, $state)
}

$prov = [System.Environment]::GetEnvironmentVariable("PAYMENT_PROVIDER", "Process")
Write-Output ("  PAYMENT   : {0}" -f $(if ($prov) { $prov } else { "mock" }))
Write-Output "---"
Write-Output "  Kiosk : http://127.0.0.1:5000/"
Write-Output "  Admin : http://127.0.0.1:5000/admin  (admin/admin123)"
Write-Output "  Mobile: http://127.0.0.1:5000/m"
Write-Output "---"

Set-Location $root
& $pythonExe backend\app.py
