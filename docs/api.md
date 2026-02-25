# API Usage

The service exposes a [FastAPI](https://fastapi.tiangolo.com/) application. Once
running, interactive documentation is available via the automatically generated
Swagger UI:

- **Swagger UI**: `http://localhost:${FLASK_PORT}/docs`

All REST endpoints are served under the `/api/v1` prefix.

## Authentication

Every request except for the health check requires an `Authorization` header
with a bearer token:

```
Authorization: Bearer <token>
```

### Admin tokens

Admin API tokens are stored in the database. A super-admin can view the
current token and generate a new one via the following endpoints:

```
GET /api/v1/admin/token
POST /api/v1/admin/token
```
Use the returned `api_token` value as the bearer token for privileged requests.

### Agent tokens

Agent API tokens are stored hashed in the database while a copy of the raw
token is kept so agents can retrieve it later.

Agents may view their current token:

```
GET /api/v1/agents/me/token
```

Agents may also rotate their own token:

```
POST /api/v1/agents/me/token
```

Agents can also view or rotate their token directly from the Telegram bot via
the **API Token** menu. Administrators may view or rotate any agent's token
through the bot's agent management panel. Super administrators can view or
rotate the global admin token from the Admin Panel in the bot.

Administrators can view or rotate a token for any agent:

```
GET /api/v1/agents/{agent_id}/token
POST /api/v1/agents/{agent_id}/token
```

The response for any rotation includes the new `api_token`. It is only shown
once and should be stored securely by the caller.


## Web UI session authentication

The browser-based Web UI uses a separate session-cookie auth flow. API tokens are
still required for programmatic/API clients and are **not** replaced by Web UI
login sessions.

### Configure Web UI username/password from the bot

A super-admin/admin configures Web UI credentials from Telegram:

1. Open **Admin Panel → Technical**.
2. Click **🔐 Web UI Login**.
3. Send a username (3-32 chars, starts with a letter, allowed: `a-zA-Z0-9._-`).
4. Send a password (minimum 8 chars).

The bot stores:

- `webui_username`
- `webui_password_hash`

No plaintext password is stored.

### Login endpoint and cookie behavior

- **Endpoint**: `POST /api/v1/web/login`
- **Body**: `{ "username": "...", "password": "..." }`
- **Success response**: `{ "status": "ok" }` plus a `web_session` cookie

Cookie/session defaults:

- `HttpOnly` always enabled
- `Secure` enabled automatically for production-like env (`APP_ENV`/`ENV` in
  `prod|production|staging`)
- Override with `WEB_SESSION_COOKIE_SECURE=true|false`
- Session TTL defaults to `WEB_SESSION_TTL_SECONDS=43200` (12 hours, conservative
  value in the recommended 8-24h range)

Related endpoints:

- `POST /api/v1/web/logout` clears the session cookie
- `GET /api/v1/web/me` returns the logged-in web identity
- `GET /api/v1/web/users` returns paginated users for the Web UI

### Basic login rate limit and failed-login audit logs

`POST /api/v1/web/login` applies an in-memory per-client/per-username limit:

- `WEB_LOGIN_RATE_LIMIT_MAX_ATTEMPTS` (default: `5`)
- `WEB_LOGIN_RATE_LIMIT_WINDOW_SECONDS` (default: `300`)

When credentials are invalid or rate limits are hit, warning-level audit log
entries are emitted with client id, username, and failed-attempt counters.

### Minimal users page flow

A minimal browser flow is:

1. Open Web UI login page and submit `POST /api/v1/web/login`.
2. Browser receives `web_session` cookie.
3. Web UI calls `GET /api/v1/web/me` to confirm authenticated session.
4. Web UI calls `GET /api/v1/web/users?offset=0&limit=25` to render the users
   table.
5. User clicks logout and UI calls `POST /api/v1/web/logout`.

## Role-based access

- **Admin**: full access, including managing agents and acting on behalf of any
  agent.
- **Agent**: limited to managing their own users and viewing their own data.

Endpoints annotate the required role in the generated Swagger UI.

## cURL examples

### Health check

```sh
curl "http://localhost:${FLASK_PORT}/api/v1/health"
```

### Rotate an agent token (admin only)

```sh
curl -X POST \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  "http://localhost:${FLASK_PORT}/api/v1/agents/123/token"
```

### Get current agent token

```sh
curl -H "Authorization: Bearer $AGENT_TOKEN" \
  "http://localhost:${FLASK_PORT}/api/v1/agents/me/token"
```

### Rotate my agent token

```sh
curl -X POST \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  "http://localhost:${FLASK_PORT}/api/v1/agents/me/token"
```



### Agent usage breakdown by panel (sudo admin only)

```sh
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  "http://localhost:${FLASK_PORT}/api/v1/admin/agents/123456/usage-by-panel"
```

Returns panel-level usage totals for the specified agent, computed from the
agent's assigned services and their panels.

### List users

```sh
curl -X POST \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"owner_id":123,"offset":0,"limit":25}' \
  "http://localhost:${FLASK_PORT}/api/v1/users"
```

### Create a user

```sh
curl -X POST \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","limit_bytes":1073741824,"duration_days":30}' \
  "http://localhost:${FLASK_PORT}/api/v1/users/create"
```

### Edit a user

```sh
curl -X PATCH \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"renew_days":30}' \
  "http://localhost:${FLASK_PORT}/api/v1/users/alice"
```

