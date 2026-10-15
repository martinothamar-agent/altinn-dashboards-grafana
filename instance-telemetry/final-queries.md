# Final dashboard MetricsQL

Both annotation targets use `instant: true`, `range: false`, `format: time_series`, and `useValueForTime: true`. Value timestamps are milliseconds.

## pdf3

Deploys (first start of version):

```metricsql
((min by ("deployment.environment.name", "service.version") (min_over_time({"altinn.instance.start_time", "service.name"=~"pdf3-(proxy|worker)", "deployment.environment.name"=~"$env"}[90d] @ (${__to} / 1000))) >= (${__from} / 1000)) <= (${__to} / 1000)) * 1000
```

Restarts / new instances:

```metricsql
((min by ("deployment.environment.name", "service.version", "service.name", "service.instance.id", "k8s.pod.uid") (min_over_time({"altinn.instance.start_time", "service.name"=~"pdf3-(proxy|worker)", "deployment.environment.name"=~"$env"}[1m${__range_ms}ms] @ (${__to} / 1000))) >= (${__from} / 1000)) <= (${__to} / 1000)) * 1000
```

Instances reporting:

```metricsql
count by ("deployment.environment.name", "service.name") (group by ("deployment.environment.name", "service.name", "service.instance.id") (present_over_time({"altinn.instance.start_time", "service.name"=~"pdf3-(proxy|worker)", "deployment.environment.name"=~"$env"}[1m])))
```

## designer

Deploys (first start of version):

```metricsql
((min by ("deployment.environment.name", "service.version") (min_over_time({"altinn.instance.start_time", "service.name"="studio-designer", "deployment.environment.name"=~"$env"}[90d] @ (${__to} / 1000))) >= (${__from} / 1000)) <= (${__to} / 1000)) * 1000
```

Restarts / new instances:

```metricsql
((min by ("deployment.environment.name", "service.version", "service.name", "service.instance.id", "k8s.pod.uid") (min_over_time({"altinn.instance.start_time", "service.name"="studio-designer", "deployment.environment.name"=~"$env"}[1m${__range_ms}ms] @ (${__to} / 1000))) >= (${__from} / 1000)) <= (${__to} / 1000)) * 1000
```

Instances reporting:

```metricsql
count by ("deployment.environment.name", "service.name") (group by ("deployment.environment.name", "service.name", "service.instance.id") (present_over_time({"altinn.instance.start_time", "service.name"="studio-designer", "deployment.environment.name"=~"$env"}[1m])))
```
