-- Admin panel login: individual accounts, server-side sessions, login throttling and an audit trail.
CREATE TABLE admin_users (
  id            BIGSERIAL PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,                 -- Argon2id, encoded with its own salt and parameters
  disabled      BOOLEAN NOT NULL DEFAULT false,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  password_changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Only a hash of the session id is stored; the cookie holds the random id itself.
CREATE TABLE admin_sessions (
  id_hash    TEXT PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
  csrf_token TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen  TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,              -- absolute lifetime
  ip         TEXT,
  user_agent TEXT
);
CREATE INDEX admin_sessions_user_idx ON admin_sessions (user_id);

-- Failed logins, keyed by account name and by client address (both are throttled).
CREATE TABLE admin_login_failures (
  id   BIGSERIAL PRIMARY KEY,
  key  TEXT NOT NULL,
  at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX admin_login_failures_key_idx ON admin_login_failures (key, at);

CREATE TABLE admin_audit (
  id      BIGSERIAL PRIMARY KEY,
  actor   TEXT NOT NULL,                        -- username, or 'token' for the machine token
  action  TEXT NOT NULL,
  detail  JSONB,
  ip      TEXT,
  at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
