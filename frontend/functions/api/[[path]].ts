const API_ORIGIN = "http://104-168-30-212.sslip.io";

interface PagesFunctionContext {
  request: Request;
}

export async function onRequest(context: PagesFunctionContext) {
  const url = new URL(context.request.url);
  const target = new URL(url.pathname.replace(/^\/api/, "/api") + url.search, API_ORIGIN);

  const headers = new Headers(context.request.headers);
  headers.set("host", new URL(API_ORIGIN).host);

  const response = await fetch(target, {
    body: context.request.method === "GET" || context.request.method === "HEAD" ? undefined : context.request.body,
    headers,
    method: context.request.method,
  });

  const nextHeaders = new Headers(response.headers);
  nextHeaders.set("access-control-allow-origin", url.origin);
  nextHeaders.set("x-diamscore-proxy", "cloudflare-pages");
  nextHeaders.set("vary", "Origin");

  return new Response(response.body, {
    headers: nextHeaders,
    status: response.status,
    statusText: response.statusText,
  });
}
