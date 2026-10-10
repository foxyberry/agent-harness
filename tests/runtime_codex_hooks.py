"""Optional real Codex runtime smoke check, with local model/backend fixtures only.

Run after ./build.sh: python3 tests/runtime_codex_hooks.py
Uses a fresh CODEX_HOME, marketplace and Git project; never touches user installations.
The one-off trust bypass is restricted to this copied, inspected fixture configuration.
The untrusted control must skip hooks. Interactive trust UI is not tested.
Artifacts are retained in a temporary directory for inspection.
"""

import json, os, pathlib, subprocess, tempfile, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

def main():
    root=pathlib.Path(tempfile.mkdtemp(prefix='issue85-lifecycle-'))
    project=root/'project';project.mkdir()
    home=root/'codex';home.mkdir()
    probe=root/'trace.py'
    probe.write_text('import json,sys,pathlib\nd=json.load(sys.stdin)\np=d.get("transcript_path")\nd["tail"]=pathlib.Path(p).read_text()[-4000:] if p and pathlib.Path(p).exists() else None\nwith open('+repr(str(root/'trace.jsonl'))+',"a") as f:f.write(json.dumps(d)+"\\n")\n')
    config={'hooks':{event:[{'hooks':[{'type':'command','command':'python3 '+str(probe),'timeout':3}]}] for event in ['SessionStart','SessionEnd','Stop']}}
    (home/'hooks.json').write_text(json.dumps(config))
    (project/'.claude/memory').mkdir(parents=True)
    subprocess.run(['git','init','-q',str(project)],check=True)
    class Handler(BaseHTTPRequestHandler):
     def log_message(self,*a):pass
     def do_POST(self):
      self.rfile.read(int(self.headers.get('Content-Length','0')))
      item={'id':'msg_probe','type':'message','role':'assistant','content':[{'type':'output_text','text':'PROBE_DONE','annotations':[]}]}
      response={'id':'resp_probe','object':'response','status':'completed','output':[item],'usage':{'input_tokens':1,'output_tokens':1,'total_tokens':2}}
      events=[{'type':'response.created','response':{'id':'resp_probe','object':'response','status':'in_progress','output':[]}}, {'type':'response.output_item.added','output_index':0,'item':{**item,'content':[]}}, {'type':'response.output_text.delta','item_id':'msg_probe','output_index':0,'content_index':0,'delta':'PROBE_DONE'}, {'type':'response.output_item.done','output_index':0,'item':item}, {'type':'response.completed','response':response}]
      data=''.join('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n' for e in events).encode()
      self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    server=HTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    (home/'config.toml').write_text('model = "probe"\nmodel_provider = "fixture"\n[model_providers.fixture]\nname = "Fixture"\nbase_url = "http://127.0.0.1:'+str(server.server_port)+'/v1"\nwire_api = "responses"\nrequires_openai_auth = false\n')
    base=['codex','exec','--skip-git-repo-check','--json','-C',str(project),'Respond PROBE_DONE without tools.']
    env={key:os.environ[key] for key in ('PATH','HOME','LANG','TMPDIR') if key in os.environ}
    env.update(CODEX_HOME=str(home),GIT_CONFIG_GLOBAL=str(root/'empty-gitconfig'),GIT_CONFIG_NOSYSTEM='1')
    (root/'empty-gitconfig').touch()
    env['HARNESS_HOOK_TRACE']=str(root/'harness-trace.jsonl')
    # Leave HARNESS_AUTO_REFLECT unset to exercise default-on installed behavior.
    env['REFLECT_BACKEND']='claude'
    bindir=root/'bin';bindir.mkdir()
    (bindir/'gh').write_text('#!/bin/sh\nexit 1\n');(bindir/'gh').chmod(0o755)
    (bindir/'claude').write_text('#!/usr/bin/env python3\nimport pathlib\np=pathlib.Path('+repr(str(root/'backend-calls'))+')\nwith p.open("a") as f:f.write("called\\n")\nprint("````\\n---\\nname: probe-lesson\\ndescription: fixture only\\ntype: feedback\\n---\\nFixture draft.\\n````")\n');(bindir/'claude').chmod(0o755)
    env['PATH']=str(bindir)+os.pathsep+env['PATH']
    source=root/'marketplace'
    (source/'.agents/plugins').mkdir(parents=True)
    import shutil,time
    repo=pathlib.Path(__file__).resolve().parents[1]
    shutil.copy2(repo/'.agents/plugins/marketplace.json',source/'.agents/plugins/marketplace.json')
    shutil.copytree(repo/'plugins/codex',source/'plugins/codex')
    for command in [['codex','plugin','marketplace','add',str(source)],['codex','plugin','add','agent-harness@foxyberry']]:
     r=subprocess.run(command,env=env,capture_output=True,text=True,timeout=20)
     (root/('install-'+command[2]+'.out')).write_text(r.stdout+'\n'+r.stderr)
     if r.returncode:raise RuntimeError(r.stderr)
    sessions=home/'sessions';sessions.mkdir(exist_ok=True)
    def fixture(sid):
     p=sessions/('rollout-'+sid+'.jsonl')
     p.write_text(json.dumps({'type':'session_meta','payload':{'id':sid,'cwd':str(project),'originator':'codex-tui','source':'cli'}})+'\n'+json.dumps({'type':'event_msg','payload':{'type':'user_message','message':'Remember to preserve attribution.'}})+'\n')
     now=time.time()-3600;os.utime(p,(now,now))
    fixture('historical')
    for mode in ['untrusted','reviewed-fixture-bypass','new-idle-session','repeat']:
     if mode=='new-idle-session':fixture('new-idle')
     command=base.copy()
     if mode!='untrusted':command.insert(2,'--dangerously-bypass-hook-trust')
     try:
      r=subprocess.run(command,env=env,text=True,capture_output=True,timeout=20)
      (root/(mode+'.out')).write_text(r.stdout+'\n'+r.stderr)
      assert r.returncode == 0, (mode, r.stderr)
      if mode == 'untrusted':
       assert not (root/'trace.jsonl').exists(), 'untrusted user hook unexpectedly ran'
       assert not (root/'harness-trace.jsonl').exists(), 'untrusted plugin unexpectedly ran'
      else:
       assert (root/'harness-trace.jsonl').exists(), 'installed plugin hooks were skipped'
      if mode == 'reviewed-fixture-bypass':
       assert not (root/'backend-calls').exists(), 'historical seeding launched a job'
      if mode == 'new-idle-session':
       deadline=time.monotonic()+5
       while time.monotonic()<deadline and not list((project/'.git').rglob('done.json')):time.sleep(.05)
       assert list((project/'.git').rglob('done.json')), 'installed worker did not complete'
      print(mode,'passed')
     except subprocess.TimeoutExpired as e:
      (root/(mode+'.out')).write_bytes((e.stdout or b'')+(e.stderr or b''));raise AssertionError((mode,'timed out')) from e
    deadline=time.monotonic()+5
    while time.monotonic()<deadline and not (root/'backend-calls').exists():time.sleep(.05)
    assert (root/'backend-calls').read_text().splitlines() == ['called'], 'duplicate or missing backend call'
    assert (project/'.claude/memory/_pending/probe-lesson.md').exists()
    for line in (root/'trace.jsonl').read_text().splitlines():
     d=json.loads(line)
     meta=json.loads(pathlib.Path(d['transcript_path']).read_text().splitlines()[0])
     assert d['session_id']==meta['payload']['id']
    assert any(json.loads(line)['hook_event_name']=='SessionEnd' for line in (root/'trace.jsonl').read_text().splitlines())
    print('One backend call, one draft, session IDs matched, SessionEnd observed.')
    print('Drafts:',list((project/'.claude/memory').rglob('*.md')))
    print('Artifacts:',root)
    server.shutdown()

if __name__ == "__main__":
    main()
