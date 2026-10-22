# Task Dashboard

A small Jira-style task management web application, built to demonstrate a complete CI/CD pipeline
(SWE40006 Software Deployment and Evolution, Group 2).

- **Application:** FastAPI + async SQLAlchemy, PostgreSQL in Kubernetes (SQLite for local development and tests)
- **Pipeline:** GitHub -> GitHub Actions self-hosted runner -> build and test -> Docker image -> Kubernetes (Docker Desktop) -> Prometheus monitoring

## What the application does

- Log in with a username and password (JWT access tokens)
- Create tasks with a description, priority (High / Medium / Low) and an assignee
- Move tasks through **To Do -> In Progress -> Done**, or complete and reopen them
- Active tasks are on `/dashboard`, completed tasks on `/completed`
- Admins can create users and delete tasks; all other routes need a valid login
- Interactive API documentation at `/docs`

Not implemented yet: task due dates (listed in the project brief).

## Repository layout

| Path | Purpose |
| --- | --- |
| `main.py` | App entry point, page routes, startup (table creation, optional demo users) |
| `routers/` | API routes: `auth`, `users`, `tasks`, `health` |
| `models.py`, `schema.py` | Database models and request/response schemas |
| `security.py`, `deps.py` | Password hashing, JWT, login rate limiting, auth dependencies |
| `config.py`, `database.py`, `seed.py` | Settings from environment variables, database engine, demo data |
| `templates/`, `static/` | HTML pages, stylesheet and shared JavaScript |
| `tests/` | Automated tests (pytest) |
| `Dockerfile`, `.dockerignore` | Container image |
| `k8s/` | Kubernetes manifests (`task-dashboard.yaml`, `postgres.yaml`) and monitoring values. See `k8s/README.md` for the Kubernetes handoff notes |
| `.github/workflows/ci-cd.yml` | The pipeline |

## Run locally (no Docker, no Postgres)

PowerShell, from the repository folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pip install aiosqlite
Copy-Item .env.example .env
```

Edit `.env`:

```
DATABASE_URL=sqlite+aiosqlite:///./taskdb.db
SECRET_KEY=<at least 32 characters>
SEED_DEMO_USERS=true
SEED_PASSWORD=<at least 8 characters>
```

Generate a key with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
Then start the app and open http://localhost:8000:

```powershell
uvicorn main:app --reload
```

`SEED_DEMO_USERS` creates three accounts on first start (Calven as admin, Mahymar and Sothearith),
all using `SEED_PASSWORD`. Leave it off anywhere real.
`.env` is ignored by Git. Each developer creates their own.

## Tests

```powershell
pytest --cov=. --cov-report=term-missing
```

The tests use a temporary SQLite database, so no server is needed. The pipeline fails
if any test fails or coverage drops below 80%.

## Docker

```powershell
docker build -t task-dashboard .
```

The image needs `DATABASE_URL` and `SECRET_KEY` at run time. Nothing secret is baked in.
It listens on port 8000 and runs as a non-root user.

## Kubernetes (Docker Desktop)

Enable Kubernetes in Docker Desktop (Settings -> Kubernetes, kubeadm, one node), then check
`kubectl get nodes` shows `Ready` and the context is `docker-desktop`.

One-time setup (the pipeline expects these to exist):

```powershell
kubectl create namespace task-dashboard

kubectl -n task-dashboard create secret generic postgres-credentials --from-literal=POSTGRES_USER=<user> --from-literal=POSTGRES_DB=<database> --from-literal=POSTGRES_PASSWORD=<letters-and-numbers-only>

kubectl -n task-dashboard create secret generic app-secret --from-literal=SECRET_KEY=<48+ random characters> --from-literal=SEED_DEMO_USERS=true --from-literal=SEED_PASSWORD=<login password>

kubectl -n task-dashboard apply -f k8s/postgres.yaml
kubectl -n task-dashboard wait --for=condition=Ready pod/postgres --timeout=300s
```

Never commit Secret values. Use a database password without `@ / : ? #`, because it is placed in
a connection URL.

To view the running app:

```powershell
kubectl -n task-dashboard port-forward svc/task-dashboard 8000:80
```

then open http://localhost:8000. (Port-forward reaches a single pod. Service load balancing happens
inside the cluster.)

Monitoring (Prometheus and Grafana) is installed separately from `k8s/monitoring-values.yaml`;
the commands are in `k8s/README.md`.

## The pipeline

Defined in `.github/workflows/ci-cd.yml`. It runs on a self-hosted GitHub Actions runner on the
machine that has Docker Desktop and Kubernetes (runner label `docker-desktop`).

| Trigger | What happens |
| --- | --- |
| Pull request to `main` | Tests with the 80% coverage gate |
| Push to `main` | Tests, then build, deploy, verify, tag |

Deploy stages:

1. **Build** the image, tagged `task-dashboard:v1.0.<run number>` and with the short commit ID.
2. **Roll out** by applying `k8s/task-dashboard.yaml` with the new tag. The Deployment has two
   replicas and a rolling update that never removes a working pod before its replacement is ready.
3. **Verify** with a readiness check (`/ready`) inside a pod.
4. **Roll back** automatically (`kubectl rollout undo`) if the rollout or verification fails.
5. **Tag** the released version in Git (`v1.0.<run number>`).
6. **Report** the time from commit to live in the run summary (target: under 5 minutes).

### Running the runner

On the machine with Docker Desktop, in the runner folder:

```powershell
.\run.cmd
```

Leave the window open. It must run as your own Windows user, which can reach Docker Desktop and
`kubectl`. Check it shows as **Idle** under Settings -> Actions -> Runners.

## Health endpoints

| Endpoint | Meaning |
| --- | --- |
| `GET /health` | The process is up (liveness). Does not touch the database |
| `GET /ready` | The app can reach its database (readiness) |

## Troubleshooting

- **App refuses to start, "field required":** `DATABASE_URL` or `SECRET_KEY` is missing from `.env` or the environment.
- **Queued job never starts:** the runner is offline or doesn't have the `docker-desktop` label.
- **Pods stay in `ImagePullBackOff`:** the image isn't visible to the cluster. Use the kubeadm cluster type, not kind.
- **Pods restart repeatedly:** run `kubectl -n task-dashboard logs deploy/task-dashboard`. A database password that
  doesn't match the one Postgres was first created with is a common cause.
- **Docker Desktop errors mentioning a read-only file system:** the drive ran out of space. Free disk space first.
