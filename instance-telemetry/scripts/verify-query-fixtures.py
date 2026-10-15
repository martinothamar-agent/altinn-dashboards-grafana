#!/usr/bin/env python3
"""Synthetic MetricsQL fixture; never writes the real instance metric."""
import json
from pathlib import Path
import time
import urllib.parse
import urllib.request

BASE = 'http://127.0.0.1:18428'
OUT = Path('/home/agent/code/.artifacts/studio-instance-telemetry/round2')
OUT.mkdir(parents=True, exist_ok=True)
END = int(time.time()) - 120
START = END - 600
RUN = str(END)
METRIC = 'altinn.instance.query_fixture'
samples = []
instances = []

def add(version, instance, start, first, last, duplicate=False, timestamps=None, pod=None,
        service='fixture-proxy'):
    labels = {'service.name': service, 'service.version': version,
              'deployment.environment.name': 'fixture', 'service.instance.id': instance,
              'k8s.pod.uid': pod or 'pod-' + instance, 'fixture.run': RUN}
    instances.append(dict(version=version, instance=instance, service=service, start=start,
                          first=first, last=last, duplicate=duplicate))
    for source in (['a', 'b'] if duplicate else ['a']):
        full = dict(labels, **{'fixture.exporter': source})
        # JSON import preserves dotted metric/label names and exact millisecond sample times.
        stamps = timestamps if timestamps is not None else list(range(first, last + 1, 15))
        samples.append({'metric': dict(full, __name__=METRIC),
                        'values': [start] * len(stamps),
                        'timestamps': [int(t * 1000) for t in stamps]})

# The first old pod has disappeared before the dashboard range. A scale-up and
# rollback of that old version inside the range must not look like new versions.
add('old', 'old-first', START-300, START-300, START-60)
add('old', 'old-scaleup', START+60, START+60, END-15)
add('old', 'old-rollback', START+420, START+420, END-15)
add('new', 'new-first', START+90, START+90, START+210, pod='same-pod-restarted')
add('new', 'new-restart', START+240, START+240, END-15, duplicate=True, pod='same-pod-restarted')
add('new', 'new-scaleup', START+360, START+360, END-15)
add('new', 'worker-new', START+100, START+100, END-15, service='fixture-worker')
add('gapped', 'gapped-first', START+180, START+180, END-15,
    timestamps=[START+180, START+195, END-30, END-15])
add('boundary-before', 'boundary-before', START-0.001, START, END-15)
add('boundary-start', 'boundary-start', START, START, END-15)
add('boundary-start-only', 'boundary-start-only', START, START, START, timestamps=[START])
add('boundary-end', 'boundary-end', END, END, END, timestamps=[END])
add('boundary-after', 'boundary-after', END+1, END+1, END+1, timestamps=[END+1])
body = '\n'.join(json.dumps(x) for x in samples).encode()
req = urllib.request.Request(BASE+'/api/v1/import', data=body,
                             headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(req) as response:
    assert response.status == 204, response.status
(OUT/'query-fixture-input.jsonl').write_bytes(body)

selector = '{"'+METRIC+'", "fixture.run"="'+RUN+'"}'
# VictoriaMetrics acknowledges import before its insert buffer flushes.
for attempt in range(20):
    params = urllib.parse.urlencode({'query': f'count_over_time({selector}[90d])', 'time': END, 'nocache': 1})
    visible = json.load(urllib.request.urlopen(BASE+'/api/v1/query?'+params))
    if len(visible['data']['result']) == len(samples)-1:  # after-range sample is excluded
        break
    time.sleep(1)
else:
    raise AssertionError(('import did not become queryable', visible))
group = '"deployment.environment.name", "service.version"'
instance_group = group+', "service.name", "service.instance.id", "k8s.pod.uid"'
deploy_value = f'min by ({group}) (min_over_time({selector}[90d] @ {END}))'
instance_value = f'min by ({instance_group}) (min_over_time({selector}[1m600000ms] @ ({END*1000} / 1000)))'
queries = {
    'deploy': f'(({deploy_value} >= {START}) <= {END}) * 1000',
    'restart': f'(({instance_value} >= {START}) <= {END}) * 1000',
    'instances': f'count by ("deployment.environment.name", "service.name") (group by ("deployment.environment.name", "service.name", "service.instance.id") (present_over_time({selector}[1m])))',
    'false_deploy_with_range_only': f'((min by ({group}) (min_over_time({selector}[600s] @ {END})) >= {START}) <= {END}) * 1000',
    'deploy_fractional_bounds': f'(({deploy_value} >= ({START*1000+1} / 1000)) <= ({END*1000-1} / 1000)) * 1000',
    'restart_strict_range': f'((min by ({instance_group}) (min_over_time({selector}[600000ms] @ ({END*1000} / 1000))) >= ({START*1000} / 1000)) <= ({END*1000} / 1000)) * 1000',
}

def query(name, path, params):
    data = json.load(urllib.request.urlopen(BASE+path+'?'+urllib.parse.urlencode(params)))
    assert data['status'] == 'success', data
    return {'query': queries[name], 'request': params, 'response': data}

results = {'start': START, 'end': END, 'run': RUN, 'instances': instances, 'queries': {}}
for name, expr in queries.items():
    results['queries'][name] = query(name, '/api/v1/query',
                                     {'query': expr, 'time': END, 'step': '15s', 'nocache': 1})
    if name in ('deploy', 'restart'):
        results['queries'][name+'_range'] = query(name, '/api/v1/query_range',
            {'query': expr, 'start': START, 'end': END, 'step': '60s', 'nocache': 1})
results['queries']['instances_during_gap'] = query('instances', '/api/v1/query',
    {'query': queries['instances'], 'time': START+300, 'step': '15s', 'nocache': 1})

def instant(name):
    return results['queries'][name]['response']['data']['result']

actual_deploy = {r['metric']['service.version']: float(r['value'][1]) for r in instant('deploy')}
expected_deploy = {'new': (START+90)*1000, 'gapped': (START+180)*1000,
                   'boundary-start': START*1000, 'boundary-start-only': START*1000,
                   'boundary-end': END*1000}
assert actual_deploy == expected_deploy, (actual_deploy, expected_deploy)
actual_restart = {r['metric']['service.instance.id']: float(r['value'][1]) for r in instant('restart')}
expected_restart = {i['instance']: i['start']*1000 for i in instances if START <= i['start'] <= END}
assert actual_restart == expected_restart, (actual_restart, expected_restart)
assert 'boundary-start-only' not in {r['metric']['service.instance.id'] for r in instant('restart_strict_range')}, instant('restart_strict_range')
assert {r['metric']['service.version'] for r in instant('deploy_fractional_bounds')} == {'new', 'gapped'}, instant('deploy_fractional_bounds')
# 8 proxy and 1 worker recently reporting process IDs, despite 10 source series.
counts = {r['metric']['service.name']: int(r['value'][1]) for r in instant('instances')}
assert counts == {'fixture-proxy': 8, 'fixture-worker': 1}, counts
gap_counts = {r['metric']['service.name']: int(r['value'][1]) for r in instant('instances_during_gap')}
assert gap_counts == {'fixture-proxy': 4, 'fixture-worker': 1}, gap_counts
# Grafana's range annotation path sees identical value timestamps each step;
# processEvents collapses each returned series to a single point annotation.
for name in ('deploy', 'restart'):
    for result in results['queries'][name+'_range']['response']['data']['result']:
        assert len(set(value for _, value in result['values'])) == 1, result
results['assertions'] = {
    'deploy': '5 exact dots across proxy and worker sharing a version; no old-version scale-up/rollback or pre-range boundary dot',
    'restart': f'{len(expected_restart)} exact process dots; same-pod restarts distinct by process instance ID; duplicated resource source deduplicated',
    'instances': '8 proxy + 1 worker unique processes with samples within 1m; proxy falls to 4 during gap and returns to 8',
    'range': 'fixed @ end emits one distinct timestamp per series across all evaluation steps',
    'bounds': 'inclusive from/to; 1ms before and 1s after excluded; fractional-bound expressions filter exact 1ms offsets; extra 1m restart lookback includes sole sample exactly at from',
}
(OUT/'query-fixture-results.json').write_text(json.dumps(results, indent=2)+'\n')
print(json.dumps({**results['assertions'], 'start': START, 'end': END,
                  'deploy': actual_deploy, 'restart': actual_restart}, indent=2))
