<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Authentication, SSO, and API tokens

All-Ontology authenticates through [Better Auth](https://github.com/better-auth/better-auth)
and authorizes every call against the caller's role. Self-service sign-up is
disabled: the first account is the bootstrap admin from
`ALL_ONTOLOGY_ADMIN_EMAIL` / `ALL_ONTOLOGY_ADMIN_PASSWORD` (Helm: `adminEmail` /
`adminPassword`).

Every `/api/...` route resolves the caller in one place,
[`frontend/auth/resolve-user.ts`](../frontend/auth/resolve-user.ts), in this
order:

1. Browser session cookie
2. All-Ontology API token (`x-api-key`, or `Authorization: Bearer`)
3. OAuth bearer issued by All-Ontology to an MCP client
4. SSO ID token forwarded by a trusted caller

Authentication answers *who* the caller is. Data visibility is a second,
independent decision: an authenticated viewer sees the union of Zones granted
directly to their user id and Zones granted to their departments. Admins are
unscoped. See [data-access.md](./architecture/data-access.md) for the model,
default-deny behavior, and management endpoints.

## SSO

Configure SSO under **Settings → Single Sign-On**. Register this redirect URI
with the identity provider:

```text
<APP_URL>/api/auth/sso/callback
```

## API tokens

A browser gets a session cookie; scripts, notebooks, and scheduled jobs use an
API token instead.

1. Open the user menu (top right) → **API Tokens** → **New token**.
2. Name it, optionally set an expiry (default: never), and copy the token.
   All-Ontology stores only a SHA-256 hash, so the token is shown once. If you
   lose it, mint a new one.

Send it as `x-api-key` (or `Authorization: Bearer <token>`) on any `/api/...`
call:

```sh
curl -H "x-api-key: $ALL_ONTOLOGY_API_TOKEN" https://all-ontology.example.com/api/terms
```

```python
import os
import requests

session = requests.Session()
session.headers["x-api-key"] = os.environ["ALL_ONTOLOGY_API_TOKEN"]
terms = session.get("https://all-ontology.example.com/api/terms").json()
```

For the streaming question API, see
[conversation-api.md](./conversation-api.md).

How tokens behave:

- **A token acts as its owner.** It has no permissions of its own; each call is
  authorized against the owner's role, as in the browser. A viewer's token can
  do what a viewer can.
- **Every authenticated route accepts it.** Any operation in
  [`openapi/all-ontology-api.json`](./openapi/all-ontology-api.json) that
  requires authentication works with a token.
- **Revocation is immediate.** Delete the token, or delete or ban its owner,
  and the next request returns 401.
- **Tokens cannot manage tokens.** Creating and revoking tokens requires a
  signed-in session, so a leaked token cannot mint its own successors.

## Delegated identity (trusted MCP gateways)

Some agent platforms can name the person a request is for but cannot hold that
person's token. For those deployments All Ontology accepts a delegated subject
from a gateway that proves itself with a shared key:

```text
x-all-ontology-delegation-key: <ALL_ONTOLOGY_DELEGATION_KEY>
x-all-ontology-subject: alice@example.com
```

Enable it by setting `ALL_ONTOLOGY_DELEGATION_KEY` on the frontend (at least 32
random characters); while it is unset the headers are ignored. The MCP server's
`ALL_ONTOLOGY_MCP_DELEGATION_KEY` must carry the same value. See
[mcp.md](./mcp.md#per-user-identity-for-embedded-deployments) for the server
side.

How the subject is resolved:

1. `email:<address>` — exact user email.
2. `sso:<subject>` — the IdP subject stored as `account.accountId`.
3. `id:<user id>` — the All Ontology user id.
4. A bare value is tried as email, then SSO subject, then user id.

Only a non-banned user resolves; anything else is a 401. The request then goes
through the same authorization as a signed-in session: the Python API derives
the user's departments, enabled zones, and zone permissions on every request,
and knowledge networks additionally apply their explicit grants. Departments
and zone ids are never accepted from the caller — only the person is named.

That also means departments are All Ontology's record, not the gateway's: keep
membership current under **Settings → Departments** (or sync it from your
directory) so zone grants and knowledge-network grants follow automatically.

Security properties:

- The key is equivalent to "may act as any user". Keep it in the gateway's
  secret store, never in a browser or model context, and rotate both sides
  together.
- Delegation is **off** unless the key is configured; a missing or wrong key is
  rejected rather than falling through to anonymous access.
- Each delegated request logs one line pairing the subject with the resolved
  user id, so an audit can explain why data was visible.
