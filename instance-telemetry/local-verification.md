# Live Studio instance telemetry verification

Worktrees: `.worktrees/studio-telemetry-prototype` (Studio main `2e666e27fb`) and `.worktrees/studio-instance-dashboards` (stacked on dashboard alignment `4242fde`).

The existing minimal-monitoring Kind stack was reused. It had been started in round 1 from `src/Runtime/pdf3` with:

```sh
DEVENV_DASHBOARDS_REPOSITORY=/home/agent/code/.worktrees/studio-dashboard-alignment make start-minimal-monitoring
```

It runs the production router/gateway/observability-proxy path, production metric allowlist, and real VictoriaMetrics. Local differences are documented in `infra/observability/local/README.md`: one backend, three-day retention, fixed dummy tokens, no self-scraping/Application Insights. No allowlist or telemetry pipeline configuration was changed.

## Build and deploy

Built actual pdf3 binaries with the changes, without changing the build/deploy pipeline:

```sh
CGO_ENABLED=0 go build -ldflags '-X altinn.studio/pdf3/internal/telemetry.serviceVersion=instance-v1' -o <artifacts>/proxy-v1/main ./cmd/proxy
CGO_ENABLED=0 go build -ldflags '-X altinn.studio/pdf3/internal/telemetry.serviceVersion=instance-v2' -o <artifacts>/proxy-v2/main ./cmd/proxy
CGO_ENABLED=0 go build -ldflags '-X altinn.studio/pdf3/internal/telemetry.serviceVersion=instance-v1' -o <artifacts>/worker-v1/main ./cmd/worker
```

Proxy images are scratch + the binary, matching the production proxy runtime. The worker's new binary was layered over the existing fixture worker image, preserving its browser, fonts and entrypoint. Built and pushed `localhost:5001/pdf3-proxy:instance-v1`, `:instance-v2`, and `localhost:5001/pdf3-worker:instance-v1` with Podman (`docker push --tls-verify=false` for the local HTTP registry).

Suspended only local `runtime-pdf3/pdf3-app` Flux reconciliation during manual rollout experiments so it would not restore fixture images. The observability stack remained running, with its real allowlist. The local application reconciliation remains suspended for inspection; resume it with `kubectl -n runtime-pdf3 patch kustomization pdf3-app --type merge -p '{"spec":{"suspend":false}}'` to restore the fixture's usual app images.

```sh
kubectl -n runtime-pdf3 set image deployment/pdf3-proxy pdf3-proxy=localhost:5001/pdf3-proxy:instance-v1
kubectl -n runtime-pdf3 set image deployment/pdf3-worker pdf3-worker=localhost:5001/pdf3-worker:instance-v1
kubectl -n runtime-pdf3 rollout status deployment/pdf3-proxy
kubectl -n runtime-pdf3 rollout status deployment/pdf3-worker
kubectl -n runtime-pdf3 set image deployment/pdf3-proxy pdf3-proxy=localhost:5001/pdf3-proxy:instance-v2
kubectl -n runtime-pdf3 rollout status deployment/pdf3-proxy
kubectl -n runtime-pdf3 rollout restart deployment/pdf3-proxy
kubectl -n runtime-pdf3 rollout status deployment/pdf3-proxy
kubectl -n runtime-pdf3 scale deployment/pdf3-proxy --replicas=3
kubectl -n runtime-pdf3 rollout status deployment/pdf3-proxy
```

The runnable `verify-live.py` records snapshots and asserts queries through the same observability-proxy read route/token used by Grafana (`:18080/internal/observability/metrics`). `live-results-summary.json` contains raw query results with pod snapshots omitted. The original run used an implicit-lookback selector to wait for processes to disappear; that selector retains stale processes longer than one minute. The corrected verifier explicitly uses `last_over_time(...[1m])`; `finish-live.py` resumed final assertions from saved deployment snapshots without repeating mutations.

## Results

- Exact stored name: `altinn.instance.start_time`, a gauge of Unix seconds, unchanged by the real allowlist and OTLP ingestion. Both proxy and worker report it while idle.
- Resource labels include `service.name`, `service.version`, `deployment.environment.name`, `k8s.pod.uid`, and a process UUID in `service.instance.id`.
- **Two deploy dots total** (instance-v1, instance-v2), aggregating proxy and worker by environment/version.
- **Nine process-start dots**: original two proxies, two original workers, two v2 proxies, two replacement v2 proxies, one scale-up proxy.
- A second range begins after v2 was already deployed, with the first v2 processes gone and replacements starting inside the range: **zero deploy dots**.
- After waiting out replaced processes' one-minute reporting window: **three proxies and two workers**.
- Synthetic edge cases and actual Grafana datasource frames are recorded separately in `query-verification.md`; synthetic data uses a different metric and is never presented as service telemetry.

For visible traffic, sent controlled HTTP 400 requests to the real proxy (`POST /pdf`, JSON `{}`), then reloaded the actual dashboards using `playwright-cli -s=studio-instance-round2 open --browser chromium`. Imported the source dashboard JSON into local Grafana and its mounted ConfigMap, retaining UIDs; no production Grafana changes were made. Screenshots show real service metrics/annotations. The two blue version dots overlap the orange process dots by definition; a separate capture disables the orange layer to show blue dots clearly.

Designer has no running deployment in the minimal runtime fixture. Its implementation is tested through the existing application hosting pipeline, including repeated gauge collection, all-signal identity, configured override, version identity and an actual HTTP/protobuf OTLP payload. Designer through the Studio collector and VictoriaMetrics is **unverified**.

## Verification commands

```sh
# pdf3
make lint build test
# Designer (SDK 10.0.401, installed because the original SDK was 10.0.302)
CI=true dotnet build src/Designer/Designer.csproj --no-incremental -p:CSharpier_Check=true
dotnet test tests/Designer.Tests/Designer.Tests.csproj --no-build --no-restore --filter FullyQualifiedName~Designer.Tests.Hosting.OpenTelemetryTests
# 18/18 passed; final targeted checks 5/5 passed.
# Repo spelling (yarn wrapper cannot run without node_modules, same underlying runner)
node scripts/spellcheck/run.mjs quick
# Dashboards
python3 scripts/validate-dashboards.py
python3 scripts/build-public-dashboards.py --check
dashboard-linter lint --strict products/studio/dashboards/designer.json
dashboard-linter lint --strict products/studio/dashboards/pdf3.json
kustomize build .
kubeconform -strict -skip ExternalSecret,SecretStore,Vault,ApplicationIdentity -schema-location default -schema-location 'schemas/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' -summary <rendered-root.yaml>
git diff --check
```

pdf3 lint: zero issues; build, unit tests and PDF/A integration tests pass. PDF generation behavior was unchanged; the full browser/PDF E2E suite was not run. Dashboard validator/public check/strict lint/root schema validation/diff check pass. Internal operational instrumentation needs no altinn-studio-docs product documentation change; proposed shared-metric guide wording is in the draft service PR.
