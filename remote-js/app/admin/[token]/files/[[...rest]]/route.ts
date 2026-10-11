import { removedFileBrowserRoute } from "../../../../../src/server/admin.ts";

export const dynamic = "force-dynamic";

// /admin/:token/files and /admin/:token/files/* (all methods, also with a
// trailing slash): token check, then 404 "Admin File Browser has been removed".
export {
  removedFileBrowserRoute as GET,
  removedFileBrowserRoute as HEAD,
  removedFileBrowserRoute as POST,
  removedFileBrowserRoute as PUT,
  removedFileBrowserRoute as PATCH,
  removedFileBrowserRoute as DELETE,
  removedFileBrowserRoute as OPTIONS,
};
