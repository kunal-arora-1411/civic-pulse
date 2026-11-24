# Demo deployment

- **Web:** https://civicpulse-demo-gamma.vercel.app (Vercel project `civicpulse-demo`, root `apps/web`)
- **API:** https://13-207-212-110.sslip.io (EC2 `i-00c086ee112eff1ad`, t3.small, ap-south-1)
- **Photos:** S3 bucket `civicpulse-demo-media-206238482917`

The browser only talks to Vercel. `apps/web/vercel.json` rewrites `/api/v1/*` to the API, so the API and its refresh cookie are same-origin. The API runs with the fake vision models (`AI_PROVIDER=fake`): no model weights and no ai-worker. Sign-in accepts the fixed code `000000` (`DEV_FIXED_OTP`), so this environment is for demos only.

## Continuous deployment

`.github/workflows/deploy.yml` runs after the CI workflow succeeds on `main`, and can also be started by hand (Actions → Deploy → Run workflow).

1. **API.** GitHub signs in to AWS through OIDC as the role `civicpulse-github-deploy`. Only `main` of this repository can assume it, and it can only run commands on this one instance. Through SSM, the job runs `infra/deploy/deploy.sh <sha>` on the server. The script checks the commit out, rebuilds the images and restarts the stack; the `migrate` service applies Alembic migrations before the API starts. Then the script waits for `/health`.
2. **Web.** Once the API is healthy, the job deploys `apps/web` to Vercel production.

Repository secret needed: `VERCEL_TOKEN`. AWS needs no stored keys.

## On the server

The repo is cloned at `~/civic-pulse`. The secrets live in `~/deploy/.env`, which is never committed: database passwords, signing secrets, the S3 key and `CORS_ORIGINS`.

```sh
~/civic-pulse/infra/deploy/deploy.sh origin/main          # deploy by hand
C="sudo docker compose -f ~/civic-pulse/infra/deploy/compose.yml --env-file ~/deploy/.env"
$C ps; $C logs -f api worker                               # status, logs
$C exec -T worker python scripts/seed.py                   # demo data (idempotent)
$C exec -T db pg_dump -U civicpulse civicpulse | gzip > db.sql.gz   # backup
```
