# Plan: Encrypt panel admin passwords (stop storing them in plaintext)

## Context

In this codebase the Telegram bot / REST API stores the **panel admin password**
(`panels.admin_password_encrypted`) needed to refresh expiring panel access
tokens. Although the column is named `admin_password_encrypted`, the two
functions that are supposed to encrypt/decrypt it are **disabled stubs** that
pass the value through unchanged:

- `services/panel_tokens.py:209` `encrypt_panel_password` → `return password`
- `services/panel_tokens.py:215` `decrypt_panel_password` → `return ciphertext`

So every panel admin password is currently written to and read from the MySQL
`panels` table in **plaintext** (`bot.py:3813`, `bot.py:3970`,
`api/admin.py:113`, `api/admin.py:167`). Anyone with DB access can read panel
credentials directly.

The project already has a working Fernet implementation in
`models/token_crypto.py` (`encrypt_token` / `decrypt_token`) backed by the
`AGENT_TOKEN_ENCRYPTION_KEY` env var (with `AGENT_TOKEN_ENCRYPTION_OLD_KEYS`
decrypt fallback for key rotation). API tokens already use it. This plan wires
the panel password functions through that same mechanism and migrates existing
plaintext rows.

### Scope (confirmed with user)
Panel admin password only. Web UI admin/agent passwords
(`webui_admin_password_hash`, `webui_agent_password_hash`) are already stored
as Werkzeug hashes and are **out of scope**.

## Why this is safe
- All **writers** already call `encrypt_panel_password(...)` before INSERT/UPDATE.
- All **readers** route the row through `ensure_panel_tokens` →
  `ensure_panel_access_token`, which calls `decrypt_panel_password(...)` on
  `admin_password_encrypted` (`bot.py`, `api/subscription_aggregator/flask_app.py`,
  `scripts/usage_sync.py` all use `ensure_panel_tokens`).
- Sanaei bearer-auth panels store `admin_password_encrypted = NULL` and are
  skipped (`ensure_panel_access_token` returns early when `encrypted` is falsy),
  so they are unaffected.
- `token_crypto` auto-generates and persists `AGENT_TOKEN_ENCRYPTION_KEY` if
  missing, matching existing API-token behavior.

## Implementation steps

### 1. Enable encryption in `services/panel_tokens.py`
- Add import:
  `from models.token_crypto import decrypt_token, encrypt_token`
  (the module already imports `TokenEncryptionError` from there on line 16).
- Replace the stubs:
  ```python
  def encrypt_panel_password(password: str) -> str:
      """Encrypt a panel admin password with the configured Fernet key."""
      return encrypt_token(password)

  def decrypt_panel_password(ciphertext: str) -> str:
      """Decrypt a stored panel admin password with the configured Fernet key."""
      return decrypt_token(ciphertext)
  ```
- These already propagate `TokenEncryptionError`, which callers already catch
  (`bot.py:3814`/`3971` and `api/admin.py:114`/`168` as
  `PanelTokenEncryptionError`, plus `ensure_panel_access_token` at line 328).
  No caller changes needed.

### 2. Add a one-time migration script `scripts/migrate_panel_passwords.py`
Run as `python -m scripts.migrate_panel_passwords` (`PYTHONPATH=.`).
- `init_mysql_pool()` then `SELECT id, admin_password_encrypted FROM panels
  WHERE admin_password_encrypted IS NOT NULL AND admin_password_encrypted != ''`.
- For each row:
  - Try `decrypt_panel_password(value)`. On **success** → already encrypted, skip.
  - On `TokenEncryptionError` → value is legacy plaintext →
    `encrypt_panel_password(value)` then `UPDATE panels SET
    admin_password_encrypted=%s WHERE id=%s`.
- Commit per row (or batched), log how many migrated vs skipped.
- Mirror the dry-run-friendly shape of `scripts/usage_sync.py` (same pool/cursor
  helpers). Keep it idempotent so re-running is safe.
- Add a short `if __name__ == "__main__":` entrypoint; make the file a module
  (the package already has `scripts/__init__.py`).

### 3. Documentation
- Update `README.md` "API token storage" section (lines ~150-164) to also cover
  panel admin passwords, and add the migration command under the legacy
  migration bullet. The README already references a `scripts.migrate_admin_tokens`
  script that does not exist in the repo; do **not** rely on it — use the new
  `scripts.migrate_panel_passwords`.

## Rollout / migration path
1. Deploy code with encryption enabled.
2. **Before** the bot/API first refreshes a panel token, run
   `python -m scripts.migrate_panel_passwords` so no row is still plaintext.
   (Until migrated, legacy rows will fail `decrypt_panel_password` and trigger
   the existing root-admin "decrypt error" notification rather than crashing.)
3. Verify `AGENT_TOKEN_ENCRYPTION_KEY` is set in `.env`
   (`setup.sh` already generates it). Put the previous key in
   `AGENT_TOKEN_ENCRYPTION_OLD_KEYS` during any key rotation.

## Validation
- Unit-style check (no DB needed): with a known `AGENT_TOKEN_ENCRYPTION_KEY`,
  assert `decrypt_panel_password(encrypt_panel_password("secret")) == "secret"`.
- Query `SELECT id, admin_password_encrypted FROM panels` after migration:
  values should be Fernet ciphertext (base64, `gAAAAA...`), never the raw
  password. Confirm no plaintext password substring appears in the column.
- Trigger a panel token refresh (hourly check or a manual panel edit) and confirm
  the round-trip log at `services/panel_tokens.py:360` passes and tokens refresh.
- Run the migration script twice; second run should migrate 0 rows (idempotent).
- Run `python -m pytest tests/` (repo currently has `tests/test_sanaei_modern.py`)
  to ensure nothing else broke.

## Open questions / risks
- **Missing key at migration time:** `token_crypto` auto-generates a key and
  writes it to `.env`. Confirm this is acceptable for the migration (it is the
  existing behavior for API tokens). If stricter control is wanted, bail out of
  the migration with a clear message when the key is absent instead of
  auto-generating.
- **Accidental Fernet-shaped plaintext:** exceptionally unlikely a plaintext
  password happens to be valid Fernet ciphertext; if so it would be skipped.
  Acceptable; can be hardened later with a length/prefix heuristic if needed.
