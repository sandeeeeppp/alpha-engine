import { NextRequest } from 'next/server';

// Extend Vercel function timeout to maximum allowed on Hobby tier
export const maxDuration = 60;

// Disable Next.js caching — SSE must never be cached
export const dynamic = 'force-dynamic';

export async function POST(req: NextRequest) {
  const body = await req.json();

  // server-side only env vars — NOT NEXT_PUBLIC_, never leaked to JS bundle
  const backendUrl = process.env.BACKEND_URL;
  const internalSecret = process.env.INTERNAL_API_SECRET;

  if (!backendUrl || !internalSecret) {
    return new Response(
      JSON.stringify({ error: 'Backend not configured.' }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    );
  }

  const response = await fetch(`${backendUrl}/api/analyze`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Internal-Secret': internalSecret,
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    return new Response(response.body, { status: response.status });
  }

  // Pass the stream directly — do not buffer it
  return new Response(response.body, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',  // Disables Nginx/Vercel edge buffering
    },
  });
}
