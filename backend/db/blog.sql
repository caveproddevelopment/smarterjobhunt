-- Blog: subscribers write posts, an admin approves them, everyone can read.
-- Run automatically at app start (app.py _ensure_blog_tables), and also
-- included at the end of schema.sql. Every statement is idempotent.

-- Cover images live in Postgres (Railway has no persistent disk). Ids are
-- random UUIDs so an uploaded-but-unpublished image isn't guessable.
CREATE TABLE IF NOT EXISTS blog_images (
    id            UUID PRIMARY KEY,
    owner_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content_type  TEXT NOT NULL,
    data          BYTEA NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- status: 'pending' (waiting for an admin), 'published', 'rejected'.
-- Editing a published post sends it back to 'pending' so nothing goes live
-- without review.
CREATE TABLE IF NOT EXISTS blog_posts (
    id              SERIAL PRIMARY KEY,
    author_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    slug            TEXT NOT NULL,
    body            TEXT NOT NULL,
    cover_image_id  UUID REFERENCES blog_images(id) ON DELETE SET NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'published', 'rejected')),
    reject_reason   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS blog_posts_status_published_idx ON blog_posts (status, published_at DESC);
CREATE INDEX IF NOT EXISTS blog_posts_author_idx ON blog_posts (author_id);

CREATE TABLE IF NOT EXISTS blog_comments (
    id          SERIAL PRIMARY KEY,
    post_id     INTEGER NOT NULL REFERENCES blog_posts(id) ON DELETE CASCADE,
    author_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS blog_comments_post_idx ON blog_comments (post_id, created_at);

CREATE TABLE IF NOT EXISTS blog_likes (
    post_id     INTEGER NOT NULL REFERENCES blog_posts(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (post_id, user_id)
);
