import { NextRequest } from 'next/server';

export const dynamic = 'force-dynamic';

export async function POST(req: NextRequest) {
  const backendUrl = process.env.BACKEND_URL;
  const internalSecret = process.env.INTERNAL_API_SECRET;

  // Fail fast with a clear message if env vars are missing
  if (!backendUrl) {
    console.error('[ingest proxy] BACKEND_URL is not set in .env.local');
    return new Response(
      JSON.stringify({ error: 'BACKEND_URL is not configured on the server.' }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    );
  }
  if (!internalSecret) {
    console.error('[ingest proxy] INTERNAL_API_SECRET is not set in .env.local');
    return new Response(
      JSON.stringify({ error: 'INTERNAL_API_SECRET is not configured on the server.' }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    );
  }

  // Parse the multipart/form-data sent by the browser
  let formData: FormData;
  try {
    formData = await req.formData();
  } catch (parseErr) {
    const msg = parseErr instanceof Error ? parseErr.message : String(parseErr);
    console.error('[ingest proxy] Failed to parse incoming FormData:', msg);
    return new Response(
      JSON.stringify({ error: `Failed to parse form data: ${msg}` }),
      { status: 400, headers: { 'Content-Type': 'application/json' } }
    );
  }

  // Log what we received so the Next.js console makes debugging trivial
  const ticker = formData.get('ticker');
  const fiscalYear = formData.get('fiscal_year');
  const file = formData.get('file');
  console.log(
    `[ingest proxy] Forwarding → ${backendUrl}/api/ingest`,
    `| ticker=${ticker} | fiscal_year=${fiscalYear}`,
    `| file=${file instanceof File ? `${file.name} (${file.size} bytes)` : 'none'}`
  );

  // Forward to FastAPI.
  // CRITICAL: Do NOT set Content-Type manually. When `body` is a FormData object,
  // fetch() automatically sets `Content-Type: multipart/form-data; boundary=...`
  // with the correct boundary string. Setting it manually strips the boundary and
  // causes FastAPI to reject the request with a 422 Unprocessable Entity.
  let backendResponse: Response;
  try {
    backendResponse = await fetch(`${backendUrl}/api/ingest`, {
      method: 'POST',
      headers: {
        'X-Internal-Secret': internalSecret,
      },
      body: formData,
    });
  } catch (fetchErr) {
    const msg = fetchErr instanceof Error ? fetchErr.message : String(fetchErr);
    console.error(
      `[ingest proxy] fetch() to ${backendUrl}/api/ingest failed:`,
      msg
    );
    return new Response(
      JSON.stringify({
        error: `Proxy failed to reach backend at ${backendUrl}: ${msg}`,
      }),
      { status: 502, headers: { 'Content-Type': 'application/json' } }
    );
  }

  // Read the backend response body as text (works for both JSON 202 and error payloads)
  const responseBody = await backendResponse.text();

  console.log(
    `[ingest proxy] Backend responded HTTP ${backendResponse.status}:`,
    responseBody.slice(0, 300)
  );

  // Return the backend's status and body verbatim to the browser
  return new Response(responseBody, {
    status: backendResponse.status,
    headers: {
      'Content-Type':
        backendResponse.headers.get('Content-Type') ?? 'application/json',
    },
  });
}
