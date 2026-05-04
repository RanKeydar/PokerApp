CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'user'
    CHECK (role IN ('admin', 'magician', 'player', 'user')),
  is_approved INTEGER NOT NULL DEFAULT 1
    CHECK (is_approved IN (0, 1))
);

CREATE TABLE IF NOT EXISTS players (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS games (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  location TEXT,
  game_type TEXT NOT NULL
    CHECK (game_type IN ('cash', 'harbo'))
);

CREATE TABLE IF NOT EXISTS game_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  game_id INTEGER NOT NULL,
  player_id INTEGER NOT NULL,
  buyin REAL NOT NULL DEFAULT 0 CHECK (buyin >= 0),
  cashout REAL NOT NULL DEFAULT 0 CHECK (cashout >= 0),
  profit REAL NOT NULL DEFAULT 0,
  FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE,
  FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE,
  UNIQUE (game_id, player_id)
);

CREATE TABLE IF NOT EXISTS admin_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    actor_username TEXT NOT NULL,
    actor_role TEXT,
    action TEXT NOT NULL,
    target_type TEXT,
    target_value TEXT,
    status TEXT NOT NULL,
    message TEXT
);

CREATE INDEX IF NOT EXISTS idx_games_type_date
  ON games(game_type, date);

CREATE INDEX IF NOT EXISTS idx_results_game_id
  ON game_results(game_id);

CREATE INDEX IF NOT EXISTS idx_results_player_id
  ON game_results(player_id);

CREATE INDEX IF NOT EXISTS idx_admin_audit_log_created_at
ON admin_audit_log (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_admin_audit_log_action
ON admin_audit_log (action);