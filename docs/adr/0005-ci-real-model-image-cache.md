# ADR 0005: Real models in CI, with a cached AI worker image

- Status: accepted
- Date: 2026-11-26

## Context

The end-to-end suite runs against the whole compose stack, including the `ai-worker`, whose image is about 1.4 GB uncompressed: Python, ~630 MB of dependencies (onnxruntime, tokenizers, headless OpenCV) and ~608 MB of CLIP and YuNet weights fetched from the Hugging Face Hub and checked against `apps/api/models.lock.json`. Building it from scratch on every push costs several minutes of installs and downloads, and makes CI depend on the Hub being reachable each time. On top of that, a separate `images` job built the same image a second time.

The Phase 2 acceptance criteria (AC-02 to AC-08) are about what the real model does: a real pothole photo gets a pothole suggestion, the same photo twice auto-links, a different scene nearby does not. The fake models can't prove any of that, so the real model must keep running somewhere in CI.

Options considered:
1. **Fake models in the main e2e job, a separate real-model job** (for example nightly). Fast PRs, but a change that breaks matching with the real model would only show up later, and two stacks double the maintenance.
2. **Pull a prebuilt AI worker image from a registry.** Fast, but needs a publishing pipeline, registry credentials and a rule for when the image is rebuilt; a PR that changes the worker would still have to build it.
3. **Build in the e2e job with BuildKit's layer cache in the GitHub Actions cache.** One stack, always built from the commit under test, and only the layers that changed are rebuilt.

## Decision

Option 3.
- The e2e job builds the `db`, `api` and `ai-worker` images with `docker/build-push-action` and `cache-from`/`cache-to: type=gha` (`mode=max`), each image in its own cache scope so they don't evict each other, and loads them into the runner's Docker. `docker compose up --no-build` then starts the stack from them.
- The AI worker Dockerfile is already ordered for this: dependencies (keyed on `uv.lock`), then weights (keyed on `models.lock.json` and the download script), then the code. A typical PR changes only the last layers, so the ~1.3 GB of dependencies and weights come from the cache.
- The separate `images` job is gone. The e2e job builds every image on every PR, so a broken Dockerfile still fails CI.
- The real model runs in the e2e job on every PR and push. The AI end-to-end tests check which embedding model is active and skip themselves only when a stack runs the fake one (`infra/docker-compose.fake-ai.yml`), which is for local work.
- The `ai-models` job keeps its own cache of the raw weights (`actions/cache`, keyed on the lock) for the model unit tests, which need no Docker.

## Consequences

- Warm runs skip the dependency install and weight download; the first run after a lock change pays for them once.
- The GitHub Actions cache is limited to 10 GB per repository and evicts entries unused for 7 days. The three images fit comfortably (the AI worker's layers are ~700 MB compressed), but after a quiet week the first run is cold. Cache written on `main` is readable by every PR branch.
- A cold run still needs the Hugging Face Hub. If that becomes a problem, the next step is option 2 for the weights layer only.
- The e2e job's timeout goes up to 40 minutes to allow for a cold build plus the AI tests, which include waiting out the two-minute matching fallback (AC-03).
