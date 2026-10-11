/**
 * Admin audit-log writer. Mirrors `_audit_admin_event` in remote/app.py - we
 * never let an audit failure abort the originating admin request.
 */

import { getDb, schemaIdent } from "./db.ts";

export interface AuditEventRequest {
  peerIp: string;
  userAgent: string;
}

export async function writeAdminAuditEvent(
  email: string,
  action: string,
  request: AuditEventRequest,
  details: Record<string, unknown> = {},
): Promise<void> {
  try {
    const sql = getDb();
    const ident = schemaIdent();
    await sql.unsafe(
      `
      INSERT INTO ${ident}.admin_audit_log
        (email, action, ip_address, user_agent, details)
      VALUES ($1, $2, $3, $4, $5::jsonb)
      `,
      [
        email,
        action,
        request.peerIp,
        request.userAgent,
        JSON.stringify(details ?? {}),
      ],
    );
  } catch (err) {
    console.warn(
      `[ADMIN AUDIT WARNING] Failed to write audit event ${JSON.stringify(action)}: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }
}
