# Alpha Engine — Safe Server Launch Script
# Clears zombie processes on port 8000 before starting uvicorn.
# Run from alpha_engine/ root:
#   powershell -ExecutionPolicy Bypass -File scripts\start_server.ps1

$targetPort  = 8000
$projectRoot = "C:\Users\LOQ\OneDrive\Desktop\agentic-RAG\alpha_engine"

Write-Host ""
Write-Host "=== Alpha Engine Server Launcher ===" -ForegroundColor Cyan

# Step 1: Clear any zombie process holding port 8000
$connections = Get-NetTCPConnection -LocalPort $targetPort -ErrorAction SilentlyContinue
if ($connections) {
    $pids = $connections | Select-Object -ExpandProperty OwningProcess | Sort-Object -Unique
    foreach ($p in $pids) {
        Write-Host "Clearing zombie process PID $p from port $targetPort..." -ForegroundColor Yellow
        taskkill /F /PID $p 2>$null | Out-Null
    }
    Start-Sleep -Seconds 1
    Write-Host "Port $targetPort cleared." -ForegroundColor Green
} else {
    Write-Host "Port $targetPort is free." -ForegroundColor Green
}

# Step 2: Activate venv
$venvActivate = Join-Path $projectRoot "backend\.venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
    & $venvActivate
    Write-Host "Virtual environment activated." -ForegroundColor Green
} else {
    Write-Host "WARNING: venv not found at $venvActivate" -ForegroundColor Yellow
}

# Step 3: Launch uvicorn (no --reload in local dev to prevent mid-ingest cancellation)
Set-Location $projectRoot
Write-Host "Starting uvicorn on http://127.0.0.1:$targetPort ..." -ForegroundColor Green
Write-Host ""
python -m uvicorn backend.main:app --host 127.0.0.1 --port $targetPort
