# Instance metric query verification

The synthetic query fixture was imported only as `altinn.instance.query_fixture`, with a separate `fixture.run` label per execution. It is separate from the services' actual exported `altinn.instance.start_time` metric. These results verify query behavior; the live service deployment results are recorded separately.

## Reproduce

```sh
kubectl -n observability port-forward svc/vmsingle-metrics-a 18428:8428
kubectl -n grafana port-forward svc/grafana 13000:80
python3 .scripts/studio-instance-telemetry/verify-query-fixtures.py
python3 .scripts/studio-instance-telemetry/verify-grafana-annotation-frames.py
```

The second script reads through the real Grafana `altinn-studio-metrics` datasource, including its configured proxy Authorization, rather than calling VictoriaMetrics directly. JSON input/requests/responses are in `query-fixture-input.jsonl`, `query-fixture-results.json`, and `grafana-annotation-frames.json` beside this report. Acknowledged VictoriaMetrics imports can take several seconds to become queryable; the fixture uses bounded visibility retries and `nocache=1`.

## Assertions passed

- Five exact deploy dots across the fixture proxy and worker, grouped only by environment/version. The first instance of the old version disappeared before the range; in-range scale-up and rollback of that old version produce no deploy dot. A deliberately narrow history query is retained as a negative control and incorrectly emits an old-version deploy dot.
- Ten exact process start dots, including a restart within the same pod UID with a different `service.instance.id`. A duplicate exporter label does not duplicate a dot.
- Recent reporting counts are eight proxy processes and one worker, despite ten raw recent source series. During a gap, the proxy count drops to four and returns to eight when telemetry resumes. This is reporting recency, not an alive/ready assertion.
- Inclusive from/to filters include the exact boundaries and exclude the start 1ms before the range and the start 1s after it. Millisecond arithmetic also correctly filters boundaries offset by exactly 1ms.
- A process with its **only sample exactly at range start** is included using the restart lookback `[1m${__range_ms}ms]`. A negative control using only `[${__range_ms}ms]` drops that event because the raw sample lookbehind interval excludes its lower bound. The additional minute supplies sample coverage; the value comparisons still enforce exact event boundaries.
- Real Grafana 12.4.8 backend queries with `instant: true`, `range: false`, `format: time_series` return five deploy and ten process Time/Value frames, one row per frame. Range queries return the same number of frames and one distinct timestamp value in each frame. Fixed `@` evaluation prevents the retained earliest version from changing across query steps.

## Recommended dashboard queries

Substitute the Designer selector `"service.name"="studio-designer"` for the PDF3 selector below. Retain the environment selector in either dashboard.

Deploy / first retained start of a version:

```metricsql
(
  (
    min by ("deployment.environment.name", "service.version") (
      min_over_time({"altinn.instance.start_time",
        "service.name"=~"pdf3-(proxy|worker)",
        "deployment.environment.name"=~"$env"}[90d] @ (${__to} / 1000))
    ) >= (${__from} / 1000)
  ) <= (${__to} / 1000)
) * 1000
```

Process start, including rollout, same-version restart, and scale-up:

```metricsql
(
  (
    min by ("deployment.environment.name", "service.version", "service.name",
            "service.instance.id", "k8s.pod.uid") (
      min_over_time({"altinn.instance.start_time",
        "service.name"=~"pdf3-(proxy|worker)",
        "deployment.environment.name"=~"$env"}[1m${__range_ms}ms] @ (${__to} / 1000))
    ) >= (${__from} / 1000)
  ) <= (${__to} / 1000)
) * 1000
```

`1m${__range_ms}ms` is a compound MetricsQL duration: one minute plus the exact dashboard range in milliseconds. Arithmetic such as `[${__range_ms}ms+1m]` is **invalid** on the running VictoriaMetrics version.

Both annotation targets should set `instant: true`, `range: false`, `format: time_series`; the annotation sets `useValueForTime: true`. The multiplication converts the gauge's Unix seconds to the milliseconds Grafana requires. `${__from}` / `${__to}` arithmetic preserves Grafana's exact millisecond bounds; `:date:seconds` truncates those bounds.

Instances reporting (instant stat at dashboard range end):

```metricsql
count by ("deployment.environment.name", "service.name") (
  group by ("deployment.environment.name", "service.name", "service.instance.id") (
    present_over_time({"altinn.instance.start_time",
      "service.name"=~"pdf3-(proxy|worker)",
      "deployment.environment.name"=~"$env"}[1m])
  )
)
```

This deliberately preserves an empty result when no instance telemetry arrives. Adding `or vector(0)` would turn a missing telemetry pipeline into an apparent zero-instance result.

## Defined limitations

- The blue event is the earliest start **among retained, successfully exported samples for that version**. Studio production retention is 90 days; the local fixture retains three days. If the original instances' entire history expires and an old version is started again, this metric cannot prove that version was deployed previously. A first deployment older than retention can therefore be represented by its earliest remaining process. No per-process-only query can reconstruct discarded history.
- Rollbacks to a version with retained prior samples generate process dots, not another blue deploy dot. Telemetry alone does not identify deployment intent, restart cause, or scale-up cause.
- A service that never successfully exports this gauge cannot produce an annotation or enter the reporting count. A gap does not alter a known process's value; a process absent for more than a minute disappears from the reporting count until another sample arrives.
- During rolling replacement, the recent-sample count includes both old and new processes for up to a minute after the old process stops reporting. `service.instance.id` must be unique per process; an explicitly configured static identity violates that condition.
- Go captures the timestamp at telemetry package initialization, before `main`, while Designer uses the operating system's process start time. The Go value approximates process creation by the runtime/dependency initialization delay. Keeping Go portable and dependency-free avoids Linux `/proc` parsing solely for this timestamp; the deviation should be explicit in the service PR.
- The 90-day lookup scans more history than ordinary dashboard panels. Instant annotation queries avoid returning thousands of repeated points. Performance at full production retention/cardinality has not been benchmarked by this local short-history fixture.

## Primary implementation references

- [Grafana 12.4.8 executeAnnotationQuery](https://github.com/grafana/grafana/blob/v12.4.8/public/app/features/annotations/executeAnnotationQuery.ts) preserves the query target, including instant/range settings.
- [Grafana 12.4.8 Prometheus annotation processing](https://github.com/grafana/grafana/blob/v12.4.8/packages/grafana-prometheus/src/annotations.ts) reads Time/Value frames and uses the numeric value as milliseconds when `useValueForTime` is enabled. Repeated identical timestamps within each series collapse into one event.
- [Grafana 12.4.8 annotation editor](https://github.com/grafana/grafana/blob/v12.4.8/packages/grafana-prometheus/src/components/AnnotationQueryEditor.tsx) documents millisecond timestamp values.
- [MetricsQL](https://docs.victoriametrics.com/metricsql/) documents rollups over raw samples, arbitrary expressions for the `@` modifier, and `present_over_time`.
