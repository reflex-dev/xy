# Docs Site Deployment

How the XY documentation site reaches its three environments, and why that
ladder is deliberately independent of the library's release cadence.

The site is a Reflex app under `docs/app`. Each deploy is a frontend/backend
image pair pushed to ECR, Harbor, and ACR, and rolled out by the Flux consumers
of `reflex-dev/helm-charts` once a generated values PR merges. No workflow in
this repository talks to a cluster.

## The ladder

| Environment | Values file | Trigger | Workflow |
| --- | --- | --- | --- |
| dev | `charts/internal/values-tenant-dev.yaml` | every push to `main` | `deploy-docs-dev.yml` |
| stg | `charts/internal/values-stg.yaml` | a successful dev deploy, or dispatch with any ref | `deploy-docs-stg.yml` |
| prod | `charts/internal/values-prod.yaml` | dispatch + `production` environment approval | `deploy-docs-prod.yml` |

Two reusable workflows do the shared work: `_build-docs-images.yml` builds and
pushes the image pair, `_helm-docs-pr.yml` opens (and auto-merges) the chart
values PR.

## Deploys follow commits, not releases

Docs deployment used to hang off `push: tags: v*` — staging built only when the
library was released, and production additionally waited for the GitHub Release
and the PyPI upload to appear. That coupled two cadences that have no reason to
match. A typo fix, a new gallery example, or a corrected benchmark table had to
wait for the next version tag, and a release that slipped took the docs with it.

The trigger is now the commit. A docs change that lands on `main` is on dev
immediately and on staging in the same pipeline; shipping it to production is a
human decision, not a release event.

**The consequence is explicit, not hidden:** production docs can describe code
that is not on PyPI yet. `deploy-docs-prod.yml` resolves the nearest reachable
`v*` tag and that version's PyPI status *before* the approval gate and writes
both to the run summary, so the approver sees exactly how far ahead of the last
published release the promotion is. It is a report, never a gate — blocking on
it would restore the coupling this design removes.

## Build once, promote many

Every image pair is tagged `sha-<short7>`, the same scheme in all three
environments, so an image built once is the image every environment runs:

- the dev deploy builds the pair for a `main` commit;
- staging **promotes** that pair — the `workflow_run` path deliberately skips
  the build job, because rebuilding the same commit produces a second copy of
  bytes that already exist;
- production promotes whatever staging currently runs, read straight out of
  `values-stg.yaml`. It refuses to act if that file's frontend and backend tags
  disagree, since a split staging state has no single thing to promote.

The one path that does build is a `workflow_dispatch` of `deploy-docs-stg.yml`
with an explicit `ref`: an arbitrary branch, tag, or commit may never have been
built. That is also how a preview of an unmerged branch reaches staging.

## Rollback

Dispatch `deploy-docs-prod.yml` with an explicit `image_tag`. Any tag still in
the registry ships without a rebuild, a revert commit, or a re-cut release. The
run summary marks it as the rollback path, and the commit lookup is
non-blocking — a tag whose git history has since been force-pushed away is
still promotable, because the images are what serve traffic.

## Separation of concerns

- **Staging never waits on production.** The workflows hold separate
  concurrency groups (`deploy-xy-docs-stg`, `deploy-xy-docs-prod`), so a
  production approval pending for up to 12 hours cannot queue staging deploys
  behind it. When both halves lived in one workflow they shared a group and it
  could.
- **Releases stay owned by `release.yml`.** No docs workflow creates tags or
  GitHub Releases, and `scripts/check_release_version.py` gates release tags
  only. Nothing in the docs ladder calls it.

## Repository configuration

| Kind | Name | Used by |
| --- | --- | --- |
| variable | `DOCS_DEPOT_PROJECT` | image builds |
| variable | `HELM_BOT_APP_ID` | chart PRs, prod tag lookup, dev SHA bookkeeping |
| variable | `LAST_DOCS_DEPLOY_SHA` | dev idempotency |
| secret | `HELM_BOT_PRIVATE_KEY` | as above |
| secret | `DEPOT_TOKEN` | image builds |
| secret | `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | ECR push |
| secret | `HARBOR_PUSH_USERNAME` / `HARBOR_PUSH_SECRET` | Harbor push |
| secret | `ACR_USERNAME` / `ACR_PASSWORD` | ACR push |
| environment | `production` | the prod approval gate |
