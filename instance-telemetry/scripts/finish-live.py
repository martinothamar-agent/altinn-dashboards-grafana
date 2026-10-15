import json,time,subprocess,urllib.request,urllib.parse
from pathlib import Path
out=Path('/home/agent/code/.artifacts/studio-instance-telemetry/round2')
base='http://127.0.0.1:18080/internal/observability/metrics'
selector='{"altinn.instance.start_time", "service.name"=~"pdf3-(proxy|worker)", "deployment.environment.name"="local"}'
records=json.loads((out/'live-results.json').read_text())
def query(expr, end=None):
 params={'query':expr,'nocache':1}
 if end is not None: params['time']=end
 req=urllib.request.Request(base+'/api/v1/query?'+urllib.parse.urlencode(params),headers={'Authorization':'Bearer local-grafana-query-token-not-a-secret'})
 return json.load(urllib.request.urlopen(req))
def save(): (out/'live-results.json').write_text(json.dumps(records,indent=2)+'\n')
def snapshot(stage):
 end=time.time(); data=query('last_over_time('+selector+'[1m])'); records[stage]={'time':end,'metric':data,'pods':json.loads(subprocess.check_output(['kubectl','-n','runtime-pdf3','get','pods','-o','json']))};save();return data['data']['result']
def wait_for(stage, predicate, timeout=65):
 deadline=time.time()+timeout
 while True:
  rows=query('last_over_time('+selector+'[1m])')['data']['result']
  if predicate(rows):
   snapshot(stage);print(stage+': PASS ('+str(len(rows))+' reporting series)',flush=True);return
  if time.time()>deadline: raise AssertionError((stage,rows))
  time.sleep(3)
def kube(*args): subprocess.run(['kubectl','-n','runtime-pdf3',*args],check=True)
def rollout(name): kube('rollout','status','deployment/'+name,'--timeout=180s')
def counts(rows):
 return {name:sum(r['metric']['service.name']==name for r in rows) for name in ['pdf3-proxy','pdf3-worker']}
# Wait out the explicit reporting window of the replaced processes.
wait_for('scale',lambda rows:counts(rows)=={'pdf3-proxy':3,'pdf3-worker':2},timeout=110)
end=time.time(); start=records['from'];group='"deployment.environment.name", "service.version"'
deploy=f'min by ({group}) (min_over_time({selector}[90d] @ {end}))'
restart=f'min by ({group}, "service.name", "service.instance.id", "k8s.pod.uid") (min_over_time({selector}[{end-start}s] @ {end}))'
queries={'deploy':f'(({deploy} >= {start}) <= {end}) * 1000','restart':f'(({restart} >= {start}) <= {end}) * 1000','instances':f'count by ("deployment.environment.name", "service.name") (group by ("deployment.environment.name", "service.name", "service.instance.id") (present_over_time({selector}[1m])))','no_deploy_after_range_start':f'(({deploy} >= {records["restart_from"]}) <= {end}) * 1000'}
records['to']=end;records['queries']={name:{'expr':expr,'result':query(expr,end)} for name,expr in queries.items()};save()
rows=lambda name:records['queries'][name]['result']['data']['result']
assert len(rows('deploy'))==2,rows('deploy') # v1 and v2 across proxy/worker
assert not rows('no_deploy_after_range_start'),rows('no_deploy_after_range_start')
assert len(rows('restart'))==9,rows('restart') # proxy v1 2 + v2 2 + restart 2 + scale 1 + workers 2
assert {r['metric']['service.name']:int(r['value'][1]) for r in rows('instances')}=={'pdf3-proxy':3,'pdf3-worker':2},rows('instances')
records['assertions']={'deploy':'2 exact version dots across both components (v1 and v2)','restart':'9 unique process dots','range_start':'no deploy dots after the first v2 pods have gone, despite their v2 replacements starting inside range','instances':'3 proxy + 2 worker; no traffic required'};save();print(json.dumps(records['assertions'],indent=2),flush=True)
