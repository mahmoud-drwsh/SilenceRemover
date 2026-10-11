"use client";

/**
 * Paged file list for one section and view (same rules as the old
 * frontend/index.html):
 *
 * - GET <api>/files?type=<section>[&view=<view>]&sort=<asc|desc>&limit=24&offset=<n>
 *   (no view parameter for All). It reads X-Has-More, and X-Total-Count
 *   (only on the first page).
 * - After each page, the next page is prefetched when the browser is idle.
 *   A prefetch error is ignored; "load more" then fetches the page again.
 * - A new query (other section, view, or sort) or reload() starts a new load
 *   sequence. Responses of an old sequence are ignored, and its requests are
 *   cancelled.
 * - Later tickets call reload() after an action (save, trash, restore,
 *   delete, upload), as the old app did.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { FileResponse } from "../server/schemas.ts";

export type { FileResponse };

export const PAGE_SIZE = 24;

type Page = { files: FileResponse[]; hasMore: boolean; totalCount: number | null; offset: number };

export type FileListQuery = { apiBase: string; type: "audio" | "video"; view: string; sort: "asc" | "desc" };

export type FileListState = {
  status: "loading" | "ready" | "error";
  files: FileResponse[];
  /** X-Total-Count of the first page, else the number of loaded files. */
  count: number;
  hasMore: boolean;
  /** Error text of the first page. */
  error: string | null;
  loadingMore: boolean;
  /** Error text of the last "load more". */
  loadMoreError: string | null;
};

const INITIAL: FileListState = {
  status: "loading",
  files: [],
  count: 0,
  hasMore: false,
  error: null,
  loadingMore: false,
  loadMoreError: null,
};

async function fetchPage(query: FileListQuery, offset: number, signal: AbortSignal): Promise<Page> {
  let url = `${query.apiBase}/files?type=${query.type}`;
  if (query.view !== "all") url += `&view=${encodeURIComponent(query.view)}`;
  url += `&sort=${query.sort}&limit=${PAGE_SIZE}&offset=${offset}`;
  const res = await fetch(url, { signal, cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  return {
    files: (await res.json()) as FileResponse[],
    hasMore: res.headers.get("X-Has-More") === "true",
    totalCount: Number(res.headers.get("X-Total-Count")) || null,
    offset,
  };
}

function message(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function onIdle(callback: () => void): () => void {
  if (typeof window.requestIdleCallback === "function") {
    const handle = window.requestIdleCallback(callback, { timeout: 1500 });
    return () => window.cancelIdleCallback(handle);
  }
  const handle = window.setTimeout(callback, 200);
  return () => window.clearTimeout(handle);
}

export function useFileList(query: FileListQuery | null) {
  const [state, setState] = useState<FileListState>(INITIAL);
  const sequence = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const nextOffset = useRef(0);
  const prefetched = useRef<{ offset: number; page: Promise<Page> } | null>(null);
  const cancelPrefetch = useRef<(() => void) | null>(null);
  const loadingMore = useRef(false);
  const { apiBase, type, view, sort } = query ?? {};

  const schedulePrefetch = useCallback((id: number, q: FileListQuery, signal: AbortSignal) => {
    cancelPrefetch.current?.();
    cancelPrefetch.current = onIdle(() => {
      if (id !== sequence.current) return;
      const offset = nextOffset.current;
      const page = fetchPage(q, offset, signal);
      page.catch(() => {});
      prefetched.current = { offset, page };
    });
  }, []);

  const reload = useCallback(async () => {
    if (!apiBase || !type || !view || !sort) return;
    const q: FileListQuery = { apiBase, type, view, sort };
    const id = ++sequence.current;
    controller.current?.abort();
    cancelPrefetch.current?.();
    const ac = new AbortController();
    controller.current = ac;
    prefetched.current = null;
    loadingMore.current = false;
    setState(INITIAL);
    try {
      const page = await fetchPage(q, 0, ac.signal);
      if (id !== sequence.current) return;
      nextOffset.current = page.files.length;
      setState({
        ...INITIAL,
        status: "ready",
        files: page.files,
        count: page.totalCount ?? page.files.length,
        hasMore: page.hasMore,
      });
      if (page.hasMore) schedulePrefetch(id, q, ac.signal);
    } catch (err) {
      if (id !== sequence.current) return;
      setState({ ...INITIAL, status: "error", error: message(err) });
    }
  }, [apiBase, type, view, sort, schedulePrefetch]);

  const loadMore = useCallback(async () => {
    if (!apiBase || !type || !view || !sort || loadingMore.current) return;
    const q: FileListQuery = { apiBase, type, view, sort };
    const id = sequence.current;
    const ac = controller.current;
    if (!ac) return;
    loadingMore.current = true;
    setState((s) => ({ ...s, loadingMore: true, loadMoreError: null }));
    try {
      const offset = nextOffset.current;
      const ready = prefetched.current?.offset === offset ? prefetched.current.page : null;
      prefetched.current = null;
      const page = await (ready ?? Promise.reject(new Error("no prefetch"))).catch(() => fetchPage(q, offset, ac.signal));
      if (id !== sequence.current) return;
      nextOffset.current = offset + page.files.length;
      setState((s) => ({
        ...s,
        files: [...s.files, ...page.files],
        hasMore: page.hasMore,
        loadingMore: false,
        loadMoreError: null,
      }));
      if (page.hasMore) schedulePrefetch(id, q, ac.signal);
    } catch (err) {
      if (id !== sequence.current) return;
      setState((s) => ({ ...s, loadingMore: false, loadMoreError: message(err) }));
    } finally {
      if (id === sequence.current) loadingMore.current = false;
    }
  }, [apiBase, type, view, sort, schedulePrefetch]);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => () => {
    controller.current?.abort();
    cancelPrefetch.current?.();
  }, []);

  return { ...state, reload, loadMore };
}
