import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

// The HTML error page for a page route with a bad token (status 401).
// Pages call unauthorized() from next/navigation after the server-side
// token check. API routes keep the JSON 401 {"detail": ...}.
export default function Unauthorized() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-lg items-center p-4">
      <Alert variant="destructive">
        <AlertTitle>Invalid link</AlertTitle>
        <AlertDescription>
          <p>The access token in this link is not correct. Ask the admin for the current project link.</p>
        </AlertDescription>
      </Alert>
    </main>
  );
}
