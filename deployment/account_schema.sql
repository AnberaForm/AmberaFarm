-- Install once as Postgres admin, in the dedicated AmberaFarm database.
-- Create the login role ambera_game_service separately with a generated
-- password; the password does not belong in this file.
BEGIN;
CREATE SCHEMA IF NOT EXISTS ambera_game;
REVOKE ALL ON SCHEMA ambera_game FROM PUBLIC;
CREATE TABLE IF NOT EXISTS ambera_game.accounts (
    id text PRIMARY KEY, name text NOT NULL, name_key text COLLATE "C" NOT NULL UNIQUE,
    salt text NOT NULL, password_hash text NOT NULL, created_at bigint NOT NULL
);
CREATE TABLE IF NOT EXISTS ambera_game.sessions (
    token_hash text PRIMARY KEY,
    account_id text NOT NULL REFERENCES ambera_game.accounts (id) ON DELETE CASCADE,
    expires_at bigint NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_expiry ON ambera_game.sessions (expires_at);
CREATE INDEX IF NOT EXISTS sessions_account ON ambera_game.sessions (account_id);
CREATE TABLE IF NOT EXISTS ambera_game.farm_saves (
    account_id text NOT NULL REFERENCES ambera_game.accounts (id) ON DELETE CASCADE,
    mode text NOT NULL CHECK (mode IN ('normal', 'online')),
    revision integer NOT NULL CHECK (revision > 0),
    operation text NOT NULL, data text NOT NULL,
    PRIMARY KEY (account_id, mode)
);
REVOKE ALL ON ALL TABLES IN SCHEMA ambera_game FROM PUBLIC;
GRANT USAGE ON SCHEMA ambera_game TO ambera_game_service;
GRANT SELECT, INSERT ON ambera_game.accounts TO ambera_game_service;
GRANT SELECT, INSERT, DELETE ON ambera_game.sessions TO ambera_game_service;
GRANT SELECT, INSERT, UPDATE ON ambera_game.farm_saves TO ambera_game_service;
ALTER TABLE ambera_game.accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE ambera_game.sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE ambera_game.farm_saves ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS game_service ON ambera_game.accounts;
DROP POLICY IF EXISTS game_service ON ambera_game.sessions;
DROP POLICY IF EXISTS game_service ON ambera_game.farm_saves;
CREATE POLICY game_service ON ambera_game.accounts TO ambera_game_service USING (true) WITH CHECK (true);
CREATE POLICY game_service ON ambera_game.sessions TO ambera_game_service USING (true) WITH CHECK (true);
CREATE POLICY game_service ON ambera_game.farm_saves TO ambera_game_service USING (true) WITH CHECK (true);
COMMIT;
