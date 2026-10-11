"use client";

// The admin dashboard (same behavior as the old frontend/admin.html):
// summary statistics, a card for each project, Refresh, Refresh Admin Token,
// and Set Project Token. All data comes from the admin API in the browser.
// The S3 storage values load after the project list (they are slow).

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { formatBytes, formatTimeAgo } from "@/src/client/adminFormat";

type Project = {
  project: string;
  audio: { todo: number; ready: number; trash: number; total: number };
  video: { total: number };
  storage_bytes: number;
  last_updated: string | null;
};

type S3State =
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; byProject: Record<string, number>; total: number };

type ListState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; projects: Project[] };

function apiBase(token: string): string {
  return `/admin/${encodeURIComponent(token)}/api`;
}

function httpError(res: Response): Error {
  return new Error(`HTTP ${res.status}: ${res.statusText}`);
}

function s3Text(s3: S3State, value: (loaded: Extract<S3State, { status: "loaded" }>) => number | undefined): string {
  if (s3.status === "loading") return "loading...";
  if (s3.status === "error") return "unavailable";
  return formatBytes(value(s3) ?? 0);
}

export function AdminDashboard({ initialToken }: { initialToken: string }) {
  const [token, setToken] = useState(initialToken);
  const [mediaToken, setMediaToken] = useState<string | null>(null);
  const [list, setList] = useState<ListState>({ status: "loading" });
  const [s3, setS3] = useState<S3State>({ status: "loading" });
  const [actionError, setActionError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [tokenInput, setTokenInput] = useState("");
  const loadSequence = useRef(0);

  const keepMediaToken = useCallback((value: unknown) => {
    const normalized = typeof value === "string" ? value.trim() : "";
    if (normalized) setMediaToken(normalized);
  }, []);

  const loadS3 = useCallback(async (base: string, sequence: number) => {
    try {
      const res = await fetch(`${base}/projects/s3-storage`);
      if (!res.ok) throw httpError(res);
      const data = (await res.json()) as { projects: { project: string; s3_storage_bytes: number }[]; total_s3_storage_bytes: number };
      if (sequence !== loadSequence.current) return;
      const byProject: Record<string, number> = {};
      for (const entry of data.projects) byProject[entry.project] = entry.s3_storage_bytes;
      setS3({ status: "loaded", byProject, total: data.total_s3_storage_bytes });
    } catch {
      if (sequence !== loadSequence.current) return;
      setS3({ status: "error" });
    }
  }, []);

  const loadProjects = useCallback(async (adminToken: string) => {
    const sequence = ++loadSequence.current;
    const base = apiBase(adminToken);
    setList({ status: "loading" });
    try {
      const res = await fetch(`${base}/projects`);
      if (!res.ok) throw res.status === 401 ? new Error("Invalid admin token") : httpError(res);
      const data = (await res.json()) as { media_token: string | null; projects: Project[] };
      if (sequence !== loadSequence.current) return;
      keepMediaToken(data.media_token);
      setS3({ status: "loading" });
      setList({ status: "ready", projects: data.projects });
      void loadS3(base, sequence);
    } catch (err) {
      if (sequence !== loadSequence.current) return;
      setList({ status: "error", message: err instanceof Error ? err.message : String(err) });
    }
  }, [keepMediaToken, loadS3]);

  useEffect(() => {
    void loadProjects(initialToken);
  }, [initialToken, loadProjects]);

  async function refreshAdminToken() {
    setActionError(null);
    try {
      const res = await fetch(`${apiBase(token)}/refresh-admin-token`, { method: "POST" });
      if (!res.ok) throw httpError(res);
      const payload = (await res.json()) as { admin_token?: string };
      const next = payload.admin_token?.trim();
      if (!next) return;
      setToken(next);
      const nextPath = `/admin/${encodeURIComponent(next)}/`;
      if (window.location.pathname !== nextPath) window.history.replaceState(null, "", nextPath);
      await loadProjects(next);
    } catch (err) {
      setActionError(`Error refreshing admin token: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  async function saveProjectToken(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setActionError(null);
    try {
      const res = await fetch(`${apiBase(token)}/media-token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: tokenInput }),
      });
      if (!res.ok) throw httpError(res);
      const payload = (await res.json()) as { media_token?: string };
      keepMediaToken(payload.media_token);
      setShowForm(false);
      setTokenInput("");
      await loadProjects(token);
    } catch (err) {
      setActionError(`Error setting project token: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-6 p-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Media Manager Admin</h1>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => void loadProjects(token)}>Refresh</Button>
          <Button variant="outline" onClick={() => void refreshAdminToken()}>Refresh Admin Token</Button>
          <Button onClick={() => setShowForm((shown) => !shown)} aria-expanded={showForm}>Set Project Token</Button>
        </div>
      </header>

      {actionError && (
        <Alert variant="destructive">
          <AlertTitle>{actionError}</AlertTitle>
        </Alert>
      )}

      {showForm && (
        <Card>
          <form onSubmit={(event) => void saveProjectToken(event)} className="flex flex-col gap-4">
            <CardHeader>
              <CardTitle><h2>Set project token</h2></CardTitle>
              <CardDescription>
                The token will be hashed for access checks and stored encrypted in Postgres for admin links.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3 sm:flex-row">
              <Input
                type="text"
                autoComplete="off"
                required
                aria-label="Project token"
                placeholder="Paste the project/media token"
                value={tokenInput}
                onChange={(event) => setTokenInput(event.target.value)}
              />
              <Button type="submit">Save token</Button>
            </CardContent>
          </form>
        </Card>
      )}

      <section aria-busy={list.status === "loading"} className="flex flex-col gap-6">
        {list.status === "loading" && (
          <>
            <div role="status" className="text-muted-foreground">Loading projects...</div>
            <div aria-hidden="true" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {[0, 1, 2].map((i) => <Skeleton key={i} className="h-40 w-full" />)}
            </div>
          </>
        )}

        {list.status === "error" && (
          <Alert variant="destructive">
            <AlertTitle>Error: {list.message}</AlertTitle>
            <AlertDescription>The project list could not load.</AlertDescription>
          </Alert>
        )}

        {list.status === "ready" && list.projects.length === 0 && (
          <Empty>
            <EmptyHeader>
              <EmptyTitle>No projects found</EmptyTitle>
            </EmptyHeader>
          </Empty>
        )}

        {list.status === "ready" && list.projects.length > 0 && (
          <ProjectList projects={list.projects} s3={s3} mediaToken={mediaToken} />
        )}
      </section>
    </main>
  );
}

function ProjectList({ projects, s3, mediaToken }: { projects: Project[]; s3: S3State; mediaToken: string | null }) {
  const totalAudio = projects.reduce((sum, p) => sum + p.audio.total, 0);
  const totalVideo = projects.reduce((sum, p) => sum + p.video.total, 0);
  const totalStorage = projects.reduce((sum, p) => sum + p.storage_bytes, 0);
  const summary: [string, string][] = [
    ["Projects", String(projects.length)],
    ["Total Audio", String(totalAudio)],
    ["Total Video", String(totalVideo)],
    ["DB Storage", formatBytes(totalStorage)],
    ["S3 Storage", s3Text(s3, (loaded) => loaded.total)],
  ];

  return (
    <>
      <dl aria-label="Summary" className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {summary.map(([label, value]) => (
          <Card key={label} data-stat={label} className="gap-2 py-4">
            <CardHeader className="px-4">
              <CardDescription><dt>{label}</dt></CardDescription>
              <CardTitle className="text-2xl"><dd>{value}</dd></CardTitle>
            </CardHeader>
          </Card>
        ))}
      </dl>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {projects.map((p) => (
          <ProjectCard key={p.project} project={p} s3={s3Text(s3, (loaded) => loaded.byProject[p.project])} mediaToken={mediaToken} />
        ))}
      </div>
    </>
  );
}

function ProjectCard({ project: p, s3, mediaToken }: { project: Project; s3: string; mediaToken: string | null }) {
  const base = `/projects/${encodeURIComponent(mediaToken ?? "")}/${encodeURIComponent(p.project)}`;
  const links: [string, string][] = [
    ["Open Audio", `${base}/audio#admin`],
    ["Open Video", `${base}/videos#admin`],
  ];
  return (
    <Card data-project={p.project}>
      <CardHeader>
        <CardTitle><h2>{p.project}</h2></CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span>Audio: <strong>{p.audio.total}</strong></span>
          {p.audio.todo > 0 && <Badge variant="secondary">{p.audio.todo} todo</Badge>}
          {p.audio.ready > 0 && <Badge variant="secondary">{p.audio.ready} ready</Badge>}
          {p.audio.trash > 0 && <Badge variant="outline">{p.audio.trash} trash</Badge>}
        </div>
        <div>Video: <strong>{p.video.total}</strong></div>
        <div className="text-muted-foreground">
          DB {formatBytes(p.storage_bytes)} • S3 {s3} • {formatTimeAgo(p.last_updated)}
        </div>
      </CardContent>
      <CardFooter className="flex flex-wrap gap-2">
        {links.map(([label, href]) =>
          mediaToken ? (
            <Button key={label} asChild variant={label === "Open Audio" ? "default" : "secondary"}>
              <a href={href} target="_blank" rel="noopener">{label}</a>
            </Button>
          ) : (
            <Button key={label} disabled variant={label === "Open Audio" ? "default" : "secondary"}>
              {label} (set project token first)
            </Button>
          ),
        )}
      </CardFooter>
    </Card>
  );
}
