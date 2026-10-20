# Shared-GPU model lifecycle

[vLLM installation](README.md) · [Durable queue](queue.md)

Use this profile when the GPU also serves interactive work or other models.
The API, Redis, PostgreSQL and queue worker can remain available while the vLLM
container is stopped. A retrieval request starts the existing container only
after resource admission succeeds. An independent supervisor stops it after
120 seconds without an active model lease, releasing its GPU allocations.

The model container uses `restart: "no"`; it does not reserve GPU memory at
boot. Model files and compilation caches remain on disk. The first request
after unloading includes a cold start; later requests can reuse the running
model until the idle deadline.

## Admission and failure behavior

- Another GPU computation, insufficient free GPU memory, a missing container,
  or a recent failed startup makes the plugin unavailable. New retrieval tasks
  are not published in these cases.
- The default cold-start requirement is 90% of total GPU memory plus 256 MiB,
  matching the supplied vLLM profile. On a 12,288 MiB GPU this is 11,316 MiB.
- A small, recognized desktop graphics process is not treated as a competing
  model. Only exact process basenames in the desktop allowlist are ignored,
  and only while each uses at most 256 MiB. Other compute processes are busy
  signals regardless of their current utilization.
- A detected competing computation takes priority. The supervisor stops only
  the configured CiteWeave container. It never terminates another process or
  container.
- Startup is bounded, and a failed startup stops the model container and
  enters a 30-second cooldown. The plugin does not keep retrying the same call.
- A task must still hold its lease and pass the resource/model checks before
  its evidence can be returned. Resource loss or preemption produces an error,
  rather than partial or cached evidence for the answer model to use.

These checks coordinate CiteWeave processes. They are not an operating-system
reservation or a guarantee against allocation races with unrelated GPU users.
Keep the guard's memory requirement aligned with changes to the model, vLLM
memory fraction or context budget.

## Configuration

Complete the queued deployment, then add these values to the shared backend
`.env`:

```dotenv
CITEWEAVE_MODEL_LIFECYCLE=ondemand
CITEWEAVE_VLLM_CONTAINER=dsh-citeweave-vllm
CITEWEAVE_MODEL_IDLE_SECONDS=120
CITEWEAVE_MODEL_START_TIMEOUT=120
```

The free-memory requirement is calculated from the GPU by default. An explicit
`CITEWEAVE_MODEL_MIN_FREE_MIB` can override it when deploying a different serving
profile. The service user needs access to Docker and `nvidia-smi`; the controller
starts and stops only the already-provisioned container. It does not download
images or silently substitute another model.

Run the [model supervisor](systemd/dsh-citeweave-model-watch.service) alongside
the API, worker and result-cleanup scheduler. Replace the template's backend path
with this repository's `backend/` absolute path before installing it as a user service:

```sh
systemctl --user daemon-reload
systemctl --user enable --now dsh-citeweave-model-watch
systemctl --user restart dsh-citeweave-worker dsh-citeweave-backend
```

Remove any API-service startup condition that requires vLLM to be running.
The API must start while the model is unloaded. Apply `restart: "no"` to an
existing model container with:

```sh
docker update --restart=no dsh-citeweave-vllm
```

Do not manually start a second vLLM instance against the same GPU. When no
retrieval is active, the standalone supervisor can be inspected or run from
the backend checkout with:

```sh
.venv/bin/python -m citeweave.model_runtime watch
```

Run exactly one supervised watcher for this deployment. Its systemd stop hook
also stops the configured model container when the supervisor exits.

## Leases and observation

Redis serializes lifecycle operations and tracks a tokenized active lease.
The worker renews it every five seconds; it expires after 30 seconds without
renewal. A worker crash therefore cannot permanently pin the model on the GPU.
The independent supervisor checks the idle state every five seconds. Redis
failure fails closed rather than keeping the model indefinitely allocated.

`/ready` checks resource admission and queue dependencies without starting the
model. An unloaded model can be ready for a cold start; a busy or insufficient
GPU is unavailable. Readiness is not a guarantee that a later allocation will
succeed. Task and request IDs remain available in errors for diagnosis.

Verify a successful cold request, automatic idle shutdown, worker-loss lease
expiry, and immediate rejection while a separate GPU computation exists. After
idle shutdown, `nvidia-smi` can still show display-server or desktop memory; the
controller releases CiteWeave's allocations, not every allocation on the card.

The Harness answer model stays independently configured. On unavailability it
continues without evidence from the failed CiteWeave call, and the plugin's
guidance tells it not to retry that failed call within the same answer.
