import { spawnSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import process from "node:process";

const host = "127.0.0.1";
const port = Number(process.env.CONTENT_REVIEW_PORT || 3100);
const root = process.cwd();
loadLocalEnv(path.join(root, "backend", ".env"));
const configPath = path.join(root, "content-pipeline", "site.config.json");
const tasksPath = path.join(root, "content-pipeline", "tasks.json");
const config = readJson(configPath);
const contentDir = path.join(root, config.site.contentDirectory);
const allowedOrigins = new Set([
  "http://localhost:3000",
  "http://127.0.0.1:3000",
  "http://localhost:3001",
  "http://127.0.0.1:3001",
]);

function loadLocalEnv(file) {
  if (!fs.existsSync(file)) return;
  for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const separator = trimmed.indexOf("=");
    if (separator < 1) continue;
    const key = trimmed.slice(0, separator).trim();
    const value = trimmed.slice(separator + 1).trim().replace(/^(['"])(.*)\1$/, "$2");
    if (!(key in process.env)) process.env[key] = value;
  }
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function writeJsonAtomic(file, value) {
  const temporary = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  fs.renameSync(temporary, file);
}

function json(response, status, payload, origin) {
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Cache-Control": "no-store",
    "Vary": "Origin",
  });
  response.end(JSON.stringify(payload));
}

function articlePath(slug) {
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug)) return null;
  const file = path.join(contentDir, `${slug}.json`);
  return path.dirname(file) === contentDir ? file : null;
}

function validation(slug) {
  return spawnSync(
    process.execPath,
    ["content-pipeline/scripts/content-pipeline.mjs", "validate", slug],
    { cwd: root, encoding: "utf8" },
  );
}

const server = http.createServer((request, response) => {
  const origin = request.headers.origin || "";
  if (!allowedOrigins.has(origin)) {
    json(response, 403, { ok: false, error: "Origin is not allowed." }, "null");
    return;
  }

  if (request.method === "OPTIONS") {
    json(response, 204, {}, origin);
    return;
  }

  if (request.method !== "POST" || !["/approve", "/publish"].includes(request.url || "")) {
    json(response, 404, { ok: false, error: "Not found." }, origin);
    return;
  }

  let raw = "";
  request.on("data", (chunk) => {
    raw += chunk;
    if (raw.length > 16_384) request.destroy();
  });
  request.on("end", () => {
    if (request.url === "/publish") {
      publish(request, response, raw, origin);
      return;
    }
    try {
      const body = JSON.parse(raw || "{}");
      const reviewer = String(body.reviewer || "").trim();
      const slug = String(body.slug || "").trim();
      const file = articlePath(slug);

      if (!file || !fs.existsSync(file)) {
        json(response, 404, { ok: false, error: "Article not found." }, origin);
        return;
      }
      if (reviewer.length < 2 || reviewer.length > 80 || /pending/i.test(reviewer)) {
        json(response, 400, { ok: false, error: "Enter a real reviewer name." }, origin);
        return;
      }

      const article = readJson(file);
      if (!["draft", "review"].includes(article.status)) {
        json(response, 409, { ok: false, error: "Article is not awaiting approval." }, origin);
        return;
      }

      const tasks = readJson(tasksPath);
      const task = tasks.tasks.find((item) => item.slug === slug);
      if (!task) {
        json(response, 409, { ok: false, error: "Matching content task not found." }, origin);
        return;
      }

      const articleBefore = structuredClone(article);
      const tasksBefore = structuredClone(tasks);
      const today = new Date().toISOString().slice(0, 10);
      article.status = "approved";
      article.reviewer = reviewer;
      article.publishedAt = article.publishedAt || today;
      article.updatedAt = today;
      task.status = "approved";
      tasks.updatedAt = today;

      writeJsonAtomic(file, article);
      writeJsonAtomic(tasksPath, tasks);

      const checked = validation(slug);
      if (checked.status !== 0) {
        writeJsonAtomic(file, articleBefore);
        writeJsonAtomic(tasksPath, tasksBefore);
        json(
          response,
          422,
          {
            ok: false,
            error: "Quality validation failed; approval was rolled back.",
            details: `${checked.stdout || ""}${checked.stderr || ""}`.trim(),
          },
          origin,
        );
        return;
      }

      json(
        response,
        200,
        {
          ok: true,
          slug,
          reviewer,
          publishedAt: article.publishedAt,
          validation: checked.stdout.trim(),
        },
        origin,
      );
    } catch (error) {
      json(
        response,
        500,
        { ok: false, error: error instanceof Error ? error.message : "Approval failed." },
        origin,
      );
    }
  });
});

async function publish(_request, response, raw, origin) {
  try {
    const body = JSON.parse(raw || "{}");
    const slug = String(body.slug || "").trim();
    const file = articlePath(slug);
    const token = String(process.env.CONTENT_PUBLISH_TOKEN || "").trim();
    const apiBase = String(
      process.env.CONTENT_PUBLISH_API_URL || "https://diamscore.com/api/content",
    ).replace(/\/$/, "");

    if (!file || !fs.existsSync(file)) {
      json(response, 404, { ok: false, error: "Article not found." }, origin);
      return;
    }
    if (!token) {
      json(
        response,
        503,
        { ok: false, error: "CONTENT_PUBLISH_TOKEN is not configured locally." },
        origin,
      );
      return;
    }

    const article = readJson(file);
    if (article.status !== "approved") {
      json(response, 409, { ok: false, error: "Approve the article before publishing." }, origin);
      return;
    }

    const checked = validation(slug);
    if (checked.status !== 0) {
      json(
        response,
        422,
        {
          ok: false,
          error: "Quality validation failed; article was not published.",
          details: `${checked.stdout || ""}${checked.stderr || ""}`.trim(),
        },
        origin,
      );
      return;
    }

    const revision = spawnSync("git", ["rev-parse", "--short", "HEAD"], {
      cwd: root,
      encoding: "utf8",
    });
    const upstream = await fetch(`${apiBase}/articles/${encodeURIComponent(slug)}`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        article,
        source_revision: revision.status === 0 ? revision.stdout.trim() : null,
      }),
    });
    const payload = await upstream.json().catch(() => ({}));
    if (!upstream.ok) {
      json(
        response,
        upstream.status,
        {
          ok: false,
          error: payload.detail || payload.error || `Publishing API returned ${upstream.status}.`,
        },
        origin,
      );
      return;
    }

    json(response, 200, { ok: true, ...payload, validation: checked.stdout.trim() }, origin);
  } catch (error) {
    json(
      response,
      500,
      { ok: false, error: error instanceof Error ? error.message : "Publishing failed." },
      origin,
    );
  }
}

server.listen(port, host, () => {
  console.log(`Content review server listening on http://${host}:${port}`);
  console.log("Local browser origins only. Press Ctrl+C to stop.");
});
