#!/usr/bin/env python3
"""Read synthetic fixture queries through the real Grafana datasource backend."""
import json
from pathlib import Path
import urllib.request

OUT = Path('/home/agent/code/.artifacts/studio-instance-telemetry/round2')
fixture = json.loads((OUT/'query-fixture-results.json').read_text())
results = {}
for name in ('deploy', 'restart'):
    for instant in (True, False):
        body = {'from': str(fixture['start']*1000), 'to': str(fixture['end']*1000),
                'queries': [{'refId': 'Anno', 'datasource': {'type': 'prometheus', 'uid': 'altinn-studio-metrics'},
                             'expr': fixture['queries'][name]['query'], 'instant': instant,
                             'range': not instant, 'format': 'time_series',
                             'intervalMs': 15000, 'maxDataPoints': 1456}]}
        request = urllib.request.Request('http://127.0.0.1:13000/api/ds/query',
            data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        response = json.load(urllib.request.urlopen(request))
        frames = response['results']['Anno']['frames']
        expected = 5 if name == 'deploy' else 10
        assert len(frames) == expected, (name, len(frames))
        for frame in frames:
            assert [f['type'] for f in frame['schema']['fields']] == ['time', 'number'], frame
            values = frame['data']['values'][1]
            assert len(set(values)) == 1, values
            if instant:
                assert len(values) == 1, values
            assert fixture['start']*1000 <= values[0] <= fixture['end']*1000, values
        mode = 'instant' if instant else 'range'
        results[name+'_'+mode] = {'request': body, 'response': response}
        print(f'{name} {mode}: {len(frames)} expected Time/Value frames; one distinct timestamp each')
(OUT/'grafana-annotation-frames.json').write_text(json.dumps(results, indent=2)+'\n')
