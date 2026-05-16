# Plan: Use temporary direct S3 URLs for Media Manager downloads

## Context

The current Media Manager stream route validates the project token, file metadata, trash state, MIME-derived extension, and safe download filename before serving bytes through the Bun service. For responses at or below the in-process buffer threshold, it fetches the S3 object into a `Uint8Array` so Bun preserves `Content-Length`; larger responses stream through Bun.

That fixes missing file-size display for small/medium downloads, but it keeps the VPS in the media data path and makes memory usage scale with concurrent buffered downloads.

## Goal

Move download and playback byte transfer off the VPS by issuing short-lived S3-compatible pre-signed GET URLs after the existing application-level authorization checks pass.

Desired steady-state flow:

1. Browser requests the existing Media Manager stream URL.
2. Bun validates the media token, project, file ID, type, database row, trash state, object existence, MIME type, and safe filename.
3. Bun signs a temporary S3 GET URL for the exact object key.
4. Bun returns a redirect to the signed URL.
5. Browser downloads or plays media directly from object storage.

## Recommended approach

### 1. Keep the existing public route

Keep the route shape unchanged:

```text
GET /projects/:token/:project/stream/:id?type=audio|video
```

Returning a redirect from the existing route minimizes frontend changes because anchors and media elements can keep using the same Media Manager URL.

### 2. Add an S3 presigner dependency

Add the AWS SDK presigner package to `remote-js/package.json`:

```json
"@aws-sdk/s3-request-presigner": "<compatible version>"
```

Use the same major/minor SDK family as `@aws-sdk/client-s3` where practical.

### 3. Add a storage helper

Add a helper near the other S3 helpers in `remote-js/src/storage.ts`:

```ts
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";

export async function storagePresignGetUrl(
  fileType: "audio" | "video",
  project: string,
  fileId: string,
  ext: string,
  options: {
    expiresInSeconds: number;
    contentType: string;
    contentDisposition: string;
  },
): Promise<string> {
  const config = loadConfig();
  const command = new GetObjectCommand({
    Bucket: config.s3Bucket,
    Key: storageObjectKey(fileType, project, fileId, ext),
    ResponseContentDisposition: options.contentDisposition,
    ResponseContentType: options.contentType,
  });

  return getSignedUrl(getS3Client(), command, {
    expiresIn: options.expiresInSeconds,
  });
}
```

Notes:

- Reuse the existing singleton `S3Client`; it already has endpoint, region, force-path-style, and credentials configured.
- Keep object-key construction centralized through `storageObjectKey()`.
- Do not hardcode any deployment domain in code.

### 4. Redirect after the existing route checks

In `remote-js/src/routes/stream.ts`, keep the current validation and metadata lookup logic. After `storageHead()` confirms the object exists and after `downloadFilename` is computed, generate the pre-signed URL and return a redirect:

```ts
const signedUrl = await storagePresignGetUrl(row.type, project, decodedId, ext, {
  expiresInSeconds: 10 * 60,
  contentType: row.mime_type,
  contentDisposition: `inline; filename*=UTF-8''${encodeURIComponent(downloadFilename)}`,
});

return c.redirect(signedUrl, 302);
```

A ten-minute expiry is a reasonable default for human-triggered download/playback starts. If downloads may sit queued before the browser opens the URL, consider fifteen minutes.

### 5. Preserve a proxy fallback while proving compatibility

S3-compatible providers differ in small ways. Keep the existing proxy-stream implementation available behind a temporary environment flag while validating production behavior:

```text
MEDIA_MANAGER_DIRECT_S3_DOWNLOADS=true
```

Recommended rollout behavior:

- Default new deployments to direct S3 redirects once verified.
- Allow `MEDIA_MANAGER_DIRECT_S3_DOWNLOADS=false` to force the old proxy path during rollback.
- Remove the proxy fallback later only after direct URLs are proven across the chosen storage provider, browser download flow, and video playback flow.

### 6. CORS and storage-provider checks

For plain browser redirects, CORS is usually less important than it would be for JavaScript `fetch()` calls. Still verify:

- Direct navigation/download works from the project page.
- `<video>` / `<audio>` playback works after the redirect.
- Range requests work on the object storage endpoint.
- `ResponseContentDisposition` produces the expected edited-title filename.
- `ResponseContentType` is respected by the provider.

If the frontend later fetches signed URLs via JavaScript and reads response headers, configure CORS on the bucket accordingly.

## Security considerations

- A pre-signed URL is a bearer credential. Anyone who receives it can access that object until expiry.
- Use short expiries, preferably five to fifteen minutes.
- Existing Media Manager authorization still happens before issuing the URL.
- Trashed files must continue to return `404` before signing.
- Object keys will be visible in browser network tools; this does not expose S3 secrets, but it may reveal project/file identifiers.
- Revocation is effectively TTL-based unless the object is deleted, renamed, or credentials are rotated.

## Operational impact

Benefits:

- Eliminates buffered-download memory spikes on the VPS for the direct path.
- Removes long-lived media transfer connections from Bun.
- Reduces VPS bandwidth usage.
- Lets object storage handle range requests and slow clients.

Tradeoffs:

- Browser-visible URLs point at the S3-compatible endpoint during the signed URL lifetime.
- Download behavior depends on provider support for response header overrides.
- Access revocation is not instantaneous after a URL is issued.

## Testing checklist

- `bun run typecheck` in `remote-js/`.
- `bun test` in `remote-js/`.
- Request an audio stream URL and confirm a `302` response with a signed S3 URL.
- Download an audio file and confirm the filename uses the edited title.
- Request a video stream URL in the browser and confirm playback starts.
- Confirm browser/media-player range requests receive valid partial responses from S3.
- Confirm trashed files and invalid tokens never produce signed URLs.
- Temporarily disable direct S3 downloads with the rollback flag and confirm the proxy path still works.
