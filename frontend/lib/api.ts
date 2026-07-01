import type { OptimizeRequest, OptimizeResponse, PlayerPoolResponse } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function fetchTodaysPlayers(): Promise<PlayerPoolResponse> {
  const res = await fetch(`${API_URL}/players/today`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error("Failed to fetch players");
  }
  return res.json();
}

export async function runOptimizer(request: OptimizeRequest): Promise<OptimizeResponse> {
  const res = await fetch(`${API_URL}/optimize/`, {
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
