# Switching the vision model

Embeddings are stored per `(media_id, model_id)`, so a new model's vectors
live beside the old ones. Matching only ever compares vectors of one model,
so nothing changes for citizens until step 4.

## 1. Add the new model alongside
- Add the model behind `app/ai/interfaces.py` (same `EMBEDDING_DIM`; the
  code refuses a model with another dimension) and pin it in the models lock.
- Deploy the `ai-worker` with the new model. On start it registers itself
  in `model_registry`. Only `ai-worker` consumes the `ai` queue; never let
  the regular worker pick it up, or fake and real vectors will mix.
- Note the new `model_id` (e.g. `clip-vit-b32@2`).

Caveat: while the ai-worker runs the new model, new uploads are embedded
with it only. Keep the reindex window short, or run the old model's matching
until step 4 knowing fresh photos lack old-model vectors (they go to human
review rather than auto-link, which is safe).

## 2. Reindex
From the API or ai-worker container:

```
python scripts/reindex_embeddings.py --model-id <new> --dry-run
python scripts/reindex_embeddings.py --model-id <new> --batch-size 50 --max-per-second 5
```

- Default mode sends each photo to the `ai` queue as `analyze_media`;
  the ai-worker embeds it. `--inline` embeds in-process (run it inside the
  ai-worker container; it refuses if its model isn't `<new>`).
- `--tenant <uuid>` limits the run to one municipality.
- Resumable: rerun at any time; photos already embedded for `<new>` are
  skipped. A `--dry-run` after queue mode drains should report 0.

## 3. Verify the evaluation
Run the evaluation in `apps/api/scripts/eval` against `<new>` and compare
with `docs/eval/phase-2-baseline.md`. Record the metrics (including the
matching thresholds such as `visual_min`) in the model's `model_registry`
row. Do not proceed if duplicate recall or auto-link precision regresses.

## 4. Switch matching
Point matching at `<new>` (the deployed model id and its registry metrics).
Watch the review queue volume and auto-link rate for a day.

## 5. Drop the old embeddings
Once stable (keep at least a week for rollback):

```sql
DELETE FROM media_embeddings WHERE model_id = '<old>';
```

Run as the owner role, or via `system_session()`; RLS hides other tenants'
rows from `civicpulse_app`.

## Rollback
- Before step 5: redeploy the ai-worker with `<old>` and switch matching
  back; the old vectors are untouched. Run the reindex for `<old>` to fill
  photos uploaded while `<new>` was live.
- After step 5: redeploy `<old>` and run the full reindex for `<old>`;
  until it finishes, unmatched photos fall back to human review.
