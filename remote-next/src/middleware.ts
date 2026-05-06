import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { SECURITY_HEADERS } from "@/lib/security";

export function middleware(_request: NextRequest): NextResponse {
  const res = NextResponse.next();
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
    res.headers.set(name, value);
  }
  return res;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
