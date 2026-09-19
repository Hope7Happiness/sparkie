import { execFile } from "node:child_process";
import { randomBytes } from "node:crypto";
import { mkdir, readFile, readdir, rename, unlink, writeFile } from "node:fs/promises";
import type { IncomingMessage, ServerResponse } from "node:http";
import { resolve } from "node:path";
import { promisify } from "node:util";
import type { Plugin, ViteDevServer } from "vite";

export interface ServiceVersion {
  name?: string;
  version?: string;
  commit?: string;
  branch?: string;
  dirty?: boolean;
}

export interface FrontendHelperPluginOptions {
  hotkey?: string;
  storageDirectory?: string;
  endpoint?: string;
  initiallyOpen?: boolean;
  maxTraceBytes?: number;
  service?: ServiceVersion;
}

const CLIENT_MODULE_ID = "virtual:frontend-helper/client";
const RESOLVED_CLIENT_MODULE_ID = `\0${CLIENT_MODULE_ID}`;
const execFileAsync = promisify(execFile);

export default function frontendHelper(options: FrontendHelperPluginOptions = {}): Plugin {
  const endpoint = normalizeEndpoint(options.endpoint ?? "/__frontend-helper/traces");
  const hotkey = options.hotkey ?? "Alt+Shift+H";
  const maxTraceBytes = options.maxTraceBytes ?? 25 * 1024 * 1024;

  return {
    name: "frontend-helper",
    apply: "serve",

    resolveId(id) {
      if (id === CLIENT_MODULE_ID) return RESOLVED_CLIENT_MODULE_ID;
    },

    load(id) {
      if (id !== RESOLVED_CLIENT_MODULE_ID) return;
      return `
        import { mount } from "@frontend-helper/dev-overlay";
        mount({
          hotkey: ${JSON.stringify(hotkey)},
          initiallyOpen: ${JSON.stringify(options.initiallyOpen ?? false)},
          traceEndpoint: ${JSON.stringify(endpoint)}
        });
      `;
    },

    transformIndexHtml() {
      return [
        {
          tag: "script",
          attrs: { type: "module", src: `/@id/__x00__${CLIENT_MODULE_ID}` },
          injectTo: "body",
        },
      ];
    },

    configureServer(server) {
      const storageDirectory = resolve(server.config.root, options.storageDirectory ?? ".frontend-helper/traces");
      server.middlewares.use(async (request, response, next) => {
        try {
          const handled = await handleTraceRequest({
            request,
            response,
            endpoint,
            storageDirectory,
            maxTraceBytes,
            serviceRoot: server.config.root,
            serviceOverride: options.service,
            server,
          });
          if (!handled) next();
        } catch (error) {
          server.config.logger.error(`[frontend-helper] ${error instanceof Error ? error.stack : String(error)}`);
          const status = getStatusCode(error);
          const code = status === 413 ? "trace_too_large" : status === 400 ? "invalid_json" : "internal_error";
          sendJson(response, status, { error: code });
        }
      });
    },
  };
}

interface TraceRequestContext {
  request: IncomingMessage;
  response: ServerResponse;
  endpoint: string;
  storageDirectory: string;
  maxTraceBytes: number;
  serviceRoot: string;
  serviceOverride?: ServiceVersion;
  server: ViteDevServer;
}

interface StoredTrace extends Record<string, unknown> {
  storage: {
    id: string;
    savedAt: string;
    name?: string;
  };
  service?: ServiceVersion;
  session?: {
    durationMs?: number;
    page?: { url?: string; title?: string };
  };
  timeline?: unknown[];
  annotations?: unknown[];
  rrwebEvents?: unknown[];
}

async function handleTraceRequest(context: TraceRequestContext): Promise<boolean> {
  const { request, response, endpoint, storageDirectory, maxTraceBytes, serviceRoot, serviceOverride, server } = context;
  const requestUrl = new URL(request.url ?? "/", "http://frontend-helper.local");
  const pathname = requestUrl.pathname;

  if (pathname === endpoint && request.method === "GET") {
    const traces = await listTraces(storageDirectory);
    sendJson(response, 200, { traces });
    return true;
  }

  if (pathname === endpoint && request.method === "POST") {
    const trace = await parseJsonBody(request, maxTraceBytes);
    if (!isFrontendHelperTrace(trace)) {
      sendJson(response, 422, { error: "invalid_trace" });
      return true;
    }

    const id = createTraceId();
    const savedAt = new Date().toISOString();
    const service = await detectServiceVersion(serviceRoot, serviceOverride);
    const storedTrace: StoredTrace = {
      ...trace,
      storage: { id, savedAt },
      ...(service ? { service } : {}),
    };
    await writeTrace(storageDirectory, id, storedTrace);
    server.config.logger.info(`[frontend-helper] saved trace ${id}`);
    sendJson(response, 201, { id, savedAt, service });
    return true;
  }

  const id = getTraceIdFromPath(pathname, endpoint);
  if (!id) return false;
  const tracePath = resolve(storageDirectory, `${id}.json`);

  if (request.method === "GET") {
    try {
      const trace = await readFile(tracePath, "utf8");
      sendRawJson(response, 200, trace);
    } catch (error) {
      if (isMissingFile(error)) sendJson(response, 404, { error: "trace_not_found", id });
      else throw error;
    }
    return true;
  }

  if (request.method === "PATCH") {
    const update = await parseJsonBody(request, 4 * 1024);
    const name = getValidTraceName(update);
    if (name === undefined) {
      sendJson(response, 422, { error: "invalid_name" });
      return true;
    }

    try {
      const trace = JSON.parse(await readFile(tracePath, "utf8")) as StoredTrace;
      trace.storage = { ...trace.storage, name: name || undefined };
      await writeTrace(storageDirectory, id, trace);
      server.config.logger.info(`[frontend-helper] renamed trace ${id}`);
      sendJson(response, 200, { id, name: trace.storage.name ?? null });
    } catch (error) {
      if (isMissingFile(error)) sendJson(response, 404, { error: "trace_not_found", id });
      else throw error;
    }
    return true;
  }

  if (request.method === "DELETE") {
    try {
      await unlink(tracePath);
      server.config.logger.info(`[frontend-helper] deleted trace ${id}`);
      sendJson(response, 200, { id, deleted: true });
    } catch (error) {
      if (isMissingFile(error)) sendJson(response, 404, { error: "trace_not_found", id });
      else throw error;
    }
    return true;
  }

  sendJson(response, 405, { error: "method_not_allowed" });
  return true;
}

async function listTraces(storageDirectory: string): Promise<Array<Record<string, unknown>>> {
  let files: string[];
  try {
    files = (await readdir(storageDirectory)).filter((file) => /^fh_[a-z0-9]+_[a-f0-9]{8}\.json$/.test(file));
  } catch (error) {
    if (isMissingFile(error)) return [];
    throw error;
  }

  const traces = await Promise.all(
    files.map(async (file) => {
      try {
        const trace = JSON.parse(await readFile(resolve(storageDirectory, file), "utf8")) as StoredTrace;
        return toTraceSummary(trace);
      } catch {
        return undefined;
      }
    }),
  );

  return traces
    .filter((trace): trace is Record<string, unknown> => Boolean(trace))
    .sort((left, right) => String(right.savedAt).localeCompare(String(left.savedAt)));
}

function toTraceSummary(trace: StoredTrace): Record<string, unknown> {
  return {
    id: trace.storage.id,
    name: trace.storage.name ?? null,
    savedAt: trace.storage.savedAt,
    service: trace.service ?? null,
    page: trace.session?.page ?? null,
    durationMs: trace.session?.durationMs ?? null,
    eventCount: trace.timeline?.length ?? 0,
    annotationCount: trace.annotations?.length ?? 0,
    rrwebEventCount: trace.rrwebEvents?.length ?? 0,
  };
}

async function writeTrace(storageDirectory: string, id: string, trace: StoredTrace): Promise<void> {
  await mkdir(storageDirectory, { recursive: true });
  const destination = resolve(storageDirectory, `${id}.json`);
  const temporary = resolve(storageDirectory, `.${id}.${randomBytes(3).toString("hex")}.tmp`);
  await writeFile(temporary, JSON.stringify(trace, null, 2), "utf8");
  await rename(temporary, destination);
}

async function parseJsonBody(request: IncomingMessage, maxBytes: number): Promise<unknown> {
  const body = await readRequestBody(request, maxBytes);
  try {
    return JSON.parse(body);
  } catch {
    const error = new Error("invalid_json");
    Object.assign(error, { statusCode: 400 });
    throw error;
  }
}

async function readRequestBody(request: IncomingMessage, maxBytes: number): Promise<string> {
  const chunks: Buffer[] = [];
  let bytes = 0;
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    bytes += buffer.byteLength;
    if (bytes > maxBytes) {
      const error = new Error("trace_too_large");
      Object.assign(error, { statusCode: 413 });
      throw error;
    }
    chunks.push(buffer);
  }
  return Buffer.concat(chunks).toString("utf8");
}

async function detectServiceVersion(root: string, override?: ServiceVersion): Promise<ServiceVersion | undefined> {
  const packageJson = await readPackageJson(root);
  const commit = override?.commit ?? firstValue(
    process.env.FRONTEND_HELPER_GIT_COMMIT,
    process.env.VERCEL_GIT_COMMIT_SHA,
    process.env.GITHUB_SHA,
    await gitValue(root, ["rev-parse", "HEAD"]),
  );
  const branch = override?.branch ?? firstValue(
    process.env.FRONTEND_HELPER_GIT_BRANCH,
    process.env.VERCEL_GIT_COMMIT_REF,
    process.env.GITHUB_REF_NAME,
    await gitValue(root, ["branch", "--show-current"]),
  );
  const dirty = override?.dirty ?? (commit ? (await gitValue(root, ["status", "--porcelain", "--untracked-files=no"])) !== "" : undefined);
  const service: ServiceVersion = {
    name: override?.name ?? firstValue(process.env.FRONTEND_HELPER_SERVICE_NAME, packageJson?.name),
    version: override?.version ?? firstValue(
      process.env.FRONTEND_HELPER_SERVICE_VERSION,
      process.env.VITE_APP_VERSION,
      packageJson?.version,
    ),
    commit,
    branch,
    dirty,
  };
  return Object.values(service).some((value) => value !== undefined && value !== "") ? service : undefined;
}

async function readPackageJson(root: string): Promise<{ name?: string; version?: string } | undefined> {
  try {
    return JSON.parse(await readFile(resolve(root, "package.json"), "utf8"));
  } catch {
    return undefined;
  }
}

async function gitValue(root: string, args: string[]): Promise<string | undefined> {
  try {
    const { stdout } = await execFileAsync("git", args, { cwd: root, timeout: 2000 });
    return stdout.trim();
  } catch {
    return undefined;
  }
}

function isFrontendHelperTrace(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return (
    candidate.format === "frontend-helper-trace" &&
    candidate.version === 1 &&
    Array.isArray(candidate.timeline) &&
    Array.isArray(candidate.annotations) &&
    Array.isArray(candidate.rrwebEvents)
  );
}

function getValidTraceName(value: unknown): string | undefined {
  if (!value || typeof value !== "object" || !("name" in value) || typeof value.name !== "string") return undefined;
  const name = value.name.trim();
  return name.length <= 80 ? name : undefined;
}

function createTraceId(): string {
  return `fh_${Date.now().toString(36)}_${randomBytes(4).toString("hex")}`;
}

function getTraceIdFromPath(pathname: string, endpoint: string): string | undefined {
  if (!pathname.startsWith(`${endpoint}/`)) return undefined;
  const id = decodeURIComponent(pathname.slice(endpoint.length + 1));
  return /^fh_[a-z0-9]+_[a-f0-9]{8}$/.test(id) ? id : undefined;
}

function normalizeEndpoint(endpoint: string): string {
  const normalized = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
  return normalized.replace(/\/+$/, "");
}

function sendJson(response: ServerResponse, status: number, value: unknown): void {
  sendRawJson(response, status, JSON.stringify(value));
}

function sendRawJson(response: ServerResponse, status: number, value: string): void {
  if (response.headersSent) return;
  response.statusCode = status;
  response.setHeader("Content-Type", "application/json; charset=utf-8");
  response.setHeader("Cache-Control", "no-store");
  response.end(value);
}

function isMissingFile(error: unknown): boolean {
  return Boolean(error && typeof error === "object" && "code" in error && error.code === "ENOENT");
}

function getStatusCode(error: unknown): number {
  if (!error || typeof error !== "object" || !("statusCode" in error)) return 500;
  return typeof error.statusCode === "number" ? error.statusCode : 500;
}

function firstValue(...values: Array<string | undefined>): string | undefined {
  return values.find((value) => Boolean(value));
}
