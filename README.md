# ⚔️ ValhallaBot

ValhallaBot is a self-hosted management stack for Marzneshin-, Marzban-, Rebecca-, Sanaei-,
and Pasarguard-style panels. It combines a Telegram bot, a FastAPI/Flask web
application, and background workers to give administrators and agents unified
control over subscriptions, usage limits, and automated provisioning.

## Key capabilities

- **Telegram operations console** – Manage panels, agents, and local users
  directly from Telegram. Admins can assign panels to agents, rotate API tokens,
  and configure services, while agents create or update their own subscribers.
- **Unified subscription aggregator** – Serves a single `/sub/<user>/<app_key>`
  endpoint that merges configurations from all linked panels, enforces both
  user- and agent-level quotas, and returns either plaintext links or a hosted
  HTML portal depending on the request headers.
- **REST API for automation** – FastAPI endpoints exposed under `/api/v1`
  provide the same capabilities as the Telegram bot for integration with other
  systems. Interactive docs are available at `/docs` once the stack is running.
- **Usage synchronisation worker** – Continuously polls linked panels to keep
  usage information in sync, apply disablement policies when quotas are
  exceeded, and push changes back to the panels.
- **Containerised deployment** – Docker/Podman images ship with Gunicorn,
  Uvicorn, the Telegram bot, and the usage synchroniser so everything runs from
  a compose file backed by either MySQL 8.0 or MongoDB 7.0.

## Architecture overview

The default deployment (created by `setup.sh`) runs the following containers:

| Service                  | Description                                                                 |
| ------------------------ | --------------------------------------------------------------------------- |
| `valhalla-app`           | FastAPI entry point that mounts the existing Flask subscription aggregator. |
| `valhalla-bot`           | Telegram bot for administrators and agents.                                 |
| `valhalla-usage`         | Background worker that synchronises usage with remote panels.               |
| `valhalla-mysql`         | MySQL 8.0 database when the MySQL backend is selected.                      |
| `valhalla-mongodb`       | MongoDB 7.0 database when the MongoDB backend is selected.                  |
| `valhalla-mongo-express` | Optional Mongo Express web console (Mongo deployments only, profile gated). |

Certificates are read from `/app/certs` when HTTPS is enabled. Persistent
database data is stored in either the `valhalla-mysql-data` or
`valhalla-mongo-data` Docker volume depending on the selected backend.

## Installation

> All commands below require root or sudo privileges.

### 1. Install Docker or Podman

Choose the container runtime that matches your environment.

#### Docker

```sh
curl -fsSL https://get.docker.com | sh
```

#### Podman (Ubuntu/Debian example)

```sh
sudo apt-get -y install podman
sudo apt install podman-compose
```

### 2. Run the setup script

The script creates `/app/.env`, downloads the `docker-compose.yml` tailored to
your database choice, pulls the
published images, and starts the stack. It will prompt for your Telegram bot
credentials, admin user IDs, database passwords, and the public base URL used to
serve subscription links. When you choose port `443` it can also request a
Let’s Encrypt certificate automatically.

```sh
sudo bash -c "$(curl -sL https://raw.githubusercontent.com/RH8888/Valhallabot/refs/heads/main/setup.sh)"
```

### 3. Verify the deployment

Depending on the runtime you selected, check the containers and follow the logs:

```sh
cd /app
# Docker example
sudo docker compose ps
sudo docker compose logs -f

# Start Mongo Express when you need the web console (MongoDB deployments only)
sudo docker compose --profile mongo-express up -d mongo-express

# Podman example
sudo podman compose ps
sudo podman compose logs -f

# Start Mongo Express when you need the web console (MongoDB deployments only)
sudo podman compose --profile mongo-express up -d mongo-express
```

The API becomes available at `http://<host>:<FLASK_PORT>/api/v1/health` once
`valhalla-app` is healthy. The Telegram bot connects automatically using the
`BOT_TOKEN` you supplied during setup.

### MongoDB deployment notes

- The repository ships `docker-compose.mongo.yml` for MongoDB deployments. Use
  `docker compose -f docker-compose.mongo.yml up -d` (or `podman compose -f ...`)
  when managing services manually without the setup script.
- Set `DATABASE_BACKEND=mongodb` when you want the application to use the bundled
  MongoDB service. If `MONGO_USER`/`MONGO_PASS` are left empty the stack falls
  back to the default `valhalla`/`changeme` credentials. Update these values in
  your `.env` file when deploying to a shared environment.
- The MongoDB port exposed to the host is controlled by `MONGODB_PORT`
  (defaults to `27017`). Open this port in your firewall if remote management or
  replica sets require it.
- Mongo Express is disabled by default. Enable it on demand using the compose
  profile shown above. Access the dashboard via
  `http://<host>:<MONGO_EXPRESS_PORT>/` and protect it with
  `MONGO_EXPRESS_USER`/`MONGO_EXPRESS_PASS`.

### Upgrades and maintenance

To fetch the latest images after an update, run the following from `/app` using
the runtime you selected during setup:

```sh
sudo docker compose pull
sudo docker compose up -d
```

For Podman replace `docker compose` with `podman compose`. The `.env` file keeps
all of your answers so rerunning the setup script is not required for upgrades.

## Configuration reference

The `.env` file generated by the setup script accepts the same keys as
[`.env.example`](./.env.example). Important entries include:

| Variable               | Purpose                                                                 |
| ---------------------- | ------------------------------------------------------------------------ |
| `BOT_TOKEN`            | Telegram bot token issued by BotFather.                                 |
| `ADMIN_IDS`            | Comma-separated Telegram user IDs with administrator access.            |
| `PUBLIC_BASE_URL`      | Public URL used when generating subscription links for users.           |
| `DATABASE_BACKEND`     | Selects the database driver (`mysql` or `mongodb`).                    |
| `MYSQL_HOST/PORT`      | Database location (defaults to the MySQL container).                    |
| `MYSQL_USER/PASSWORD`  | Application database credentials.                                       |
| `MYSQL_DATABASE`       | Database name (default `valhalla`).                                     |
| `MYSQL_ROOT_PASSWORD`  | Root password for the MySQL container.                                  |
| `MONGO_URI`            | Optional MongoDB connection string (overrides host/port credentials).   |
| `MONGO_USER/PASS`      | Credentials used when building a MongoDB URI if `MONGO_URI` is unset.   |
| `MONGO_DATABASE`       | Optional database name appended when building the fallback URI.         |
| `MONGODB_HOST/PORT`    | MongoDB location used when constructing the fallback URI or the exposed port of the bundled container. |
| `MONGO_EXPRESS_PORT`   | Host port published for the optional Mongo Express dashboard.            |
| `MONGO_EXPRESS_USER/PASS` | Basic auth credentials applied to the Mongo Express dashboard.          |
| `AGENT_TOKEN_ENCRYPTION_KEY` | Base64-encoded 32-byte Fernet key used to encrypt agent and admin API tokens. |
| `FLASK_HOST/FLASK_PORT`| Bind address and port for the FastAPI/Flask application.                |
| `WORKERS`              | Number of Gunicorn worker processes that serve the API.                 |
| `USAGE_SYNC_INTERVAL`  | Interval (seconds) between usage polls performed by the worker.         |
| `FETCH_MAX_WORKERS`    | Maximum parallel requests when fetching subscriptions.                  |

Additional knobs such as `SSL_CERT_PATH`, `SSL_KEY_PATH`, or `USER_LIMIT_REACHED_MESSAGE`
can be added manually to customise behaviour.

## Using ValhallaBot

- **Telegram bot** – Message your bot to open the inline menus. Admins can add
  panels (Marzneshin, Marzban, Rebecca, Sanaei, Pasarguard), create agents, assign services, rotate
  API tokens, and remove panels. Agents can provision local users, change
  quotas, renew subscriptions, and retrieve their unified subscription links.
- **Subscription portal** – Each user receives a link of the form
  `https://<PUBLIC_BASE_URL>/sub/<username>/<app_key>/links`. Requests with
  `Accept: text/plain` return a plain list of configs. Requests from browsers
  (or with `Accept: text/html`) render the responsive Persian-language portal in
  `templates/index.html`.
- **REST API** – Authenticate using a bearer token retrieved from the bot or
  database. Interactive documentation is available at `/docs` and the health
  check lives at `/api/v1/health`. Examples of common endpoints are documented
  in [`docs/api.md`](./docs/api.md).
- **Usage synchronisation** – The `scripts.usage_sync` worker tallies usage from
  every linked panel and updates local quotas. When a user or agent exceeds
  their allowance, the worker and aggregator coordinate to disable remote
  accounts automatically.

### API token storage

- **Hashed + encrypted** – Agent and admin API tokens are stored as a SHA-256
  hash for lookups plus an encrypted payload (using the
  `AGENT_TOKEN_ENCRYPTION_KEY`) so the raw value can still be shown once via the
  bot or REST API.
- **Legacy migration** – Existing installations that stored plaintext admin
  tokens should run `python -m scripts.migrate_admin_tokens` (with
  `PYTHONPATH=.` or from within the project virtualenv) after deploying this
  release. The script hashes and encrypts any remaining plaintext entries while
  preserving the original value.
- **Environment requirement** – Ensure `AGENT_TOKEN_ENCRYPTION_KEY` is defined
  before rotating or viewing tokens; without it the bot and API will refuse to
  decrypt stored values.

## Additional documentation

- [`docs/deployment.md`](./docs/deployment.md) – Manual deployment notes,
  including HTTPS configuration and tuning the MySQL connection pool.
- [`docs/api.md`](./docs/api.md) – REST API authentication and example requests.

## Contributing

Issues and pull requests are welcome. Please ensure linting passes, include
clear descriptions of the change, and keep new features behind configuration
flags when possible.
