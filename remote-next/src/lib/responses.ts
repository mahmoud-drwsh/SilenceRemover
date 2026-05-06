import { NextResponse } from "next/server";

export function jsonError(status: number, detail: string): NextResponse {
  return NextResponse.json({ detail }, { status });
}

export function httpException(
  status: number,
  detail: string,
  headers?: HeadersInit,
): never {
  throw new HttpError(status, detail, headers);
}

export class HttpError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly headers?: HeadersInit,
  ) {
    super(message);
    this.name = "HttpError";
  }
}

export function toNextResponse(err: unknown): NextResponse {
  if (err instanceof HttpError) {
    return NextResponse.json(
      { detail: err.message },
      { status: err.status, headers: err.headers },
    );
  }
  console.error(err);
  return NextResponse.json({ detail: "Internal Server Error" }, { status: 500 });
}
