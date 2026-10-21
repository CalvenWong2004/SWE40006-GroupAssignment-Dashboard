import jwt

from config import settings
from tests.conftest import login


# ---------- auth ----------
def test_login_success_returns_token_and_role(client):
    response = login(client, "Calven")
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "admin"
    assert body["access_token"]


def test_login_wrong_password_and_unknown_user_look_identical(client):
    wrong_password = login(client, "Calven", "nope-nope-nope")
    unknown_user = login(client, "nobody")
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()


def test_login_missing_fields_is_422_not_500(client):
    assert client.post("/token", data={"username": "Calven"}).status_code == 422


def test_login_is_rate_limited(client):
    for _ in range(settings.login_max_failures):
        assert login(client, "Calven", "bad-password").status_code == 401
    blocked = login(client, "Calven")  # even the correct password is refused now
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


def test_api_requires_a_token(client):
    for method, path in [("get", "/tasks"), ("post", "/tasks"), ("get", "/users")]:
        assert getattr(client, method)(path).status_code == 401


def test_garbage_and_forged_tokens_are_rejected(client):
    assert client.get("/tasks", headers={"Authorization": "Bearer garbage"}).status_code == 401
    forged = jwt.encode({"sub": "1", "exp": 4102444800}, "wrong-key-wrong-key-wrong-key-0000", algorithm="HS256")
    assert client.get("/tasks", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    expired = jwt.encode({"sub": "1", "exp": 1}, settings.secret_key, algorithm="HS256")
    assert client.get("/tasks", headers={"Authorization": f"Bearer {expired}"}).status_code == 401


# ---------- users ----------
def test_list_users_hides_password_hashes(client, user_headers):
    response = client.get("/users", headers=user_headers)
    assert response.status_code == 200
    users = response.json()
    assert {u["username"] for u in users} >= {"Calven", "Mahymar", "Sothearith"}
    assert all(set(u) == {"id", "username"} for u in users)


def test_only_admin_can_create_users(client, admin_headers, user_headers):
    payload = {"username": "newperson", "password": "a-good-password"}
    assert client.post("/users", json=payload, headers=user_headers).status_code == 403
    created = client.post("/users", json=payload, headers=admin_headers)
    assert created.status_code == 201
    assert client.post("/users", json=payload, headers=admin_headers).status_code == 409
    assert login(client, "newperson", "a-good-password").status_code == 200


def test_create_user_validates_password(client, admin_headers):
    response = client.post("/users", json={"username": "shorty", "password": "short"}, headers=admin_headers)
    assert response.status_code == 422


# ---------- tasks ----------
def test_create_task_returns_nested_assignee(client, user_headers):
    users = client.get("/users", headers=user_headers).json()
    mahymar = next(u for u in users if u["username"] == "Mahymar")

    response = client.post(
        "/tasks",
        json={"description": "  Write docs  ", "priority": "High", "assignee_id": mahymar["id"]},
        headers=user_headers,
    )
    assert response.status_code == 201, response.text
    task = response.json()
    assert task["description"] == "Write docs"  # whitespace stripped
    assert task["assignee"] == {"id": mahymar["id"], "username": "Mahymar"}
    assert task["status"] == "To Do" and task["is_completed"] is False


def test_create_task_validation(client, user_headers):
    def post(**body):
        return client.post("/tasks", json=body, headers=user_headers)

    assert post(description="").status_code == 422
    assert post(description="   ").status_code == 422
    assert post(description="x" * 501).status_code == 422
    assert post(description="ok", priority="banana").status_code == 422
    assert post(description="ok", status="banana").status_code == 422
    assert post(description="ok", assignee_id=99999).status_code == 422


def test_task_lifecycle_complete_reopen_and_filters(client, user_headers):
    task = client.post("/tasks", json={"description": "Lifecycle task"}, headers=user_headers).json()
    task_id = task["id"]

    def ids(**params):
        page = client.get("/tasks", params={"limit": 200, **params}, headers=user_headers).json()
        return {t["id"] for t in page["items"]}

    assert task_id in ids(is_completed="false")
    assert task_id not in ids(is_completed="true")

    done = client.patch(f"/tasks/{task_id}", json={"is_completed": True}, headers=user_headers)
    assert done.status_code == 200
    assert done.json()["status"] == "Done" and done.json()["is_completed"] is True
    assert task_id in ids(is_completed="true")
    assert task_id not in ids(is_completed="false")

    reopened = client.patch(f"/tasks/{task_id}", json={"status": "In Progress"}, headers=user_headers)
    assert reopened.json()["is_completed"] is False

    conflicting = client.patch(
        f"/tasks/{task_id}", json={"status": "Done", "is_completed": False}, headers=user_headers
    )
    assert conflicting.status_code == 422


def test_patch_can_unassign_but_not_null_required_fields(client, user_headers):
    users = client.get("/users", headers=user_headers).json()
    task = client.post(
        "/tasks", json={"description": "Assign me", "assignee_id": users[0]["id"]}, headers=user_headers
    ).json()

    unassigned = client.patch(f"/tasks/{task['id']}", json={"assignee_id": None}, headers=user_headers)
    assert unassigned.json()["assignee"] is None

    untouched = client.patch(f"/tasks/{task['id']}", json={"description": None}, headers=user_headers)
    assert untouched.json()["description"] == "Assign me"

    assert client.patch(f"/tasks/{task['id']}", json={"assignee_id": 99999}, headers=user_headers).status_code == 422


def test_pagination(client, user_headers):
    for i in range(3):
        client.post("/tasks", json={"description": f"Paging {i}"}, headers=user_headers)
    page = client.get("/tasks", params={"limit": 2, "offset": 0}, headers=user_headers).json()
    assert len(page["items"]) == 2
    assert page["total"] >= 3 and page["limit"] == 2 and page["offset"] == 0
    assert client.get("/tasks", params={"limit": 0}, headers=user_headers).status_code == 422
    assert client.get("/tasks", params={"limit": 201}, headers=user_headers).status_code == 422


def test_missing_task_is_404(client, user_headers):
    assert client.get("/tasks/99999", headers=user_headers).status_code == 404
    assert client.patch("/tasks/99999", json={"status": "Done"}, headers=user_headers).status_code == 404


def test_only_admin_can_delete_tasks(client, admin_headers, user_headers):
    task = client.post("/tasks", json={"description": "Delete me"}, headers=user_headers).json()
    assert client.delete(f"/tasks/{task['id']}", headers=user_headers).status_code == 403
    assert client.delete(f"/tasks/{task['id']}", headers=admin_headers).status_code == 204
    assert client.get(f"/tasks/{task['id']}", headers=user_headers).status_code == 404


# ---------- pages ----------
def test_pages_are_served(client):
    for path in ["/", "/dashboard", "/completed"]:
        response = client.get(path)
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
    assert client.get("/static/app.js").status_code == 200
