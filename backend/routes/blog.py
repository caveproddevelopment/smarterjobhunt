"""Blog: anyone can read published posts; subscribers (plan == 'pro') can
write posts, comment and like; every new or edited post waits for an admin
to approve it before it's public.

Admins are the accounts whose email is listed in ADMIN_EMAILS (config.py),
or any request carrying the shared X-Admin-Key (same key as routes/staging.py).

Posts are plain text: blank lines separate paragraphs and a line starting
with "## " is a heading. The frontend renders them as text nodes, so there's
no HTML to sanitize.
"""
import re
import secrets
import uuid

from flask import Blueprint, Response, current_app, g, jsonify, request

from auth_utils import optional_auth, require_auth
from db.connection import get_cursor
from email_utils import send_contact_email

bp = Blueprint("blog", __name__, url_prefix="/api/blog")

PAGE_SIZE = 12
TITLE_MIN, TITLE_MAX = 5, 150
BODY_MIN, BODY_MAX = 50, 20000
COMMENT_MAX = 2000
MAX_PENDING_PER_USER = 5
IMAGE_MAX_BYTES = 3 * 1024 * 1024
EXCERPT_CHARS = 220

# Magic-byte sniffing -- never trust the browser's Content-Type.
_IMAGE_SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def _sniff_image(data):
    for sig, ctype in _IMAGE_SIGNATURES:
        if data.startswith(sig):
            return ctype
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _clean_text(value, keep_newlines=False):
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    allowed = {"\n", "\t"} if keep_newlines else set()
    text = "".join(ch for ch in text if ch.isprintable() or ch in allowed)
    if keep_newlines:
        text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _slugify(title):
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80].strip("-")
    return slug or "post"


def _excerpt(body):
    text = " ".join(line[3:] if line.startswith("## ") else line for line in body.split("\n"))
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= EXCERPT_CHARS else text[:EXCERPT_CHARS].rsplit(" ", 1)[0] + "..."


def _initials(name):
    parts = (name or "").split()
    return "".join(p[0] for p in parts[:2]).upper() or "?"


# --- who is asking ---------------------------------------------------------

def _admin_emails():
    raw = current_app.config.get("ADMIN_EMAILS") or ""
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def _has_admin_key():
    expected = current_app.config.get("ADMIN_API_KEY")
    provided = request.headers.get("X-Admin-Key", "")
    return bool(expected and provided and secrets.compare_digest(provided, expected))


def _viewer():
    """The logged-in user (id, plan, email, is_admin, can_write) or None."""
    if getattr(g, "_blog_viewer", "unset") != "unset":
        return g._blog_viewer
    viewer = None
    if g.get("user_id"):
        cur = get_cursor()
        cur.execute("SELECT id, email, plan, full_name FROM users WHERE id = %s", (g.user_id,))
        row = cur.fetchone()
        if row:
            viewer = dict(row)
            viewer["is_admin"] = row["email"].lower() in _admin_emails()
            viewer["can_write"] = row["plan"] == "pro"
    g._blog_viewer = viewer
    return viewer


def _is_admin():
    v = _viewer()
    return bool(v and v["is_admin"]) or _has_admin_key()


def _subscriber_or_error():
    v = _viewer()
    if v is None:
        return None, (jsonify({"error": "Log in to continue.", "code": "login_required"}), 401)
    if not v["can_write"]:
        return None, (
            jsonify({"error": "Only subscribers can do this. Subscribe to join in.",
                     "code": "subscription_required"}),
            403,
        )
    return v, None


# --- serialization -----------------------------------------------------------

_POST_SELECT = """
    SELECT p.id, p.author_id, p.title, p.slug, p.body, p.cover_image_id, p.status,
           p.reject_reason, p.created_at, p.updated_at, p.published_at,
           u.full_name AS author_name,
           (SELECT count(*) FROM blog_likes l WHERE l.post_id = p.id) AS like_count,
           (SELECT count(*) FROM blog_comments c WHERE c.post_id = p.id) AS comment_count,
           EXISTS (SELECT 1 FROM blog_likes l WHERE l.post_id = p.id AND l.user_id = %(viewer_id)s)
               AS liked_by_me
    FROM blog_posts p JOIN users u ON u.id = p.author_id
"""


def _post_json(row, full=False):
    viewer = _viewer()
    out = {
        "id": row["id"],
        "slug": row["slug"],
        "path": f"/blog/{row['id']}-{row['slug']}",
        "title": row["title"],
        "excerpt": _excerpt(row["body"]),
        "cover_url": (f"/api/blog/images/{row['cover_image_id']}" if row["cover_image_id"] else None),
        "cover_image_id": str(row["cover_image_id"]) if row["cover_image_id"] else None,
        "status": row["status"],
        "author": {"name": row["author_name"], "initials": _initials(row["author_name"])},
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        "published_at": row["published_at"].isoformat() if row["published_at"] else None,
        "like_count": row["like_count"],
        "comment_count": row["comment_count"],
        "liked_by_me": bool(row["liked_by_me"]),
        "is_mine": bool(viewer and viewer["id"] == row["author_id"]),
    }
    if out["is_mine"] or _is_admin():
        out["reject_reason"] = row["reject_reason"]
    if full:
        out["body"] = row["body"]
    return out


def _fetch_post(post_id):
    cur = get_cursor()
    viewer = _viewer()
    cur.execute(_POST_SELECT + " WHERE p.id = %(id)s",
                {"viewer_id": viewer["id"] if viewer else None, "id": post_id})
    return cur.fetchone()


def _can_see(row):
    if row is None:
        return False
    if row["status"] == "published":
        return True
    viewer = _viewer()
    return bool(viewer and viewer["id"] == row["author_id"]) or _is_admin()


def _validate_post(body):
    title = _clean_text(body.get("title"))
    text = _clean_text(body.get("body"), keep_newlines=True)
    if not TITLE_MIN <= len(title) <= TITLE_MAX:
        return None, f"Title must be {TITLE_MIN}-{TITLE_MAX} characters."
    if not BODY_MIN <= len(text) <= BODY_MAX:
        return None, f"Post must be {BODY_MIN}-{BODY_MAX} characters."
    cover = body.get("cover_image_id") or None
    if cover is not None:
        try:
            cover = str(uuid.UUID(str(cover)))
        except ValueError:
            return None, "Invalid cover image."
    return {"title": title, "body": text, "cover_image_id": cover}, None


def _check_cover_owner(cover_id, user_id, current_cover=None):
    """A post may only use a cover the author uploaded (or the one it already has)."""
    if cover_id is None or cover_id == current_cover:
        return True
    cur = get_cursor()
    cur.execute("SELECT owner_id FROM blog_images WHERE id = %s", (cover_id,))
    row = cur.fetchone()
    return bool(row and row["owner_id"] == user_id)


def _notify_admin_of_pending(post_id, title, author_name):
    try:
        link = f"{current_app.config['FRONTEND_ORIGIN']}/blog/admin"
        send_contact_email(
            "JobBeggar Blog",
            "noreply@jobbeggar.com",
            f"Blog post waiting for approval: {title}",
            f"{author_name} submitted a blog post (#{post_id}) that needs review.\n\nReview it here: {link}",
        )
    except Exception:  # noqa: BLE001 -- a notification must never break posting
        current_app.logger.exception("Couldn't send blog approval notification")


# --- reading -----------------------------------------------------------------

@bp.get("/me")
@optional_auth
def blog_me():
    v = _viewer()
    return jsonify({
        "logged_in": v is not None,
        "can_write": bool(v and v["can_write"]),
        "is_admin": _is_admin(),
    })


@bp.get("/posts")
@optional_auth
def list_posts():
    """Published posts, newest first. ?mine=1 lists the caller's own posts in
    every status (so authors can see pending/rejected ones)."""
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    viewer = _viewer()
    params = {"viewer_id": viewer["id"] if viewer else None,
              "limit": PAGE_SIZE + 1, "offset": (page - 1) * PAGE_SIZE}
    if request.args.get("mine"):
        if viewer is None:
            return jsonify({"error": "Log in to see your posts.", "code": "login_required"}), 401
        where, order = "p.author_id = %(viewer_id)s", "p.updated_at DESC"
    else:
        where, order = "p.status = 'published'", "p.published_at DESC"
    cur = get_cursor()
    cur.execute(_POST_SELECT + f" WHERE {where} ORDER BY {order}, p.id DESC"
                " LIMIT %(limit)s OFFSET %(offset)s", params)
    rows = cur.fetchall()
    return jsonify({
        "posts": [_post_json(r) for r in rows[:PAGE_SIZE]],
        "page": page,
        "has_more": len(rows) > PAGE_SIZE,
    })


@bp.get("/posts/<int:post_id>")
@optional_auth
def get_post(post_id):
    row = _fetch_post(post_id)
    if not _can_see(row):
        return jsonify({"error": "Post not found"}), 404
    return jsonify(_post_json(row, full=True))


@bp.get("/posts/<int:post_id>/comments")
@optional_auth
def list_comments(post_id):
    row = _fetch_post(post_id)
    if not _can_see(row):
        return jsonify({"error": "Post not found"}), 404
    viewer = _viewer()
    admin = _is_admin()
    cur = get_cursor()
    cur.execute(
        """
        SELECT c.id, c.author_id, c.body, c.created_at, u.full_name AS author_name
        FROM blog_comments c JOIN users u ON u.id = c.author_id
        WHERE c.post_id = %s ORDER BY c.created_at, c.id
        """,
        (post_id,),
    )
    return jsonify([
        {
            "id": c["id"],
            "body": c["body"],
            "created_at": c["created_at"].isoformat(),
            "author": {"name": c["author_name"], "initials": _initials(c["author_name"])},
            "can_delete": admin or bool(viewer and viewer["id"] == c["author_id"]),
        }
        for c in cur.fetchall()
    ])


@bp.get("/images/<image_id>")
def get_image(image_id):
    try:
        image_id = str(uuid.UUID(image_id))
    except ValueError:
        return jsonify({"error": "Not found"}), 404
    cur = get_cursor()
    cur.execute("SELECT content_type, data FROM blog_images WHERE id = %s", (image_id,))
    row = cur.fetchone()
    if row is None:
        return jsonify({"error": "Not found"}), 404
    resp = Response(bytes(row["data"]), mimetype=row["content_type"])
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


# --- writing (subscribers) ---------------------------------------------------

@bp.post("/images")
@require_auth
def upload_image():
    viewer, err = _subscriber_or_error()
    if err:
        return err
    file = request.files.get("image")
    if file is None:
        return jsonify({"error": "No image uploaded."}), 400
    data = file.read(IMAGE_MAX_BYTES + 1)
    if len(data) > IMAGE_MAX_BYTES:
        return jsonify({"error": "Image must be 3 MB or smaller."}), 400
    ctype = _sniff_image(data)
    if ctype is None:
        return jsonify({"error": "Use a JPG, PNG, WebP or GIF image."}), 400
    image_id = str(uuid.uuid4())
    cur = get_cursor()
    cur.execute(
        "INSERT INTO blog_images (id, owner_id, content_type, data) VALUES (%s, %s, %s, %s)",
        (image_id, viewer["id"], ctype, data),
    )
    cur.connection.commit()
    return jsonify({"id": image_id, "url": f"/api/blog/images/{image_id}"}), 201


@bp.post("/posts")
@require_auth
def create_post():
    viewer, err = _subscriber_or_error()
    if err:
        return err
    data, problem = _validate_post(request.get_json(silent=True) or {})
    if problem:
        return jsonify({"error": problem}), 400
    if not _check_cover_owner(data["cover_image_id"], viewer["id"]):
        return jsonify({"error": "Invalid cover image."}), 400
    cur = get_cursor()
    cur.execute("SELECT count(*) AS n FROM blog_posts WHERE author_id = %s AND status = 'pending'",
                (viewer["id"],))
    if cur.fetchone()["n"] >= MAX_PENDING_PER_USER:
        return jsonify({"error": f"You already have {MAX_PENDING_PER_USER} posts waiting for review. "
                                 "Please wait until they're approved."}), 429
    cur.execute(
        """
        INSERT INTO blog_posts (author_id, title, slug, body, cover_image_id)
        VALUES (%s, %s, %s, %s, %s) RETURNING id
        """,
        (viewer["id"], data["title"], _slugify(data["title"]), data["body"], data["cover_image_id"]),
    )
    post_id = cur.fetchone()["id"]
    cur.connection.commit()
    _notify_admin_of_pending(post_id, data["title"], viewer["full_name"])
    return jsonify(_post_json(_fetch_post(post_id), full=True)), 201


@bp.put("/posts/<int:post_id>")
@require_auth
def update_post(post_id):
    viewer, err = _subscriber_or_error()
    if err:
        return err
    row = _fetch_post(post_id)
    if row is None or row["author_id"] != viewer["id"]:
        return jsonify({"error": "Post not found"}), 404
    data, problem = _validate_post(request.get_json(silent=True) or {})
    if problem:
        return jsonify({"error": problem}), 400
    current_cover = str(row["cover_image_id"]) if row["cover_image_id"] else None
    if not _check_cover_owner(data["cover_image_id"], viewer["id"], current_cover):
        return jsonify({"error": "Invalid cover image."}), 400
    cur = get_cursor()
    # Any edit goes back through review, so an approved post can't be
    # swapped for something else afterwards.
    cur.execute(
        """
        UPDATE blog_posts
        SET title = %s, slug = %s, body = %s, cover_image_id = %s,
            status = 'pending', reject_reason = NULL, updated_at = now()
        WHERE id = %s
        """,
        (data["title"], _slugify(data["title"]), data["body"], data["cover_image_id"], post_id),
    )
    cur.connection.commit()
    _notify_admin_of_pending(post_id, data["title"], viewer["full_name"])
    return jsonify(_post_json(_fetch_post(post_id), full=True))


@bp.delete("/posts/<int:post_id>")
@optional_auth
def delete_post(post_id):
    row = _fetch_post(post_id)
    viewer = _viewer()
    is_author = bool(row and viewer and viewer["id"] == row["author_id"])
    if row is None or not (is_author or _is_admin()):
        return jsonify({"error": "Post not found"}), 404
    cur = get_cursor()
    cur.execute("DELETE FROM blog_posts WHERE id = %s", (post_id,))
    cur.connection.commit()
    return jsonify({"deleted": True})


@bp.post("/posts/<int:post_id>/like")
@require_auth
def toggle_like(post_id):
    viewer, err = _subscriber_or_error()
    if err:
        return err
    row = _fetch_post(post_id)
    if row is None or row["status"] != "published":
        return jsonify({"error": "Post not found"}), 404
    cur = get_cursor()
    cur.execute("DELETE FROM blog_likes WHERE post_id = %s AND user_id = %s RETURNING 1",
                (post_id, viewer["id"]))
    liked = False
    if cur.fetchone() is None:
        cur.execute("INSERT INTO blog_likes (post_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (post_id, viewer["id"]))
        liked = True
    cur.execute("SELECT count(*) AS n FROM blog_likes WHERE post_id = %s", (post_id,))
    count = cur.fetchone()["n"]
    cur.connection.commit()
    return jsonify({"liked": liked, "like_count": count})


@bp.post("/posts/<int:post_id>/comments")
@require_auth
def add_comment(post_id):
    viewer, err = _subscriber_or_error()
    if err:
        return err
    row = _fetch_post(post_id)
    if row is None or row["status"] != "published":
        return jsonify({"error": "Post not found"}), 404
    text = _clean_text((request.get_json(silent=True) or {}).get("body"), keep_newlines=True)
    if not 1 <= len(text) <= COMMENT_MAX:
        return jsonify({"error": f"Comment must be 1-{COMMENT_MAX} characters."}), 400
    cur = get_cursor()
    cur.execute(
        "INSERT INTO blog_comments (post_id, author_id, body) VALUES (%s, %s, %s) RETURNING id, created_at",
        (post_id, viewer["id"], text),
    )
    c = cur.fetchone()
    cur.connection.commit()
    return jsonify({
        "id": c["id"],
        "body": text,
        "created_at": c["created_at"].isoformat(),
        "author": {"name": viewer["full_name"], "initials": _initials(viewer["full_name"])},
        "can_delete": True,
    }), 201


@bp.delete("/comments/<int:comment_id>")
@optional_auth
def delete_comment(comment_id):
    viewer = _viewer()
    cur = get_cursor()
    cur.execute("SELECT author_id FROM blog_comments WHERE id = %s", (comment_id,))
    c = cur.fetchone()
    if c is None or not ((viewer and viewer["id"] == c["author_id"]) or _is_admin()):
        return jsonify({"error": "Comment not found"}), 404
    cur.execute("DELETE FROM blog_comments WHERE id = %s", (comment_id,))
    cur.connection.commit()
    return jsonify({"deleted": True})


# --- moderation (admins) -----------------------------------------------------

def _admin_or_error():
    if not _is_admin():
        return jsonify({"error": "Admins only."}), 403
    return None


@bp.get("/admin/posts")
@optional_auth
def admin_list():
    err = _admin_or_error()
    if err:
        return err
    status = request.args.get("status", "pending")
    if status not in ("pending", "published", "rejected"):
        return jsonify({"error": "Unknown status"}), 400
    cur = get_cursor()
    cur.execute(_POST_SELECT + " WHERE p.status = %(status)s ORDER BY p.updated_at ASC LIMIT 100",
                {"viewer_id": None, "status": status})
    return jsonify([_post_json(r, full=True) for r in cur.fetchall()])


@bp.post("/admin/posts/<int:post_id>/approve")
@optional_auth
def admin_approve(post_id):
    err = _admin_or_error()
    if err:
        return err
    cur = get_cursor()
    cur.execute(
        """
        UPDATE blog_posts
        SET status = 'published', reject_reason = NULL,
            published_at = COALESCE(published_at, now())
        WHERE id = %s RETURNING id
        """,
        (post_id,),
    )
    if cur.fetchone() is None:
        return jsonify({"error": "Post not found"}), 404
    cur.connection.commit()
    return jsonify(_post_json(_fetch_post(post_id), full=True))


@bp.post("/admin/posts/<int:post_id>/reject")
@optional_auth
def admin_reject(post_id):
    err = _admin_or_error()
    if err:
        return err
    reason = _clean_text((request.get_json(silent=True) or {}).get("reason"))[:500] or None
    cur = get_cursor()
    cur.execute(
        "UPDATE blog_posts SET status = 'rejected', reject_reason = %s WHERE id = %s RETURNING id",
        (reason, post_id),
    )
    if cur.fetchone() is None:
        return jsonify({"error": "Post not found"}), 404
    cur.connection.commit()
    return jsonify(_post_json(_fetch_post(post_id), full=True))
