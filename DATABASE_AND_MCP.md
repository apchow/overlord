# Overlord database and MCP integration

## Storage architecture

Overlord now uses SQLAlchemy and a relational schema. `DATABASE_URL` selects the backend:

- **Local / no environment variable:** SQLite at `workspace/overlord.sqlite3`.
- **Competition deployment:** managed PostgreSQL. Set `DATABASE_URL` to the provider's private URL. Render's local filesystem is ephemeral unless a persistent disk is attached; use Render Postgres for durable hosted records.

The app writes audit runs, rule violations, and policy revisions to SQL. It keeps the existing JSONL compliance receipt as a readable compatibility/export ledger. Each SQL compliance event has a SHA-256 link to the previous event; policy changes are also captured as hash-chained events. SQLite installs append-only triggers for the event table, and `verify_compliance_ledger()` recomputes every link. This is tamper-evident, not a replacement for an independently administered WORM archive or signed external audit log.

Tables:

- `audit_runs`: one row per completed PO / GR / invoice audit.
- `policy_violations`: one row per triggered rule, linked to the audit.
- `policy_revisions`: versioned snapshots and SHA-256 hashes of policy configs.
- `audit_feedback`: explicit confirmed / false-positive / needs-review labels from a reviewer.
- `compliance_events`: append-only, hash-chained audit, policy, and reviewer-feedback events.

## Governed continuous improvement

The improvement agent reads reviewer labels attached to completed audits. It needs repeated feedback on independent audits before it will draft a policy severity change. Repeated false-positive labels produce a recommendation to narrow the rule, not an automatic edit. The proposal is inserted into the existing policy editor; a person reviews it and explicitly activates it through **Apply Approved Draft & Re-Run Audit**. The agent does not rewrite Python source, learn from unreviewed model output, or silently modify payment controls.

SQLAlchemy creates missing tables on startup. For a serious multi-instance production rollout, deploy schema changes through reviewed migrations and use a managed database backup/restore policy.

### Configure a hosted database

1. Create a PostgreSQL database in Render (or use another managed provider).
2. Set the app's `DATABASE_URL` environment variable to the **private/internal** PostgreSQL URL. The app accepts `postgres://` and `postgresql://` and normalizes them to Psycopg 3.
3. Install dependencies with `pip install -r requirements.txt` and restart the web service.
4. Check the sidebar's **STORAGE** card; it reports the backend, record counts, and DB ledger-chain verification.

Do not commit real database URLs or credentials. `workspace/overlord.sqlite3` is the fallback for development, not a durable Render deployment unless that path is on a persistent disk.

## MCP server

`mcp_server.py` is a local **Model Context Protocol (MCP)** server using the official Python SDK's `FastMCP` and stdio transport. It shares the same policy engine and SQL database as the Gradio app. It exposes these tools:

1. `get_storage_status`
2. `list_active_policies`
3. `evaluate_policy_context`
4. `add_or_replace_policy_config`
5. `create_policy_rule`
6. `get_recent_audits`
7. `get_audit_details`
8. `list_policy_history`
9. `submit_audit_feedback`
10. `analyze_continuous_improvement`
11. `verify_compliance_ledger`

Run locally from the project root:

```bash
python mcp_server.py
```

The process uses MCP stdio and is intended to be launched by an MCP-compatible desktop/IDE client. A generic client configuration looks like this (replace the script path with the absolute path on your machine):

```json
{
  "mcpServers": {
    "overlord-audit": {
      "command": "python",
      "args": ["/absolute/path/to/overlord/mcp_server.py"],
      "env": {
        "DATABASE_URL": "sqlite:////absolute/path/to/overlord/workspace/overlord.sqlite3"
      }
    }
  }
}
```

For hosted PostgreSQL, configure the same `DATABASE_URL` in the MCP client's environment, using a secret manager rather than a committed config file. Do not run this stdio server as an unauthenticated public web service. `create_policy_rule` and `add_or_replace_policy_config` alter active financial controls; only grant them to trusted clients and require human approval in the MCP client.

The Gradio app directly calls the shared deterministic services and writes to the shared database. The MCP server makes the same capabilities available to external MCP clients; it does not silently hand control of payment approvals to an LLM.
