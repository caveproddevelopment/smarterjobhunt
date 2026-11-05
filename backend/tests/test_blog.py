"""The JobBeggar Brief (blog): admins write posts (published immediately),
everyone reads, subscribers comment and like. Same throwaway-database setup
as test_country_billing.py (needs SJH_TEST_DATABASE_URL)."""
import io

from tests.test_country_billing import US_IP, _register, db_url, env  # noqa: F401  (fixtures)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
BODY = "This is a long enough blog post body.\n\n## A heading\n\nAnd a second paragraph here."


def _user(env, plan="pro"):
    user_id, headers = _register(env["client"], US_IP, country="US")
    env["db"].execute("UPDATE users SET plan = %s WHERE id = %s", (plan, user_id))
    env["db"].execute("SELECT email FROM users WHERE id = %s", (user_id,))
    return user_id, headers, env["db"].fetchone()[0]


def _admin(env):
    _, headers, email = _user(env, plan="free")
    env["app"].config["ADMIN_EMAILS"] = email
    return headers


def _post(env, headers, title="Who is hiring this week", body=BODY, **extra):
    extra.setdefault("author_name", "Priya Sharma")
    return env["client"].post("/api/blog/posts", json={"title": title, "body": body, **extra},
                              headers=headers)


def test_only_admins_can_write(env):
    c = env["client"]
    assert _post(env, {}).status_code == 401
    _, subscriber, _ = _user(env)
    resp = _post(env, subscriber)
    assert resp.status_code == 403 and resp.get_json()["code"] == "admin_required"
    assert c.get("/api/blog/me", headers=subscriber).get_json() == {
        "logged_in": True, "can_write": False, "can_engage": True, "comment_banned": False,
        "is_admin": False}
    admin = _admin(env)
    assert c.get("/api/blog/me", headers=admin).get_json() == {
        "logged_in": True, "can_write": True, "can_engage": True, "comment_banned": False,
        "is_admin": True}
    # the shared admin key can't author posts (a post needs an author)
    env["app"].config["ADMIN_API_KEY"] = "k"
    assert _post(env, {"X-Admin-Key": "k"}).status_code == 401


def test_admin_post_is_published_immediately_and_public(env):
    c = env["client"]
    admin = _admin(env)
    resp = _post(env, admin)
    assert resp.status_code == 201
    post = resp.get_json()
    assert post["status"] == "published" and post["published_at"]
    assert post["path"] == f"/blog/{post['id']}-who-is-hiring-this-week"
    public = c.get(f"/api/blog/posts/{post['id']}").get_json()
    assert public["body"] == BODY
    assert post["id"] in [p["id"] for p in c.get("/api/blog/posts").get_json()["posts"]]


def test_edit_and_delete_admin_only(env):
    c = env["client"]
    admin = _admin(env)
    post = _post(env, admin).get_json()
    _, subscriber, _ = _user(env)
    assert c.put(f"/api/blog/posts/{post['id']}", json={"author_name": "Priya Sharma", "title": "Hijacked title", "body": BODY},
                 headers=subscriber).status_code == 403
    assert c.delete(f"/api/blog/posts/{post['id']}", headers=subscriber).status_code == 404
    resp = c.put(f"/api/blog/posts/{post['id']}", json={"author_name": "Priya Sharma", "title": "Edited title here", "body": BODY},
                 headers=admin)
    assert resp.status_code == 200
    edited = resp.get_json()
    assert edited["status"] == "published" and edited["title"] == "Edited title here"
    assert c.get(f"/api/blog/posts/{post['id']}").status_code == 200  # still public
    assert c.delete(f"/api/blog/posts/{post['id']}", headers=admin).status_code == 200
    assert c.get(f"/api/blog/posts/{post['id']}").status_code == 404


def test_validation(env):
    admin = _admin(env)
    assert _post(env, admin, title="Hi").status_code == 400
    assert _post(env, admin, body="   ").status_code == 400  # empty post


def test_likes_toggle_and_need_subscription(env):
    c = env["client"]
    post = _post(env, _admin(env)).get_json()
    _, reader, _ = _user(env)
    url = f"/api/blog/posts/{post['id']}/like"
    assert c.post(url, headers=reader).get_json() == {"liked": True, "like_count": 1}
    assert c.get(f"/api/blog/posts/{post['id']}", headers=reader).get_json()["liked_by_me"] is True
    assert c.post(url, headers=reader).get_json() == {"liked": False, "like_count": 0}
    _, free, _ = _user(env, plan="free")
    assert c.post(url, headers=free).status_code == 403
    assert c.post(url).status_code == 401


def test_comments_public_read_subscriber_write_and_delete_rules(env):
    c = env["client"]
    admin = _admin(env)
    post = _post(env, admin).get_json()
    _, reader, _ = _user(env)
    url = f"/api/blog/posts/{post['id']}/comments"
    resp = c.post(url, json={"body": "Great post!"}, headers=reader)
    assert resp.status_code == 201
    comment = resp.get_json()
    _, free, _ = _user(env, plan="free")
    assert c.post(url, json={"body": "hi"}, headers=free).status_code == 403
    public = c.get(url).get_json()
    assert [x["body"] for x in public] == ["Great post!"] and public[0]["can_delete"] is False
    assert c.get(f"/api/blog/posts/{post['id']}").get_json()["comment_count"] == 1
    # another subscriber can't delete it; the commenter and admins can
    _, other, _ = _user(env)
    assert c.delete(f"/api/blog/comments/{comment['id']}", headers=other).status_code == 404
    assert c.delete(f"/api/blog/comments/{comment['id']}", headers=reader).status_code == 200
    second = c.post(url, json={"body": "Spam"}, headers=reader).get_json()
    assert c.delete(f"/api/blog/comments/{second['id']}", headers=admin).status_code == 200
    assert c.get(url).get_json() == []


def test_cover_image_upload_admin_only(env):
    c = env["client"]
    admin = _admin(env)
    _, subscriber, _ = _user(env)

    def upload(headers, data=PNG):
        return c.post("/api/blog/images", headers=headers, content_type="multipart/form-data",
                      data={"image": (io.BytesIO(data), "cover.png")})

    assert upload(subscriber).status_code == 403
    resp = upload(admin)
    assert resp.status_code == 201
    image = resp.get_json()
    got = c.get(image["url"])
    assert got.status_code == 200 and got.mimetype == "image/png" and got.data == PNG
    assert upload(admin, b"<script>alert(1)</script>").status_code == 400
    post = _post(env, admin, cover_image_id=image["id"]).get_json()
    assert post["cover_url"] == image["url"]


def test_admin_bans_commenter_and_can_unban(env):
    c = env["client"]
    admin = _admin(env)
    post = _post(env, admin).get_json()
    other = _post(env, admin, title="Another hiring update").get_json()
    troll_id, troll, _ = _user(env)
    _, reader, _ = _user(env)
    url = f"/api/blog/posts/{post['id']}/comments"
    bad = c.post(url, json={"body": "spam spam"}, headers=troll).get_json()
    c.post(f"/api/blog/posts/{other['id']}/comments", json={"body": "more spam"}, headers=troll)
    c.post(url, json={"body": "Nice one"}, headers=reader)
    comments = c.get(url, headers=admin).get_json()
    assert [x["can_ban"] for x in comments] == [True, True]
    assert all(x["can_ban"] is False for x in c.get(url, headers=reader).get_json())
    # non-admin can't ban
    assert c.post(f"/api/blog/admin/comments/{bad['id']}/ban", headers=reader).status_code == 403
    resp = c.post(f"/api/blog/admin/comments/{bad['id']}/ban",
                  json={"reason": "Spam", "delete_all": True}, headers=admin)
    assert resp.status_code == 200 and resp.get_json()["deleted_comments"] == 2
    assert [x["body"] for x in c.get(url).get_json()] == ["Nice one"]
    assert c.get(f"/api/blog/posts/{other['id']}/comments").get_json() == []
    # banned: can't comment, can still like
    resp = c.post(url, json={"body": "I'm back"}, headers=troll)
    assert resp.status_code == 403 and resp.get_json()["code"] == "comment_banned"
    assert c.get("/api/blog/me", headers=troll).get_json()["comment_banned"] is True
    assert c.post(f"/api/blog/posts/{post['id']}/like", headers=troll).status_code == 200
    bans = c.get("/api/blog/admin/bans", headers=admin).get_json()
    assert [(b["user_id"], b["reason"]) for b in bans] == [(troll_id, "Spam")]
    assert c.get("/api/blog/admin/bans", headers=reader).status_code == 403
    # unban
    assert c.delete(f"/api/blog/admin/bans/{troll_id}", headers=admin).status_code == 200
    assert c.post(url, json={"body": "Sorry, behaving now"}, headers=troll).status_code == 201


def test_ban_without_delete_all_removes_only_that_comment(env):
    c = env["client"]
    admin = _admin(env)
    post = _post(env, admin).get_json()
    _, troll, _ = _user(env)
    url = f"/api/blog/posts/{post['id']}/comments"
    first = c.post(url, json={"body": "ok comment"}, headers=troll).get_json()
    bad = c.post(url, json={"body": "rude comment"}, headers=troll).get_json()
    resp = c.post(f"/api/blog/admin/comments/{bad['id']}/ban", json={}, headers=admin)
    assert resp.get_json()["deleted_comments"] == 1
    assert [x["id"] for x in c.get(url).get_json()] == [first["id"]]


def test_subtitle_optional_saved_and_editable(env):
    c = env["client"]
    admin = _admin(env)
    plain = _post(env, admin).get_json()
    assert plain["subtitle"] is None
    post = _post(env, admin, title="Org Charts Before Brick and Mortar",
                 subtitle="LifeStance's Specialty Expansion Takes Shape").get_json()
    assert post["subtitle"] == "LifeStance's Specialty Expansion Takes Shape"
    assert c.get(f"/api/blog/posts/{post['id']}").get_json()["subtitle"] == post["subtitle"]
    listed = {p["id"]: p for p in c.get("/api/blog/posts").get_json()["posts"]}
    assert listed[post["id"]]["subtitle"] == post["subtitle"]
    edited = c.put(f"/api/blog/posts/{post['id']}", json={"author_name": "Priya Sharma", "title": post["title"], "subtitle": "New angle",
                   "body": BODY}, headers=admin).get_json()
    assert edited["subtitle"] == "New angle"
    cleared = c.put(f"/api/blog/posts/{post['id']}", json={"author_name": "Priya Sharma", "title": post["title"], "subtitle": "  ",
                    "body": BODY}, headers=admin).get_json()
    assert cleared["subtitle"] is None
    assert _post(env, admin, subtitle="x" * 201).status_code == 400


def test_category_label_filter_and_list(env):
    c = env["client"]
    admin = _admin(env)
    a = _post(env, admin, title="LifeStance hiring update", category="Healthcare").get_json()
    b = _post(env, admin, title="Hospital network expands", category="  healthcare ").get_json()
    f = _post(env, admin, title="Fintech roles this week", category="Fintech").get_json()
    n = _post(env, admin, title="No category post").get_json()
    assert a["category"] == "Healthcare" and b["category"] == "Healthcare"  # same spelling reused
    assert n["category"] is None
    ids = [p["id"] for p in c.get("/api/blog/posts?category=HEALTHCARE").get_json()["posts"]]
    assert set(ids) == {a["id"], b["id"]}
    cats = {x["name"]: x["count"] for x in c.get("/api/blog/categories").get_json()}
    assert cats["Healthcare"] >= 2 and cats["Fintech"] >= 1
    edited = c.put(f"/api/blog/posts/{f['id']}", json={"author_name": "Priya Sharma", "title": f["title"], "body": BODY, "category": ""},
                   headers=admin).get_json()
    assert edited["category"] is None
    assert _post(env, admin, category="x" * 41).status_code == 400


RICH = ('<p>Hiring is <strong>up</strong> this week at <a href="https://example.com" target="_blank">Acme</a>. '
        '<span style="color: #E24B34; font-size: 20px; font-family: Georgia, serif; font-weight: 800">Big</span> '
        'news for job seekers everywhere.</p><script>alert(1)</script><img src=x onerror=alert(1)>'
        '<p><a href="javascript:alert(1)">bad link</a> <span style="position: fixed">x</span></p>')


def test_rich_text_is_sanitized_and_has_plain_text(env):
    c = env["client"]
    admin = _admin(env)
    resp = c.post("/api/blog/posts", json={"author_name": "Priya Sharma", "title": "Rich text post here", "body_html": RICH}, headers=admin)
    assert resp.status_code == 201, resp.get_json()
    post = c.get(f"/api/blog/posts/{resp.get_json()['id']}").get_json()
    h = post["body_html"]
    assert "<strong>up</strong>" in h
    assert 'href="https://example.com"' in h and 'target="_blank"' in h and "noopener" in h
    assert "color:#E24B34" in h.replace(" ", "") and "font-weight:800" in h.replace(" ", "")
    for bad in ("<script", "<img", "onerror", "javascript:", "position"):
        assert bad not in h
    assert post["body"].startswith("Hiring is up this week at Acme.")
    assert "<" not in post["excerpt"]
    # short posts are fine now (no minimum); empty ones aren't
    short = c.post("/api/blog/posts", json={"author_name": "Priya Sharma", "title": "Short rich post", "body_html": "<p><b>hi</b></p>"},
                   headers=admin)
    assert short.status_code == 201
    empty = c.post("/api/blog/posts", json={"author_name": "Priya Sharma", "title": "Empty rich post", "body_html": "<p><b> </b></p>"},
                   headers=admin)
    assert empty.status_code == 400


def test_edit_keeps_date_unless_republished(env):
    c = env["client"]
    admin = _admin(env)
    post = c.post("/api/blog/posts", json={"author_name": "Priya Sharma", "title": "Republish me later", "body_html": RICH,
                                           "category": "RepubTest"}, headers=admin).get_json()
    env["db"].execute("UPDATE blog_posts SET published_at = now() - interval '30 days' WHERE id = %s",
                      (post["id"],))
    newer = _post(env, admin, title="A newer post here", category="RepubTest").get_json()
    edited = c.put(f"/api/blog/posts/{post['id']}", json={"author_name": "Priya Sharma", "title": "Republish me later", "body_html": RICH,
                   "category": "RepubTest"}, headers=admin).get_json()
    ids = [p["id"] for p in c.get("/api/blog/posts?category=RepubTest").get_json()["posts"]]
    assert ids == [newer["id"], post["id"]]  # plain edit keeps the old date
    republished = c.put(f"/api/blog/posts/{post['id']}", json={"author_name": "Priya Sharma", "title": "Republish me later", "body_html": RICH,
                        "category": "RepubTest", "republish": True}, headers=admin).get_json()
    assert republished["published_at"] > edited["published_at"]
    ids = [p["id"] for p in c.get("/api/blog/posts?category=RepubTest").get_json()["posts"]]
    assert ids == [post["id"], newer["id"]]


def test_visits_and_article_signup_stats(env):
    from routes import blog as blog_routes
    blog_routes._visit_hits.clear()
    c = env["client"]
    admin = _admin(env)
    post = _post(env, admin, title="Tracked article here").get_json()
    url = f"/api/blog/posts/{post['id']}/visit"
    for src in ("linkedin", "LinkedIn", "www.google.com", None):
        assert c.post(url, json={"source": src}).status_code == 200
    assert c.post("/api/blog/posts/999999/visit", json={"source": "x"}).status_code == 404
    # someone signs up after arriving from the article's LinkedIn share link
    from tests.test_country_billing import US_IP as ip
    import uuid
    email = f"u{uuid.uuid4().hex[:8]}@example.com"
    c.post("/api/auth/register", json={"full_name": "Link Reader", "email": email, "password": "password123",
           "utm_source": "linkedin", "utm_campaign": "the_brief", "utm_content": f"brief-{post['id']}"},
           headers={"X-Real-IP": ip})
    _, reader, _ = _user(env)
    assert c.get(f"/api/blog/admin/posts/{post['id']}/stats", headers=reader).status_code == 403
    stats = c.get(f"/api/blog/admin/posts/{post['id']}/stats", headers=admin).get_json()
    by_source = {v["source"]: v["visits"] for v in stats["visits_by_source"]}
    assert by_source == {"linkedin": 2, "google": 1, "direct": 1}
    assert stats["total_visits"] == 4 and stats["utm_content"] == f"brief-{post['id']}"
    assert stats["total_signups"] == 1 and stats["signups_by_source"][0]["source"] == "linkedin"


def test_visit_tracking_cannot_be_abused(env):
    from routes import blog as blog_routes
    blog_routes._visit_hits.clear()
    c = env["client"]
    admin = _admin(env)
    post = _post(env, admin, title="Abuse target post").get_json()
    url = f"/api/blog/posts/{post['id']}/visit"
    hostile = ["<script>alert(1)</script>", "'; DROP TABLE users;--", "a" * 900, {"$gt": 1}, ["x"], 12345,
               "evil.com/../../etc/passwd", "\x00\x01"]
    for src in hostile:
        assert c.post(url, json={"source": src}).status_code == 200
    assert c.post(url, data="not json", content_type="text/plain").status_code == 200
    assert c.post(url, json=["not", "a", "dict"]).status_code == 200
    # oversized body rejected
    assert c.post(url, json={"source": "a" * 5000}).status_code == 413
    # users table untouched, sources normalized to safe labels
    env["db"].execute("SELECT count(*) FROM users"); assert env["db"].fetchone()[0] > 0
    env["db"].execute("SELECT source FROM blog_post_visits WHERE post_id = %s", (post["id"],))
    sources = {r[0] for r in env["db"].fetchall()}
    assert all(len(s) <= 40 and "<" not in s and "'" not in s for s in sources)
    # unpublished / missing posts can't be tracked
    env["db"].execute("UPDATE blog_posts SET status = 'pending' WHERE id = %s", (post["id"],))
    assert c.post(url, json={"source": "linkedin"}).status_code == 404
    env["db"].execute("UPDATE blog_posts SET status = 'published' WHERE id = %s", (post["id"],))
    # per-IP rate limit
    blog_routes._visit_hits.clear()
    codes = [c.post(url, json={"source": "linkedin"}, headers={"X-Real-IP": "9.9.9.9"}).status_code
             for _ in range(25)]
    assert codes.count(200) == blog_routes.VISITS_PER_IP_PER_MINUTE and codes[-1] == 429
    # distinct junk sources per post per day are capped
    blog_routes._visit_hits.clear()
    for i in range(40):
        c.post(url, json={"source": f"site{i}.example.com"}, headers={"X-Real-IP": f"10.0.{i}.1"})
    env["db"].execute("SELECT count(*) FROM blog_post_visits WHERE post_id = %s AND day = CURRENT_DATE",
                      (post["id"],))
    assert env["db"].fetchone()[0] <= blog_routes.MAX_SOURCES_PER_POST_PER_DAY + 1


def test_no_length_limit_on_long_posts(env):
    c = env["client"]
    admin = _admin(env)
    para = "<p>" + ("Hiring signals from company career pages. " * 40) + "</p>"
    long_html = para * 150  # ~250,000 characters, well past the old 20,000 limit
    resp = c.post("/api/blog/posts", json={"author_name": "Priya Sharma", "title": "A very long article", "body_html": long_html},
                  headers=admin)
    assert resp.status_code == 201, resp.get_json()
    post = c.get(f"/api/blog/posts/{resp.get_json()['id']}").get_json()
    assert len(post["body"]) > 200_000 and post["body_html"].count("<p>") == 150


def test_author_name_byline(env):
    c = env["client"]
    admin = _admin(env)
    # optional, and the account name is never used in its place
    plain = c.post("/api/blog/posts", json={"title": "No byline post", "body": BODY}, headers=admin)
    assert plain.status_code == 201
    assert plain.get_json()["author"] is None and plain.get_json()["byline"] is None
    blank = _post(env, admin, title="Blank byline post", author_name="   ").get_json()
    assert blank["author"] is None
    named = _post(env, admin, title="Uses real name", author_name="  Monte   Scott Turner ").get_json()
    assert named["author"] == {"name": "Monte Scott Turner", "initials": "MS"}
    assert named["byline"] == "Monte Scott Turner"
    listed = {p["id"]: p for p in c.get("/api/blog/posts").get_json()["posts"]}
    assert listed[named["id"]]["author"]["name"] == "Monte Scott Turner"
    assert listed[plain.get_json()["id"]]["author"] is None
    cleared = c.put(f"/api/blog/posts/{named['id']}", json={"title": "Uses real name", "body": BODY,
                    "author_name": ""}, headers=admin).get_json()
    assert cleared["author"] is None
    assert _post(env, admin, author_name="x" * 81).status_code == 400
