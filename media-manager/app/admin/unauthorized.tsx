import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

// The HTML error page for the admin page with a bad admin token (status 401).
// The admin API keeps the JSON 401 {"detail": "Invalid admin token"}.
export default function AdminUnauthorized() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-lg items-center p-4">
      <Alert variant="destructive">
        <AlertTitle>Invalid admin token</AlertTitle>
        <AlertDescription>
          <p>The admin token in this link is not correct. Use the current admin link.</p>
        </AlertDescription>
      </Alert>
    </main>
  );
}
