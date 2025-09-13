# API Usage

The service exposes a [FastAPI](https://fastapi.tiangolo.com/) application. Once
running, interactive documentation is available via the automatically generated
Swagger UI:

- **Swagger UI**: `http://localhost:5000/docs`

All REST endpoints are served under the `/api/v1` prefix.

## Authentication

Every request except for the health check requires an `Authorization` header
with a bearer token:

```
Authorization: Bearer <token>
```

### Admin tokens

Set the `ADMIN_API_TOKEN` environment variable before starting the application
and use its value as the bearer token. Admin tokens allow access to privileged
endpoints.

### Agent tokens

Agent API tokens are stored hashed in the database. To issue or rotate an agent
token, an admin must call:

```
POST /api/v1/agents/{agent_id}/token
```

The response includes the new `api_token`. It is only shown once and should be
stored securely by the caller.

## Role-based access

- **Admin**: full access, including managing agents and acting on behalf of any
  agent.
- **Agent**: limited to managing their own users and viewing their own data.

Endpoints annotate the required role in the generated Swagger UI.

## cURL examples

### Health check

```sh
curl http://localhost:5000/api/v1/health
```

### Rotate an agent token (admin only)

```sh
curl -X POST \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://localhost:5000/api/v1/agents/123/token
```

### List users

```sh
curl -H "Authorization: Bearer $AGENT_TOKEN" \
  http://localhost:5000/api/v1/users
```

### Create a user

```sh
curl -X POST \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","limit_bytes":1073741824,"duration_days":30}' \
  http://localhost:5000/api/v1/users
```

### Edit a user

```sh
curl -X PATCH \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"renew_days":30}' \
  http://localhost:5000/api/v1/users/alice
```

