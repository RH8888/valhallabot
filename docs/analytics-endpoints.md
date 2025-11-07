# Analytics API Endpoints

The analytics endpoints expose read-only metrics to support the dashboard
experience. They run through the existing MySQL connection pool helpers so the
queries execute safely inside the server process.

## Agent analytics

`GET /api/v1/analytics/agent/summary`

* **Guard**: `require_agent`
* **Purpose**: Returns aggregated quota usage, service-level breakdowns, usage
  trends, and recent activity for the authenticated agent.
* **Query parameters**:
  * `trend_days` – number of days of usage trend data (default 7, max 90)
  * `top_limit` – number of high-usage users to return (default 5, max 50)
  * `activity_limit` – number of recent activity rows (default 10, max 100)
* **Pagination**: Not required because the payload is summarised data.

## Administrative analytics

`GET /api/v1/analytics/admin/agents`

* **Guard**: `require_admin`
* **Purpose**: Provides a paginated view of agent usage metrics, including user
  counts and quota utilisation. The route keeps heavy joins on the backend so
  dashboards do not query the database directly.
* **Query parameters**:
  * `limit` – page size (default 25, max 100)
  * `offset` – number of rows to skip for pagination
  * `search` – optional case-insensitive match on agent name

Both endpoints rely solely on read-only `SELECT` statements via
`with_mysql_cursor`, preventing the analytics features from mutating state.
