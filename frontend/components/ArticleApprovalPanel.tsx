"use client";

import { useState } from "react";

interface ArticleApprovalPanelProps {
  slug: string;
}

export function ArticleApprovalPanel({ slug }: ArticleApprovalPanelProps) {
  const [reviewer, setReviewer] = useState("");
  const [status, setStatus] = useState<
    | { type: "idle" }
    | { type: "loading" }
    | { type: "success"; message: string }
    | { type: "error"; message: string }
  >({ type: "idle" });

  async function approve() {
    if (reviewer.trim().length < 2) {
      setStatus({ type: "error", message: "Enter the reviewer’s real name first." });
      return;
    }
    if (!window.confirm("Approve this article and make it eligible for the next production build?")) {
      return;
    }

    setStatus({ type: "loading" });
    try {
      const response = await fetch("http://127.0.0.1:3100/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug, reviewer: reviewer.trim() }),
      });
      const payload = (await response.json()) as {
        ok?: boolean;
        error?: string;
        publishedAt?: string;
      };
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || "Approval failed.");
      }
      setStatus({
        type: "success",
        message: `Approved for publication on ${payload.publishedAt}. Refreshing preview…`,
      });
      window.setTimeout(() => window.location.reload(), 900);
    } catch (error) {
      setStatus({
        type: "error",
        message:
          error instanceof Error
            ? `${error.message} Make sure npm run content:review-server is running.`
            : "Approval failed.",
      });
    }
  }

  return (
    <section className="mb-8 rounded-2xl border border-amber-300 bg-amber-50 p-5">
      <p className="text-sm font-semibold text-amber-950">Pending approval · Local editorial preview</p>
      <p className="mt-1 text-sm leading-6 text-amber-900/75">
        Approval runs the quality validator before changing the article and matching task to approved.
        Production still requires a normal build and deployment.
      </p>
      <div className="mt-4 flex flex-col gap-3 sm:flex-row">
        <label className="flex-1">
          <span className="sr-only">Reviewer name</span>
          <input
            className="h-11 w-full rounded-xl border border-amber-300 bg-white px-4 text-sm outline-none focus:border-amber-600"
            onChange={(event) => setReviewer(event.target.value)}
            placeholder="Reviewer’s real name"
            type="text"
            value={reviewer}
          />
        </label>
        <button
          className="h-11 rounded-xl bg-amber-700 px-5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
          disabled={status.type === "loading"}
          onClick={approve}
          type="button"
        >
          {status.type === "loading" ? "Validating…" : "Approve article"}
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
