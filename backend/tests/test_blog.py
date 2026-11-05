"""Blog: public reading, subscriber-only writing, admin approval, comments,
likes and cover images. Same throwaway-database setup as
test_country_billing.py (needs SJH_TEST_DATABASE_URL)."""
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
    user_id, headers, email = _user(env, plan="free")
    env["app"].config["ADMIN_EMAILS"] = email
    return headers


def _post(env, headers, title="My first post", body=BODY, **extra):
    return env["client"].post("/api/blog/posts", json={"title": title, "body": body, **extra},
                              headers=headers)


def _publish(env, headers):
    post = _post(env, headers).get_json()
    admin = _admin(env)
    resp = env["client"].post(f"/api/blog/admin/posts/{post['id']}/approve", headers=admin)
    assert resp.status_code == 200
    return post, admin


def test_only_subscribers_can_post(env):
    c = env["client"]
    assert _post(env, {}).status_code == 401
    _, free_headers, _ = _user(env, plan="free")
    resp = _post(env, free_headers)
    assert resp.status_code == 403 and resp.get_json()["code"] == "subscription_required"
    _, headers, _ = _user(env)
    resp = _post(env, headers)
    assert resp.status_code == 201
    post = resp.get_json()
    assert post["status"] == "pending" and post["path"] == f"/blog/{post['id']}-my-first-post"
    assert c.get("/api/blog/me", headers=headers).get_json() == {
        "logged_in": True, "can_write": True, "is_admin": False}


def test_pending_posts_are_hidden_until_approved(env):
    c = env["client"]
    _, headers, _ = _user(env)
    post = _post(env, headers, title="Hidden until approved").get_json()
    # public can't see it, author can
    assert c.get(f"/api/blog/posts/{post['id']}").status_code == 404
    assert all(p["id"] != post["id"] for p in c.get("/api/blog/posts").get_json()["posts"])
    assert c.get(f"/api/blog/posts/{post['id']}", headers=headers).status_code == 200
    mine = c.get("/api/blog/posts?mine=1", headers=headers).get_json()["posts"]
    assert [p["status"] for p in mine if p["id"] == post["id"]] == ["pending"]
    # non-admins can't approve
    assert c.post(f"/api/blog/admin/posts/{post['id']}/approve", headers=headers).status_code == 403
    admin = _admin(env)
    pending = c.get("/api/blog/admin/posts", headers=admin).get_json()
    assert post["id"] in [p["id"] for p in pending]
    assert c.post(f"/api/blog/admin/posts/{post['id']}/approve", headers=admin).status_code == 200
    public = c.get(f"/api/blog/posts/{post['id']}").get_json()
    assert public["status"] == "published" and public["body"] == BODY and public["published_at"]
    assert post["id"] in [p["id"] for p in c.get("/api/blog/posts").get_json()["posts"]]


def test_reject_with_reason_visible_to_author_only(env):
    c = env["client"]
    _, headers, _ = _user(env)
    post = _post(env, headers).get_json()
    admin = _admin(env)
    c.post(f"/api/blog/admin/posts/{post['id']}/reject", json={"reason": "Too short"}, headers=admin)
    mine = c.get(f"/api/blog/posts/{post['id']}", headers=headers).get_json()
    assert mine["status"] == "rejected" and mine["reject_reason"] == "Too short"
    assert c.get(f"/api/blog/posts/{post['id']}").status_code == 404


def test_edit_sends_post_back_to_review(env):
    c = env["client"]
    _, headers, _ = _user(env)
    post, _ = _publish(env, headers)
    resp = c.put(f"/api/blog/posts/{post['id']}", json={"title": "Edited title", "body": BODY},
                 headers=headers)
    assert resp.status_code == 200 and resp.get_json()["status"] == "pending"
    assert c.get(f"/api/blog/posts/{post['id']}").status_code == 404
    # someone else can't edit or delete it
    _, other, _ = _user(env)
    assert c.put(f"/api/blog/posts/{post['id']}", json={"title": "Hijack", "body": BODY},
                 headers=other).status_code == 404
    assert c.delete(f"/api/blog/posts/{post['id']}", headers=other).status_code == 404
    assert c.delete(f"/api/blog/posts/{post['id']}", headers=headers).status_code == 200
    assert c.get(f"/api/blog/posts/{post['id']}", headers=headers).status_code == 404


def test_validation_and_pending_limit(env):
    _, headers, _ = _user(env)
    assert _post(env, headers, title="Hi").status_code == 400
    assert _post(env, headers, body="too short").status_code == 400
    for i in range(5):
        assert _post(env, headers, title=f"Post number {i}").status_code == 201
    assert _post(env, headers, title="One too many").status_code == 429


def test_likes_toggle_and_need_subscription(env):
    c = env["client"]
    _, author, _ = _user(env)
    post, _ = _publish(env, author)
    _, reader, _ = _user(env)
    url = f"/api/blog/posts/{post['id']}/like"
    assert c.post(url, headers=reader).get_json() == {"liked": True, "like_count": 1}
    assert c.get(f"/api/blog/posts/{post['id']}", headers=reader).get_json()["liked_by_me"] is True
    assert c.post(url, headers=reader).get_json() == {"liked": False, "like_count": 0}
    _, free, _ = _user(env, plan="free")
    assert c.post(url, headers=free).status_code == 403


def test_comments_public_read_subscriber_write_and_delete_rules(env):
    c = env["client"]
    _, author, _ = _user(env)
    post, admin = _publish(env, author)
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
    assert c.delete(f"/api/blog/comments/{comment['id']}", headers=author).status_code == 404
    assert c.delete(f"/api/blog/comments/{comment['id']}", headers=reader).status_code == 200
    second = c.post(url, json={"body": "Spam"}, headers=reader).get_json()
    assert c.delete(f"/api/blog/comments/{second['id']}", headers=admin).status_code == 200
    assert c.get(url).get_json() == []


def test_cover_image_upload_and_ownership(env):
    c = env["client"]
    _, headers, _ = _user(env)
    resp = c.post("/api/blog/images", headers=headers, content_type="multipart/form-data",
                  data={"image": (io.BytesIO(PNG), "cover.png")})
    assert resp.status_code == 201
    image = resp.get_json()
    got = c.get(image["url"])
    assert got.status_code == 200 and got.mimetype == "image/png" and got.data == PNG
    # not an image
    bad = c.post("/api/blog/images", headers=headers, content_type="multipart/form-data",
                 data={"image": (io.BytesIO(b"<script>alert(1)</script>"), "x.png")})
    assert bad.status_code == 400
    # own cover works, someone else's doesn't
    post = _post(env, headers, cover_image_id=image["id"]).get_json()
    assert post["cover_url"] == image["url"]
    _, other, _ = _user(env)
    assert _post(env, other, cover_image_id=image["id"]).status_code == 400


def test_admin_key_header_works_without_login(env):
    c = env["client"]
    env["app"].config["ADMIN_API_KEY"] = "secret-key"
    _, headers, _ = _user(env)
    post = _post(env, headers, title="Approve via key").get_json()
    assert c.post(f"/api/blog/admin/posts/{post['id']}/approve",
                  headers={"X-Admin-Key": "wrong"}).status_code == 403
    assert c.post(f"/api/blog/admin/posts/{post['id']}/approve",
                  headers={"X-Admin-Key": "secret-key"}).status_code == 200
