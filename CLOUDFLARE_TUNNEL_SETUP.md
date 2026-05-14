# Replace ngrok with Cloudflare Tunnel

## Why

ngrok buffers SSE streams. Cloudflare Tunnel passes chunked transfer encoding
natively, has no bandwidth limit, no connection limit, and gives a permanent URL.

## Steps (Run on Windows as Administrator)

### 1. Download cloudflared

https://github.com/cloudflare/cloudflared/releases/latest

Download: `cloudflared-windows-amd64.exe` → rename to `cloudflared.exe`
Place at: `C:\cloudflared\cloudflared.exe`

### 2. Authenticate

```powershell
C:\cloudflared\cloudflared.exe login
```

Browser opens → authorize your Cloudflare account.

### 3. Create tunnel

```powershell
C:\cloudflared\cloudflared.exe tunnel create alpha-engine-backend
```

**NOTE:** Copy the UUID it outputs. You will need it in step 4.

### 4. Create config file

Create `C:\Users\LOQ\.cloudflared\config.yml` with the following content
(replace `<YOUR-UUID>` and `api.yourdomain.com` with your values):

```yaml
tunnel: <YOUR-UUID>
credentials-file: C:\Users\LOQ\.cloudflared\<YOUR-UUID>.json
ingress:
  - hostname: api.yourdomain.com
    service: http://127.0.0.1:8000
    originRequest:
      noTLSVerify: true
  - service: http_status:404
```

### 5. Route DNS

```powershell
C:\cloudflared\cloudflared.exe tunnel route dns alpha-engine-backend api.yourdomain.com
```

### 6. Install as Windows Service (survives reboots — no manual restart needed)

```powershell
C:\cloudflared\cloudflared.exe service install
Start-Service cloudflared
```

### 7. Update Vercel Environment Variables

In Vercel dashboard → Settings → Environment Variables:

```
BACKEND_URL = https://api.yourdomain.com   (NOT NEXT_PUBLIC_ prefix)
INTERNAL_API_SECRET = <generate with the command below>
```

Generate a secret:

```powershell
backend\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
```

Trigger a Vercel redeploy after updating env vars.

## Verification

After the tunnel is running and Vercel is redeployed, test SSE streaming:

```powershell
$secret = "<your INTERNAL_API_SECRET>"
curl.exe -N https://api.yourdomain.com/api/analyze `
  -H "X-Internal-Secret: $secret" `
  -H "Content-Type: application/json" `
  -d "{`"query`": `"Analyze NVDA for fiscal year 2024`", `"session_id`": `"test-001`"}"
```

Tokens **must stream one by one**, not appear all at once.
If they batch-arrive, check that `X-Accel-Buffering: no` header is present in the
response and that `compress: false` is set in `frontend/next.config.ts`.
