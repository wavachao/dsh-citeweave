# Durable retrieval queue

[Backend installation](README.md) · [Plugin configuration](../docs/reference.md)

This profile uses Celery 5.6.3, Redis and PostgreSQL. Redis stores pending work;
one Celery worker executes retrieval and local model requests; PostgreSQL stores
task states and results. The existing synchronous evidence endpoint submits a
task once and waits for its result, so existing Harness installations remain
compatible. Waiting for a result does not resubmit retrieval requests.

The pinned containers were validated as Redis 8.2.10 and PostgreSQL 17.11.
Image digests are recorded in [queue-compose.yml](queue-compose.yml).

```mermaid
flowchart LR
  H[Harness / DeepSeek] --> A[CiteWeave API]
  A --> R[(Redis queue)]
  R --> W[Celery worker: concurrency 1]
  W --> V[vLLM on GPU]
  W --> P[(PostgreSQL results)]
  P --> A
```

The queue applies across API processes and clients. Admission checks and
publication are serialized with a Redis lock; the waiting queue is limited to
four tasks by default. A full queue returns `429` with `Retry-After`. The worker
prefetches one task and acknowledges it after execution. Redis uses AOF
persistence with one-second fsync and a `noeviction` memory policy. PostgreSQL
and Redis each use a persistent Docker volume and bind only to loopback.

For a shared GPU, enable the [on-demand model lifecycle](model-lifecycle.md).
It keeps the broker and database available while releasing vLLM's GPU memory
between periods of use, and rejects new work when the GPU is unavailable.

Delivery is at least once. A worker crash can cause a task to be delivered again;
retrieval and model inference must tolerate repetition. This is not an
exactly-once execution guarantee. With Redis's configured visibility timeout,
an unacknowledged task can take up to an hour to become visible after an abrupt
worker loss. Graceful service restarts allow running work to finish.

## Install

Complete the [vLLM backend setup](README.md) in a dedicated backend checkout,
including the adapter patch and ranking assets. Install the queue's additional
dependencies using its hash-locked requirements:

```sh
uv pip install --python .venv/bin/python --require-hashes \
  -r "$CITEWEAVE_PLUGIN_DIR/backend/requirements-queue.txt"
```

Create a private `queue.env` with two independently generated passwords:

```dotenv
CITEWEAVE_REDIS_PASSWORD=replace-with-a-random-hex-password
CITEWEAVE_POSTGRES_PASSWORD=replace-with-another-random-hex-password
```

Generate each password with `python -c 'import secrets; print(secrets.token_hex(32))'`.
Protect the environment files with `chmod 600 queue.env .env`. Start the pinned
database and broker containers:

```sh
docker compose --env-file queue.env \
  -f "$CITEWEAVE_PLUGIN_DIR/backend/queue-compose.yml" up -d --wait
```

Add the following to the backend's `.env`, substituting the same passwords:

```dotenv
CITEWEAVE_QUEUE=celery
CITEWEAVE_BROKER_URL=redis://:REDIS_PASSWORD@127.0.0.1:6379/0
CITEWEAVE_RESULT_BACKEND=db+postgresql://citeweave:POSTGRES_PASSWORD@127.0.0.1:5432/citeweave
CITEWEAVE_MAX_WAITING=4
CITEWEAVE_JOB_WAIT_TIMEOUT=280
CITEWEAVE_RESULT_TTL=86400
```

These credentials belong to the broker and database. They are separate from
the CiteWeave workspace token and the Harness model-provider credentials.

Run one worker and one result-cleanup scheduler, each supervised as a separate
service. Start them from the backend checkout, using its Python environment and
the same `.env` as the API:

```sh
CITEWEAVE_WORKER=1 .venv/bin/celery -A citeweave.jobs:celery_app worker \
  --pool=solo --concurrency=1 --prefetch-multiplier=1 \
  --queues=citeweave --hostname=citeweave@%h --loglevel=INFO
.venv/bin/celery -A citeweave.jobs:celery_app beat \
  --schedule=work/celerybeat-schedule --loglevel=INFO
```

Run these commands in separate services or terminals; the worker command stays
in the foreground. A supervisor should restart failed processes. Use a graceful
shutdown allowance long enough for one retrieval to complete. Do not launch
multiple inference workers against the same GPU. The scheduler cleans expired
PostgreSQL results hourly; the default retention period is one day.

Set `CITEWEAVE_WORKER=1` only for the worker service, not in the shared `.env`.
It enables backoff and retry while the worker records results during a temporary
database outage. API processes keep bounded database reads and return a task ID
when storage is unavailable.

Restart the API with queue mode enabled. Use `.venv/bin/python` or
`uv run --no-sync` after installing the queue dependencies. Running a strict
sync against the original upstream lock can remove these optional dependencies.

### systemd user services

The [service templates](systemd/) supervise the API, worker, scheduler and optional model lifecycle. In
each template, replace `/srv/citeweave-backend` with the absolute path of the
backend clone owned by the service user. For the on-demand profile, copy all four files to
`~/.config/systemd/user/` and start them:

```sh
mkdir -p work ~/.config/systemd/user
systemctl --user daemon-reload
systemctl --user enable --now dsh-citeweave-model-watch dsh-citeweave-worker dsh-citeweave-beat dsh-citeweave-backend
```

For startup without an interactive login, an administrator can enable lingering
for that account with `loginctl enable-linger USERNAME`. Docker must also start
at boot; container restart policies restore Redis and PostgreSQL. The on-demand
supervisor starts vLLM only for admitted work. The API
template binds loopback; use the existing reverse-proxy or tunnel connection
described in the backend guide.

## Behavior and operations

| Endpoint | Behavior |
| --- | --- |
| `POST /api/jobs` | Accept an evidence request; return `202`, a task ID and its status URL. |
| `GET /api/jobs/{task_id}` | Return the existing task's state and, when available, its result or error. |
| `DELETE /api/jobs/{task_id}` | Request cancellation while the task is pending; do not kill active inference. |
| `POST /api/evidence` | Submit once and wait for the result; return `X-Task-ID` for later lookup. |

The asynchronous submission body is the same evidence request JSON used by
`/api/evidence`. All job endpoints require the existing workspace token when
authentication is enabled. A completed empty retrieval is a successful evidence
response with diagnostics; it does not assert that a useful source exists.

- `POST /api/evidence` and `POST /api/search` keep their synchronous response
  contracts. Each accepted request publishes one task and waits within the
  configured server timeout.
- The job API provides explicit submission, status lookup and cancellation of
  pending tasks. It uses the same workspace authentication as the evidence API.
- Search results with no readable sources return empty evidence and retrieval
  notes. They do not masquerade as a model-server outage. A failed English
  translation search can fall back to the original-language query.
- Genuine broker, database or inference failures remain errors. The plugin
  shows backend details and request IDs; it does not repeatedly resubmit failed
  requests.
- A timeout does not prove a task stopped. Use its task ID to inspect the
  existing task before submitting another one. Cancelling queued work does not
  forcibly interrupt running inference.

Inspect API, worker and scheduler logs using the task ID and request ID.
Monitor waiting queue length, task failures, result latency, Redis memory and
PostgreSQL disk use. `/ready` checks the serving dependencies; it does not
replace an end-to-end retrieval test.

Back up PostgreSQL with `pg_dump` and preserve the Redis AOF volume. Keep the
backend's image-cache directory with results: task metadata alone cannot
reconstruct an image file that has been deleted. Retention and backup policy
must account for both. Keep both service ports private; remote deployments
need private networking and appropriate TLS.

For example, create a PostgreSQL custom-format backup on the backend host:

```sh
docker exec dsh-citeweave-postgres pg_dump -U citeweave -d citeweave -Fc > citeweave-results.dump
```

Protect backups as application data. Test restoration separately before relying
on a backup policy; do not delete or recreate the service volumes during a
routine upgrade.

## Verification

Submit two different evidence requests concurrently and confirm they both
finish, with one worker executing at a time. Stop the worker, submit a pending
job, restart Redis without deleting its volume, then restart the worker and
confirm that job completes. Restart PostgreSQL and verify that completed task
results remain available. Test full-queue admission and queued cancellation
separately from live inference.

The [Celery configuration reference](https://docs.celeryq.dev/en/stable/userguide/configuration.html)
documents late acknowledgements, prefetch and database result expiry. Queue
durability does not make public search providers or source websites available;
unreadable pages remain explicit retrieval diagnostics.
