"use client";

// The player page body (#58): the title, a Close button, and the stock
// Vidstack player (default video layout) on the stream route. Seeking uses
// HTTP Range requests on the stream route.
//   - Close: close the tab when a page opened it (window.opener), else go back.
//   - No `file` query parameter: "Missing video id."
//   - The video cannot play (for example the stream route gives 404):
//     "Unable to play this video."

import "@vidstack/react/player/styles/default/theme.css";
import "@vidstack/react/player/styles/default/layouts/video.css";
import { useEffect, useState } from "react";
import { isVideoProvider, MediaPlayer, MediaProvider } from "@vidstack/react";
import { DefaultVideoLayout, defaultLayoutIcons } from "@vidstack/react/player/layouts/default";
import { Alert, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { streamUrl } from "@/src/client/projectUrl";

type Props = { token: string; project: string; fileId: string; title: string };

function closePlayer() {
  if (window.opener && !window.opener.closed) {
    window.close();
    return;
  }
  window.history.back();
}

export function VideoPlayer({ token, project, fileId, title }: Props) {
  const [failed, setFailed] = useState(false);
  // Give the source to the player only after hydration. On the server,
  // Vidstack renders the source as a <source> child, and the browser starts
  // to load it before hydration. After hydration, Vidstack loads the same
  // source again (abort, emptied, and a new load). Thus the duration was
  // NaN for a short time after the first "loadedmetadata", and the stream
  // was requested two times. With the source only on the client, the
  // browser loads it one time.
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => setHydrated(true), []);
  const src = streamUrl(token, project, fileId, "video");
  const message = !fileId ? "Missing video id." : failed ? "Unable to play this video." : null;

  return (
    <main className="mx-auto flex min-h-svh w-full max-w-5xl flex-col gap-4 p-4">
      <header className="flex items-center justify-between gap-4">
        <h1 dir="auto" className="min-w-0 break-words text-xl font-semibold">{title}</h1>
        <Button variant="outline" onClick={closePlayer}>Close</Button>
      </header>
      <section aria-live="polite" aria-busy="false">
        {message ? (
          <Alert variant="destructive">
            <AlertTitle>{message}</AlertTitle>
          </Alert>
        ) : (
          // The stream URL has no file extension, so the source type tells
          // Vidstack to use its HTML5 video provider. The browser reads the
          // real type from the response.
          <MediaPlayer
            title={title}
            src={hydrated ? { src, type: "video/mp4" } : undefined}
            preload="metadata"
            playsInline
            onError={() => setFailed(true)}
            // Vidstack gives the stream URL to a <source> child. A load
            // error (for example a 404) fires on that <source>, not on the
            // <video>, and the "error" event does not bubble. A capture
            // listener on the <video> gets it.
            onProviderSetup={(provider) => {
              if (isVideoProvider(provider)) {
                provider.video.addEventListener("error", () => setFailed(true), true);
              }
            }}
          >
            <MediaProvider />
            <DefaultVideoLayout icons={defaultLayoutIcons} />
          </MediaPlayer>
        )}
      </section>
    </main>
  );
}
