-- M1 数据层：曲库、活动组、播放队列和演出记录的基础结构。

CREATE TABLE IF NOT EXISTS songs (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    artist TEXT NOT NULL CHECK (length(trim(artist)) > 0),
    bpm INTEGER CHECK (bpm IS NULL OR (bpm >= 1 AND bpm <= 400)),
    duration INTEGER NOT NULL CHECK (duration >= 0),
    source TEXT NOT NULL CHECK (source IN ('library', 'kugou')),
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (title, artist)
);

CREATE INDEX IF NOT EXISTS idx_songs_title_artist ON songs(title, artist);

CREATE TABLE IF NOT EXISTS event_groups (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 20),
    color TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0 CHECK (sort_order >= 0),
    created_at TEXT NOT NULL,
    UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS categories (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL REFERENCES event_groups(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 20),
    color TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0 CHECK (sort_order >= 0),
    UNIQUE (group_id, name)
);

CREATE INDEX IF NOT EXISTS idx_categories_group_order ON categories(group_id, sort_order, id);

CREATE TABLE IF NOT EXISTS category_songs (
    category_id TEXT NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
    PRIMARY KEY (category_id, song_id),
    UNIQUE (category_id, position)
);

CREATE INDEX IF NOT EXISTS idx_category_songs_song ON category_songs(song_id);

CREATE TABLE IF NOT EXISTS queue_items (
    id TEXT PRIMARY KEY,
    song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position >= 0),
    added_at TEXT NOT NULL,
    UNIQUE (position)
);

CREATE INDEX IF NOT EXISTS idx_queue_items_position ON queue_items(position, id);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_open_session
    ON sessions(ended_at)
    WHERE ended_at IS NULL;

CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    song_id INTEGER REFERENCES songs(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    played_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_history_session_played_at ON history(session_id, played_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS ppt_bindings (
    app TEXT NOT NULL CHECK (app IN ('powerpoint', 'wps')),
    document_id TEXT NOT NULL,
    slide INTEGER NOT NULL CHECK (slide >= 1),
    song_id INTEGER REFERENCES songs(id) ON DELETE SET NULL,
    PRIMARY KEY (app, document_id, slide)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
