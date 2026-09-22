# MCP Server — setup guide

The **MCP server** is a read-only [Model Context Protocol](https://modelcontextprotocol.io)
endpoint that lets AI clients (Claude, ChatGPT, …) query your Process Mining data —
**metrics, paths and metadata** — over HTTP(S). Callers authenticate with an **OAuth access
token issued by your Authentik server**; the token is verified against Authentik's signing
keys and mapped to a Process Mining user, whose assigned database connections decide what
they may see. Nothing here can write — there are no ingest/edit/sampling tools.

It is the seventh surface, on the admin port **+40**: **HTTP 8130 / HTTPS 8493** in the
container, published by Docker at **18130 / 18493** on the host. It is **off until an
administrator enables it** (admin panel → *MCP Server* tab) and returns `503` while off.

```
AI client ──OAuth──▶ Authentik (:19443)          the client gets an access token
AI client ──MCP/JSON-RPC + Bearer token──▶ MCP server (:18493/mcp)
                          └─ verifies the token against Authentik's JWKS
                          └─ maps it to a Process Mining user
                          └─ answers read-only queries on that user's connections
```

---

## What the server exposes (MCP tools)

| Tool | Returns |
|------|---------|
| `list_connections` | The database connections you may query (id, name, schema). |
| `list_projects` | The process-mining projects on a connection — or, with `connectionId` omitted, on every connection you may query. |
| `get_process_map` | The directly-follows map: steps (nodes) + transitions (edges) with counts/timing. |
| `get_transition_metrics` | Per step-pair: count and avg/median/min/max/stddev transition time. |
| `get_variants` | Distinct journey paths and how often each occurs (most frequent first). |
| `get_statistics` | Journey count, journey-duration stats, process-goodness score. |
| `get_metadata` | Meta-attribute titles, step names, and the event date range. |
| `get_journey` | One case's ordered events, by business case id or stored hash. |
| `find_journeys` | The individual journeys behind an aggregate: slowest cases, cases that visited a step, longest traces. |

All query tools accept `connectionId` + `projectId` and an optional filter (`sampleSet`,
`fromDate`, `toDate`, `includedSteps`, `excludedSteps`, `meta1..3`); `get_variants` also
takes `limit`. `get_journey` takes `connectionId` + `projectId` + `eventId` (and
`sampleSet`) instead of the filter — it resolves a business id like `FLT-000123` by
MD5-hashing it, the same way ingest does.

**`list_projects` across connections.** `connectionId` is optional: omit it and the tool
returns every project on every connection assigned to you, each entry tagged with its
`connectionId` and `connectionName`. Add `includeCounts: true` for a `journeyCount` per
project (one count query each), which answers "which process has the most journeys?" in a
single call. A connection that cannot be opened yields one entry carrying `error` instead
of a project, so one unreachable database does not fail the whole listing.

**`find_journeys` — from the aggregate to the cases.** Every other tool summarises many
journeys; `get_journey` needs a case id you already have. `find_journeys` closes the gap:
it returns one row per case (stored id, start/end, duration, step count, meta attributes)
for any filter, ordered by `orderBy` — `DURATION_DESC` (the default, slowest first),
`DURATION_ASC`, `START_DESC`, `START_ASC`, `STEPS_DESC`, `STEPS_ASC`. It also takes
`limit` (default 20), `minDurationSecs` / `maxDurationSecs`, `minSteps` / `maxSteps`, and
`includePath` to add each journey's full step path. The returned `eventId` is the stored
MD5 — `JOURNEYS` never holds the plaintext business id — and `get_journey` accepts it
as-is, so the drill-down is: `get_statistics` → `find_journeys` → `get_journey`.

```jsonc
// The five slowest bookings that reached "Payment Failed", with their paths
{"name": "find_journeys", "arguments": {
  "connectionId": "…", "projectId": 1, "limit": 5,
  "includedSteps": ["Payment Failed"], "includePath": true}}
```

---

## Prerequisites

- An **Authentik** server reachable from the Process Mining host (this guide assumes
  `https://authentik.example.com:19443`).
- Administrator access to both Authentik and the Process Mining admin console.
- Each MCP user must **already exist and be enabled** in Process Mining (Users tab) with the
  **same username** the token will carry (see “username claim” below), and must be
  **assigned the connection(s)** they should query (Database Connections tab).

---

## Part A — Configure Authentik

1. **Create an OAuth2/OpenID Provider**
   *Applications → Providers → Create → OAuth2/OpenID Provider.*
   - **Name**: `Process Mining MCP`.
   - **Authorization flow**: your standard `default-provider-authorization-explicit-consent`
     (or implicit-consent).
   - **Client type**: `Public` (recommended for interactive clients that use PKCE) — or
     `Confidential` if your client stores a secret.
   - **Redirect URIs**: add the callback(s) your client uses. For **Claude** these are:
     - `https://claude.ai/api/mcp/auth_callback`
     - `https://claude.com/api/mcp/auth_callback`
     - and, for Claude Desktop, a local loopback such as `http://localhost:*` (use the exact
       value Claude shows you if it differs).
   - **Signing Key**: pick an RSA key (the access token is then a signed RS256 JWT the MCP
     server can verify offline). Note the key.
   - **Scopes**: include `openid`, `profile`, `email` (add `offline_access` if you want
     refresh tokens).
   - Save, then open the provider and note its **Client ID** (and secret, if confidential).

2. **Create an Application** bound to that provider
   *Applications → Applications → Create.*
   - **Name**: `Process Mining MCP`, **Slug**: e.g. `process-mining-mcp`.
   - **Provider**: the provider from step 1.
   - Under **Policy / Group / User Bindings**, restrict who may use it (e.g. bind a group
     `process-mining-users`). You can enforce the same group again in the MCP server settings.

3. **Note the endpoints.** With the slug above, Authentik publishes (all under
   `https://authentik.example.com:19443/application/o/process-mining-mcp/`):
   - **Issuer**: `.../application/o/process-mining-mcp/`
   - **Discovery**: `…/.well-known/openid-configuration`
   - **JWKS**: `…/jwks/`

   > **Access-token audience.** Authentik's access token may not set `aud` to your client id
   > unless you add an audience via a scope/property mapping. If you want the MCP server to
   > check `aud`, add that mapping and set the client id as the audience; otherwise leave the
   > MCP **Audience** field blank — the issuer, signature and group checks still apply.

   > **Dynamic Client Registration (DCR).** Some clients register themselves automatically.
   > If yours does and you prefer that, enable DCR in Authentik; otherwise the manual
   > provider above is all you need and you give the client the Client ID directly.

---

## Part B — Configure the MCP server (admin console)

1. Open the admin console → **MCP Server** tab.
2. Fill in **Authentik (OAuth) settings**:
   - **Issuer URL** — `https://authentik.example.com:19443/application/o/process-mining-mcp/`
   - **JWKS URL** — leave blank to auto-discover from the issuer, or paste `…/jwks/`.
   - **Audience / Client ID** — the client id if you configured the token's `aud`; else blank.
   - **Required group** — optional; only members of this Authentik group may connect
     (matched against the token's `groups` claim).
   - **Username claim** — the JWT claim matched (case-insensitively) to a Process Mining
     username. Default `preferred_username`; use `email` if your usernames are email
     addresses.
3. Press **Save settings**, then **Test Authentik** — it fetches the discovery document and
   JWKS and reports the signing-key count. Fix any error before continuing.
4. Tick **Enable the MCP server**. (Enabling/disabling is immediate; no restart.)

> **TLS.** The server follows the same TLS mode and certificate as the app and admin console.
> Turn TLS on in the **TLS / SSL** tab and use the **HTTPS** endpoint (`:18493`) — OAuth
> clients require HTTPS. A TLS change takes effect after **↻ Restart app server** (App Control).

---

## Behind a reverse proxy

The MCP server listens on its own port (container `8130`/`8493`, host `18130`/`18493`). If you
expose it under a public domain path — e.g. `https://pm.example.com/mcp` — the proxy must:

1. **Preserve the path.** Forward `/mcp` to the backend as `/mcp`, not stripped to `/`. In
   nginx, `proxy_pass http://mcp-backend:8493;` (no trailing slash) preserves it;
   `proxy_pass http://mcp-backend:8493/;` (trailing slash) **strips** the prefix and the
   backend then sees `/` (you'd get a `404 {"detail":"Not Found"}`). The server also answers
   at the root as a fallback, so a stripping proxy still works — but preserving the path is
   cleaner. Route `/mcp`, `/.well-known/oauth-protected-resource` (and its `…/mcp` suffix) and
   `/health` to the backend.
2. **Send forwarding headers.** Set `X-Forwarded-Proto` and `X-Forwarded-Host` so the OAuth
   discovery document advertises the public `https://pm.example.com/mcp`, not the internal
   host:port.

Example nginx:

```nginx
location /mcp {
    proxy_pass https://127.0.0.1:18493;   # no trailing slash — keep the /mcp path
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host  $host;
}
location = /.well-known/oauth-protected-resource      { proxy_pass https://127.0.0.1:18493; proxy_set_header X-Forwarded-Host $host; proxy_set_header X-Forwarded-Proto $scheme; }
location = /.well-known/oauth-protected-resource/mcp  { proxy_pass https://127.0.0.1:18493; proxy_set_header X-Forwarded-Host $host; proxy_set_header X-Forwarded-Proto $scheme; }
```

Point the client at the public URL (`https://pm.example.com/mcp`). Alternatively, skip the
proxy and expose the MCP port directly (`https://<host>:18493/mcp`) if your firewall allows it
and TLS is enabled in the admin console.

---

## Part C — Add the server to an AI client

### Claude (claude.ai / Claude Desktop)

1. **Settings → Connectors → Add custom connector**.
2. **Name**: `Process Mining`. **URL**: `https://<your-host>:18493/mcp`.
3. Save and click **Connect**. Claude discovers Authentik from the server's
   `/.well-known/oauth-protected-resource` document, opens Authentik's sign-in, and (after you
   approve) stores the token. The Process Mining tools then appear in the connector.
4. In a chat, enable the connector and ask e.g. *“list my process-mining connections”*, then
   *“show the process map for project 1 on connection c1”*.

The same pattern applies to any MCP client that supports **remote (HTTP) servers with OAuth**:
point it at `https://<your-host>:18493/mcp`.

---

## Verifying by hand

Discovery (no auth):

```bash
curl -k https://<your-host>:18493/.well-known/oauth-protected-resource
```

A call with a token you already obtained from Authentik:

```bash
curl -k -X POST https://<your-host>:18493/mcp \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "arguments":{},"params":{"name":"list_connections","arguments":{}}}'
```

`GET /health` (unauthenticated) returns `{"ok":true,"enabled":<bool>}`.

---

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `503 The MCP server is disabled` | Enable it in the admin MCP tab. |
| `401` + a `WWW-Authenticate` header | No/invalid token — the client should run the OAuth flow. Check the issuer/JWKS in the MCP tab and press **Test Authentik**. |
| `403 No enabled Process Mining user matches '…'` | The token's username claim doesn't match an enabled PM user. Create the user (Users tab) with that exact name, or change the **Username claim** (e.g. to `email`). |
| `403 …not in the group required` | The user isn't in the configured **Required group** in Authentik. |
| `Connection … is not assigned to you` | Assign the connection to the user (Database Connections tab). |
| Test says it can't reach Authentik | Wrong issuer URL or the host can't reach `:19443`. The server does not verify Authentik's TLS certificate (internal host), but the URL and network path must be right. |

## Security notes

- Tokens are verified **cryptographically** against Authentik's JWKS (RS256); only the JWKS
  **transport** skips certificate verification (Authentik is a trusted internal host), which
  does not weaken token integrity.
- The MCP server is **read-only** and never exposes more than the mapped user's assigned
  connections — the same boundary as the app.
- Configure `PMW_MCP_MAX_ROWS` (default 1000) to cap rows returned per call, and
  `PMW_MCP_JWKS_CACHE_SECS` (default 3600) for how long signing keys are cached.
