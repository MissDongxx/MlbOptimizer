import type { OptimizeRequest, OptimizeResponse, PlayerPoolResponse } from "./types";

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

export async function fetchTodaysPlayers(): Promise<PlayerPoolResponse> {
  const res = await fetchWithTimeout(`${API_URL}/players/today`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error("Failed to fetch players");
  }
  return res.json();
}

export async function runOptimizer(request: OptimizeRequest): Promise<OptimizeResponse> {
  const res = await fetchWithTimeout(`${API_URL}/optimize/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
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

async function fetchWithTimeout(input: string, init: RequestInit = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    return await fetch(input, {
      ...init,
      signal: init.signal ?? controller.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("API request timed out. Make sure the backend is running on port 8000.");
    }
    throw err;
  } finally {
    window.clearTimeout(timeout);
  }
}
