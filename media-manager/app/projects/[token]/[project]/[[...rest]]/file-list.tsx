"use client";

// The list of one view: loading, error with retry, empty state, the cards,
// and "Load more". "Load more" also runs automatically when its button comes
// within 300 px of the viewport (as the old app did).

import { useEffect, useRef } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Empty, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import type { Section } from "@/src/client/projectUrl";
import type { useFileList } from "@/src/client/useFileList";
import { AudioCard } from "./audio-card";
import { VideoCard } from "./video-card";

type Props = {
  list: ReturnType<typeof useFileList>;
  section: Section;
  view: string;
  admin: boolean;
  token: string;
  project: string;
};

export function FileList({ list, section, view, admin, token, project }: Props) {
  const moreButton = useRef<HTMLButtonElement>(null);
  const { loadMore, loadingMore, loadMoreError, hasMore, status } = list;

  useEffect(() => {
    const button = moreButton.current;
    if (!button || status !== "ready" || !hasMore || loadingMore || loadMoreError) return;
    if (!("IntersectionObserver" in window)) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        observer.disconnect();
        void loadMore();
      }
    }, { rootMargin: "300px" });
    observer.observe(button);
    return () => observer.disconnect();
  }, [status, hasMore, loadingMore, loadMoreError, loadMore, list.files.length]);

  if (list.status === "loading") {
    return (
      <section aria-busy="true" className="flex flex-col gap-4">
        <div role="status" className="text-muted-foreground">Loading…</div>
        <div aria-hidden="true" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-32 w-full" />)}
        </div>
      </section>
    );
  }

  if (list.status === "error") {
    return (
      <section aria-busy="false" className="flex flex-col items-start gap-3">
        <Alert variant="destructive">
          <AlertTitle>Error: {list.error}</AlertTitle>
          <AlertDescription>The list could not load.</AlertDescription>
        </Alert>
        <Button variant="outline" onClick={() => void list.reload()}>Retry</Button>
      </section>
    );
  }

  if (list.files.length === 0) {
    return (
      <section aria-busy="false">
        <Empty className="border">
          <EmptyHeader>
            <EmptyTitle>No {section} files in this view</EmptyTitle>
          </EmptyHeader>
        </Empty>
      </section>
    );
  }

  return (
    <section aria-busy="false" className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {list.files.map((file, index) =>
          file.type === "audio" ? (
            <AudioCard key={file.id} file={file} titleId={`file-title-${index}`} />
          ) : (
            <VideoCard
              key={file.id}
              file={file}
              titleId={`file-title-${index}`}
              view={view}
              admin={admin}
              token={token}
              project={project}
            />
          ),
        )}
      </div>
      {hasMore ? (
        <div className="flex justify-center">
          <Button
            ref={moreButton}
            variant="outline"
            disabled={loadingMore}
            onClick={() => void loadMore()}
          >
            {loadingMore ? "Loading…" : loadMoreError ? `Retry loading more: ${loadMoreError}` : "Load more"}
          </Button>
        </div>
      ) : null}
    </section>
  );
}
