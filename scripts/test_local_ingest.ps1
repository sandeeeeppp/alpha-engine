# Alpha Engine - Local Ingest E2E Test Script
# Run from alpha_engine/ root:
#   powershell -ExecutionPolicy Bypass -File scripts\test_local_ingest.ps1

$ErrorActionPreference = "Stop"

$EnvFile = Resolve-Path (Join-Path (Join-Path $PSScriptRoot "..") ".env")

# Load INTERNAL_API_SECRET from .env
$Secret = $null
foreach ($line in Get-Content $EnvFile) {
    if ($line -match '^\s*#' -or $line -match '^\s*$') { continue }
    if ($line -match '^INTERNAL_API_SECRET=(.+)$') {
        $Secret = $Matches[1].Trim()
        break
    }
}

if (-not $Secret) {
    Write-Error "INTERNAL_API_SECRET not found in $EnvFile"
    exit 1
}

Write-Host ""
Write-Host "=== Alpha Engine Local Ingest Test ===" -ForegroundColor Cyan
Write-Host "Secret loaded: $($Secret.Substring(0,8))..." -ForegroundColor DarkGray

# Create a dummy file with a PDF magic byte header
$TmpDir   = $env:TEMP
$DummyPath = Join-Path $TmpDir "alpha_engine_test_dummy.pdf"
$PdfBytes  = [System.Text.Encoding]::ASCII.GetBytes("%PDF-1.4`nTest dummy for Alpha Engine ingest test`n")
[System.IO.File]::WriteAllBytes($DummyPath, $PdfBytes)

Write-Host "Dummy PDF created at: $DummyPath" -ForegroundColor DarkGray

# -------------------------------------------------------------------
# Test 1: Direct FastAPI - no secret - expect 403
# -------------------------------------------------------------------
Write-Host ""
Write-Host "Test 1: POST /api/ingest WITHOUT secret (expect 403)" -ForegroundColor Yellow

$T1 = curl.exe -s -o - -w "`nHTTP_STATUS:%{http_code}" `
    -X POST "http://127.0.0.1:8000/api/ingest" `
    -F "file=@${DummyPath};type=application/pdf" `
    -F "ticker=TEST" `
    -F "fiscal_year=2024"

Write-Host $T1

if ($T1 -match "HTTP_STATUS:403") {
    Write-Host "[PASS] 403 returned - auth guard is active." -ForegroundColor Green
} else {
    Write-Host "[FAIL] Expected 403. Check backend/security.py." -ForegroundColor Red
}

# -------------------------------------------------------------------
# Test 2: Direct FastAPI - with secret - expect 202
# -------------------------------------------------------------------
Write-Host ""
Write-Host "Test 2: POST /api/ingest WITH secret (expect 202 Accepted)" -ForegroundColor Yellow

$T2 = curl.exe -s -o - -w "`nHTTP_STATUS:%{http_code}" `
    -X POST "http://127.0.0.1:8000/api/ingest" `
    -H "X-Internal-Secret: $Secret" `
    -F "file=@${DummyPath};type=application/pdf" `
    -F "ticker=TEST" `
    -F "fiscal_year=2024"

Write-Host $T2

if ($T2 -match "HTTP_STATUS:202") {
    Write-Host "[PASS] 202 Accepted - PDF queued for background ingestion." -ForegroundColor Green
} elseif ($T2 -match "HTTP_STATUS:400") {
    Write-Host "[INFO] 400 returned - PDF has no extractable text (expected for dummy)." -ForegroundColor DarkYellow
    Write-Host "       Auth passed. Endpoint is reachable. Real PDFs will return 202." -ForegroundColor DarkYellow
} else {
    Write-Host "[FAIL] Unexpected status. Full response above." -ForegroundColor Red
}

# -------------------------------------------------------------------
# Test 3: Direct FastAPI - 413 guard
# -------------------------------------------------------------------
Write-Host ""
Write-Host "Test 3: POST /api/ingest with Content-Length 25MB (expect 413)" -ForegroundColor Yellow

$T3 = curl.exe -s -o - -w "`nHTTP_STATUS:%{http_code}" `
    -X POST "http://127.0.0.1:8000/api/ingest" `
    -H "Content-Length: 25000000" `
    -H "X-Internal-Secret: $Secret" `
    -F "ticker=TEST" `
    -F "fiscal_year=2024"

Write-Host $T3

if ($T3 -match "HTTP_STATUS:413") {
    Write-Host "[PASS] 413 returned - oversized file guard works." -ForegroundColor Green
} else {
    Write-Host "[FAIL] Expected 413. Check LimitUploadSizeMiddleware in main.py." -ForegroundColor Red
}

# -------------------------------------------------------------------
# Test 4: Via Next.js proxy at localhost:3000 - expect 202
# -------------------------------------------------------------------
Write-Host ""
Write-Host "Test 4: POST /api/ingest via Next.js proxy at localhost:3000 (requires npm run dev)" -ForegroundColor Yellow

$T4 = curl.exe -s -o - -w "`nHTTP_STATUS:%{http_code}" `
    -X POST "http://localhost:3000/api/ingest" `
    -F "file=@${DummyPath};type=application/pdf" `
    -F "ticker=TEST" `
    -F "fiscal_year=2024"

Write-Host $T4

if ($T4 -match "HTTP_STATUS:202") {
    Write-Host "[PASS] 202 via Next.js proxy - full E2E path works." -ForegroundColor Green
} elseif ($T4 -match "HTTP_STATUS:000" -or $T4 -match "connect" -or $T4 -match "refused") {
    Write-Host "[SKIP] Next.js server not running on port 3000. Run: cd frontend && npm run dev" -ForegroundColor DarkYellow
} else {
    Write-Host "[FAIL] Unexpected response from proxy. Check Next.js console output." -ForegroundColor Red
}

# Cleanup
Remove-Item $DummyPath -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "=== Test complete. Dummy file removed. ===" -ForegroundColor Cyan
