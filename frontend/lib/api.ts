import type {
  OptimizeRequest,
  OptimizeResponse,
  PlayerPoolResponse,
  Site,
  SlateListResponse,
} from "./types";

interface ContactRequest {
  email: string;
  message?: string;
  company?: string;
}

interface ContactResponse {
  ok: boolean;
  message: string;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const REQUEST_TIMEOUT_MS = 8000;
const PLAYER_REQUEST_TIMEOUT_MS = 90000;
const OPTIMIZER_REQUEST_TIMEOUT_MS = 60000;

export async function fetchTodaysPlayers(site?: Site, slateId?: string): Promise<PlayerPoolResponse> {
  const params = site && slateId
    ? `?${new URLSearchParams({ site, slate_id: slateId }).toString()}`
    : "";
  const res = await fetchWithTimeout(
    `${API_URL}/players/today${params}`,
    { cache: "no-store" },
    PLAYER_REQUEST_TIMEOUT_MS,
    "Live player data is still refreshing. Please try again shortly.",
  );
  if (!res.ok) {
    throw new Error("Failed to fetch players");
  }
  return res.json();
}

export async function fetchSlates(site: Site): Promise<SlateListResponse> {
  const params = new URLSearchParams({ site });
  const res = await fetchWithTimeout(
    `${API_URL}/players/slates?${params.toString()}`,
    { cache: "no-store" },
    PLAYER_REQUEST_TIMEOUT_MS,
    "Slate list is still refreshing. Please try again shortly.",
  );
  if (!res.ok) {
    throw new Error("Failed to fetch slates");
  }
  return res.json();
}

export async function runOptimizer(request: OptimizeRequest): Promise<OptimizeResponse> {
  const res = await fetchWithTimeout(`${API_URL}/optimize/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, OPTIMIZER_REQUEST_TIMEOUT_MS, "Optimization is taking longer than expected. Please try again.");
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(err?.detail || "Optimization failed");
  }
  return res.json();
}

export async function sendContactMessage(request: ContactRequest): Promise<ContactResponse> {
  const res = await fetchWithTimeout(`${API_URL}/contact/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    throw new Error(body?.detail || "Could not send your message. Please try again later.");
  }
  return body;
}

async function fetchWithTimeout(
  input: string,
  init: RequestInit = {},
  timeoutMs = REQUEST_TIMEOUT_MS,
  timeoutMessage = "API request timed out. Please try again.",
) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetch(input, {
      ...init,
      signal: init.signal ?? controller.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error(timeoutMessage);
    }
    throw err;
  } finally {
    window.clearTimeout(timeout);
  }
}
