/**
 * Create a Dokploy-managed Postgres database for Media Manager.
 *
 * Reads DOKPLOY_BASE and DOKPLOY_TOKEN from the repo .env, then optionally:
 * - DOKPLOY_PROJECT_ID
 * - DOKPLOY_ENVIRONMENT_ID
 * - DOKPLOY_POSTGRES_NAME
 * - DOKPLOY_POSTGRES_DATABASE
 * - DOKPLOY_POSTGRES_USER
 * - DOKPLOY_POSTGRES_PASSWORD
 * - DOKPLOY_POSTGRES_IMAGE
 */

import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { randomBytes } from "node:crypto";
import { resolve } from "node:path";

interface DokployProject {
  projectId: string;
  name: string;
}

interface DokployEnvironment {
  environmentId: string;
  name: string;
}

interface DokployPostgres {
  postgresId?: string;
  name?: string;
  appName?: string;
  internalUrl?: string;
  databaseUrl?: string;
  postgresUrl?: string;
}

function loadDotenv(path: string): void {
  if (!existsSync(path)) return;
  for (const line of readFileSync(path, "utf8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const match = /^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/.exec(trimmed);
    if (!match) continue;
    const key = match[1];
    const rawValue = match[2];
    if (!key || rawValue === undefined) continue;
    if (process.env[key] !== undefined) continue;
    process.env[key] = rawValue.replace(/^['"]|['"]$/g, "");
  }
}

function env(name: string): string | undefined {
  const value = process.env[name]?.trim();
  return value ? value : undefined;
}

function requiredEnv(name: string): string {
  const value = env(name);
  if (!value) throw new Error(`Missing required environment variable: ${name}`);
  return value;
}

function apiUrl(base: string, path: string, mode: "api" | "trpc"): string {
  const normalized = base.replace(/\/+$/, "");
  return `${normalized}/${mode}/${path.replace(/^\/+/, "")}`;
}

async function dokploy<T>(
  base: string,
  token: string,
  path: string,
  init: RequestInit = {},
  mode: "api" | "trpc" = "api",
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("x-api-key", token);
  headers.set("accept", "application/json");
  if (init.body && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  const response = await fetch(apiUrl(base, path, mode), { ...init, headers });
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`${path} failed (${response.status}): ${text}`);
  }
  const parsed = text ? JSON.parse(text) : {};
  if (mode === "trpc") {
    return parsed?.result?.data?.json as T;
  }
  return parsed as T;
}

async function dokployGet<T>(
  base: string,
  token: string,
  path: string,
  input?: Record<string, unknown>,
): Promise<T> {
  try {
    return await dokploy<T>(base, token, path);
  } catch (err) {
    if (!(err instanceof Error) || !err.message.includes("(404)")) {
      throw err;
    }
  }

  const query = input
    ? `?input=${encodeURIComponent(JSON.stringify({ json: input }))}`
    : "";
  return dokploy<T>(base, token, `${path}${query}`, {}, "trpc");
}

async function dokployPost<T>(
  base: string,
  token: string,
  path: string,
  body: Record<string, unknown>,
): Promise<T> {
  try {
    return await dokploy<T>(base, token, path, {
      method: "POST",
      body: JSON.stringify(body),
    });
  } catch (err) {
    if (!(err instanceof Error) || !err.message.includes("(404)")) {
      throw err;
    }
  }

  return dokploy<T>(
    base,
    token,
    path,
    {
      method: "POST",
      body: JSON.stringify({ json: body }),
    },
    "trpc",
  );
}

async function chooseProject(base: string, token: string): Promise<string> {
  const explicit = env("DOKPLOY_PROJECT_ID");
  if (explicit) return explicit;

  const projects = await dokployGet<DokployProject[]>(base, token, "project.all");
  if (projects.length !== 1) {
    const names = projects.map((p) => `${p.name}=${p.projectId}`).join("\n");
    throw new Error(
      `Set DOKPLOY_PROJECT_ID in .env. Available projects:\n${names}`,
    );
  }
  return projects[0]!.projectId;
}

async function chooseEnvironment(
  base: string,
  token: string,
  projectId: string,
): Promise<string> {
  const explicit = env("DOKPLOY_ENVIRONMENT_ID");
  if (explicit) return explicit;

  const environments = await dokployGet<DokployEnvironment[]>(
    base,
    token,
    "environment.byProjectId",
    { projectId },
  );
  if (environments.length !== 1) {
    const names = environments.map((e) => `${e.name}=${e.environmentId}`).join("\n");
    throw new Error(
      `Set DOKPLOY_ENVIRONMENT_ID in .env. Available environments:\n${names}`,
    );
  }
  return environments[0]!.environmentId;
}

function randomPassword(): string {
  return randomBytes(24).toString("base64url");
}

async function main(): Promise<void> {
  loadDotenv(resolve(import.meta.dir, "../../.env"));
  loadDotenv(resolve(import.meta.dir, "../.env"));

  const base = requiredEnv("DOKPLOY_BASE");
  const token = requiredEnv("DOKPLOY_TOKEN");
  const projectId = await chooseProject(base, token);
  const environmentId = await chooseEnvironment(base, token, projectId);

  const name = env("DOKPLOY_POSTGRES_NAME") ?? "media-manager-postgres";
  const databaseName = env("DOKPLOY_POSTGRES_DATABASE") ?? "media_manager";
  const databaseUser = env("DOKPLOY_POSTGRES_USER") ?? "media_manager";
  const databasePassword = env("DOKPLOY_POSTGRES_PASSWORD") ?? randomPassword();
  const dockerImage = env("DOKPLOY_POSTGRES_IMAGE") ?? "postgres:18";
  const tokenEncryptionKey = randomBytes(32).toString("base64");

  const created = await dokployPost<DokployPostgres>(
    base,
    token,
    "postgres.create",
    {
      name,
      appName: name,
      databaseName,
      databaseUser,
      databasePassword,
      dockerImage,
      environmentId,
      description: "Media Manager metadata database",
    },
  );

  const postgresId = created.postgresId;
  const databaseHost = created.appName ?? name;
  const envOutput = [
    `DATABASE_URL=postgresql://${databaseUser}:${databasePassword}@${databaseHost}:5432/${databaseName}`,
    "DB_SCHEMA=media_manager",
    `TOKEN_ENCRYPTION_KEY=${tokenEncryptionKey}`,
    "",
  ].join("\n");
  writeFileSync(resolve(import.meta.dir, "../.dokploy-postgres.env"), envOutput, {
    mode: 0o600,
  });

  if (postgresId) {
    try {
      await dokployPost(base, token, "postgres.deploy", { postgresId });
    } catch {
      await dokployPost(base, token, "postgres.start", { postgresId });
    }
  }

  console.log("Dokploy Postgres created.");
  console.log(`postgresId=${postgresId ?? "<not returned by Dokploy>"}`);
  console.log("");
  console.log("Media Manager env written to remote-js/.dokploy-postgres.env");
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : String(err));
  process.exit(1);
});
