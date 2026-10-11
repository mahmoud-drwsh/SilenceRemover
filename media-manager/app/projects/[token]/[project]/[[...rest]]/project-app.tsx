"use client";

// The project page shell: header, section switch, view tabs, sort toggle,
// and the file list. Role rules (from the old frontend/index.html):
//   - Admin ("#admin" in the URL hash): section switch, all view tabs, and
//     the oldest/newest sort toggle (kept in localStorage "mediaManagerSort").
//   - Non-admin: fixed oldest-first sort. Audio shows the TODO and Approved
//     tabs. Video shows one focused designer queue with no navigation.
//   - A direct URL to a video view other than All or Trash: for an admin,
//     tab clicks then do not change the URL.

import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  apiBase,
  defaultView,
  isDirectViewUrl,
  parseProjectPath,
  projectPath,
  showsNavigation,
  VIEW_LABELS,
  visibleTabs,
  type Section,
} from "@/src/client/projectUrl";
import { useFileList } from "@/src/client/useFileList";
import { BulkApprove } from "./bulk-approve";
import { FileList } from "./file-list";

const SORT_KEY = "mediaManagerSort";

type Place = { section: Section; view: string; direct: boolean };

function readPlace(): Place {
  const { section, view } = parseProjectPath(window.location.pathname);
  return { section, view: view ?? defaultView(section), direct: isDirectViewUrl(view) };
}

function readStoredSort(): "asc" | "desc" {
  try {
    const value = window.localStorage.getItem(SORT_KEY);
    return value === "desc" ? "desc" : "asc";
  } catch {
    return "asc";
  }
}

export function ProjectApp({ token, project }: { token: string; project: string }) {
  // The URL path and hash are read in the browser only. Until then the page
  // shows the loading state (the server does not know the hash).
  const [place, setPlace] = useState<Place | null>(null);
  const [hash, setHash] = useState("");
  const [sortChoice, setSortChoice] = useState<"asc" | "desc" | null>(null);

  useEffect(() => {
    const onPop = () => setPlace(readPlace());
    const onHash = () => setHash(window.location.hash);
    onPop();
    onHash();
    window.addEventListener("popstate", onPop);
    window.addEventListener("hashchange", onHash);
    return () => {
      window.removeEventListener("popstate", onPop);
      window.removeEventListener("hashchange", onHash);
    };
  }, []);

  const admin = hash.includes("admin");
  const sort = !admin ? "asc" : sortChoice ?? (place ? readStoredSort() : "asc");
  const strict = place !== null && admin && place.section === "video" && place.direct;
  const base = apiBase(token, project);

  const query = useMemo(
    () => (place ? { apiBase: base, type: place.section, view: place.view, sort } : null),
    [base, place, sort],
  );
  const list = useFileList(query);

  const selectView = useCallback((view: string) => {
    if (!place) return;
    setPlace({ ...place, view });
    if (!strict) {
      window.history.replaceState(null, "", projectPath(token, project, place.section, view, window.location.hash));
    }
  }, [place, strict, token, project]);

  const selectSection = useCallback((value: string) => {
    const section: Section = value === "video" ? "video" : "audio";
    const view = defaultView(section);
    window.history.pushState(null, "", projectPath(token, project, section, view, window.location.hash));
    setPlace({ section, view, direct: isDirectViewUrl(view) });
  }, [token, project]);

  const toggleSort = useCallback(() => {
    const next = sort === "asc" ? "desc" : "asc";
    setSortChoice(next);
    try {
      window.localStorage.setItem(SORT_KEY, next);
    } catch {
      // The choice stays for this page only.
    }
  }, [sort]);

  const label = place ? VIEW_LABELS[place.view] ?? place.view : "Media Manager";
  const heading = place && list.status === "ready" ? `${label} (${list.count})` : label;
  const navigation = place !== null && showsNavigation(place.section, admin);

  const content = place ? (
    <FileList
      list={list}
      section={place.section}
      view={place.view}
      admin={admin}
      token={token}
      project={project}
    />
  ) : (
    <div role="status" className="text-muted-foreground">Loading…</div>
  );

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 p-4">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="mr-auto text-2xl font-semibold tracking-tight">{heading}</h1>
        {place && admin ? (
          <Tabs value={place.section} onValueChange={selectSection} aria-label="Switch section">
            <TabsList>
              <TabsTrigger value="audio">Audio</TabsTrigger>
              <TabsTrigger value="video">Video</TabsTrigger>
            </TabsList>
          </Tabs>
        ) : null}
        {admin ? (
          <Button variant="outline" onClick={toggleSort} title="Toggle sort order" aria-label={`Sort order: ${sort === "asc" ? "oldest" : "newest"} first`}>
            {sort === "asc" ? "Oldest" : "Newest"}
          </Button>
        ) : null}
      </header>

      {place && admin && place.section === "audio" && place.view === "todo" ? (
        <BulkApprove apiBase={base} onChanged={() => void list.reload()} />
      ) : null}

      {place && navigation ? (
        <Tabs value={place.view} onValueChange={selectView}>
          <nav aria-label="Views">
            <TabsList className="h-auto w-full flex-wrap justify-start">
              {visibleTabs(place.section, admin).map((view) => (
                <TabsTrigger key={view} value={view} className="flex-none">
                  {VIEW_LABELS[view]}
                </TabsTrigger>
              ))}
            </TabsList>
          </nav>
          <TabsContent value={place.view}>{content}</TabsContent>
        </Tabs>
      ) : (
        <main>{content}</main>
      )}
    </div>
  );
}
