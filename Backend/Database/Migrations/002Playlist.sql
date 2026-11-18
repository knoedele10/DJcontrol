-- 歌单成员只保存核验结果；歌曲改名后旧结果失效，删除歌曲时级联清理。
CREATE TABLE playlist_tracks (
    playlist TEXT NOT NULL,
    song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    in_playlist INTEGER CHECK (in_playlist IS NULL OR in_playlist IN (0, 1)),
    checked_at TEXT NOT NULL,
    PRIMARY KEY (playlist, song_id)
);
