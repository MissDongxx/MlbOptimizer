"use client";

import { useState } from "react";

interface ArticlePublishPanelProps {
  slug: string;
  reviewer: string;
}

export function ArticlePublishPanel({ slug, reviewer }: ArticlePublishPanelProps) {
  const [status, setStatus] = useState<
    | { type: "idle" }
    | { type: "loading" }
    | { type: "success"; message: string }
    | { type: "error"; message: string }
  >({ type: "idle" });

  async function publish() {
    if (
      !window.confirm(
        "Publish this approved article to the production content API? It can become public immediately.",
      )
    ) {
      return;
    }
    setStatus({ type: "loading" });
    try {
      const response = await fetch("http://127.0.0.1:3100/publish", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug }),
      });
      const payload = (await response.json()) as {
        ok?: boolean;
        error?: string;
        publishedAt?: string;
      };
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || "Publishing failed.");
      }
      setStatus({
        type: "success",
        message: `Published through the production content API on ${payload.publishedAt}.`,
      });
    } catch (error) {
      setStatus({
        type: "error",
        message:
          error instanceof Error
            ? `${error.message} Check the local publisher and production API configuration.`
            : "Publishing failed.",
      });
    }
  }

  return (
    <section className="mb-8 rounded-2xl border border-emerald-300 bg-emerald-50 p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-sm font-semibold text-emerald-950">Approved by {reviewer}</p>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-emerald-900/75">
            Publishing sends this validated version to the production content API. It does not rebuild
            or redeploy the application.
          </p>
        </div>
        <button
          className="h-11 rounded-xl bg-emerald-700 px-5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
          disabled={status.type === "loading"}
          onClick={publish}
          type="button"
        >
          {status.type === "loading" ? "Publishing…" : "Publish now"}
        </button>
      </div>
      {status.type !== "idle" && status.type !== "loading" && (
        <p
          className={`mt-3 text-sm ${status.type === "success" ? "text-emerald-700" : "text-red-700"}`}
          role="status"
        >
          {status.message}
        </p>
      )}
    </section>
  );
}
