"""Deferred worker tests use installed-style bundles and isolated Git repositories."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DeferredReflectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        subprocess.run(['git','init','-q',str(self.project)],check=True)
        (self.project / '.claude/memory').mkdir(parents=True)
        self.bundle = self.root / 'bundle'
        shutil.copytree(ROOT / 'plugins/codex/hooks',self.bundle)
        self.log = self.root / 'calls.jsonl'
        # Replace the LLM job, not the worker. Tests never invoke a real backend.
        (self.bundle / 'reflect.py').write_text('''import json,os,pathlib,sys,time
p=pathlib.Path(sys.argv[sys.argv.index('--transcript')+1])
with open(os.environ['CALLS'],'a') as f:f.write(json.dumps({'cwd':os.getcwd(),'project':os.environ.get('CLAUDE_PROJECT_DIR'),'text':p.read_text()})+'\\n')
time.sleep(float(os.environ.get('JOB_SLEEP','0')))
sys.exit(int(os.environ.get('JOB_EXIT','0')))
''')
        self.rollout = self.root / 'rollout-session.jsonl'
        self.write_rollout()
        self.env = {**os.environ,'REFLECT_BACKEND':'ollama','CALLS':str(self.log),'HARNESS_AUTO_REFLECT':'1'}
        self.env.pop('CLAUDE_PROJECT_DIR',None)
        self.env.pop('REFLECT_JOB',None)

    def write_rollout(self,originator='codex-tui',source='cli',age=3600):
        self.rollout.write_text(json.dumps({'type':'session_meta','payload':{'id':'session-1','cwd':str(self.project),'originator':originator,'source':source}})+'\n'+json.dumps({'type':'event_msg','payload':{'type':'user_message','message':'Remember this correction'}})+'\n')
        now=time.time()-age
        os.utime(self.rollout,(now,now))

    def worker(self,project=None,env=None):
        return subprocess.Popen([sys.executable,str(self.bundle/'codex_reflect_job.py'),'--project-dir',str(project or self.project),'--transcript',str(self.rollout)],env=env or self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)

    def finish(self,p):
        out,err=p.communicate(timeout=10)
        self.assertEqual(p.returncode,0,(out,err))

    def calls(self):
        return [json.loads(s) for s in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_concurrent_workers_only_run_backend_once_and_cleanup_snapshot(self):
        env={**self.env,'JOB_SLEEP':'0.2'}
        a=self.worker(env=env); b=self.worker(env=env)
        self.finish(a);self.finish(b);self.finish(self.worker())
        self.assertEqual(len(self.calls()),1)
        self.assertEqual(list((self.project/'.git').rglob('snapshot.jsonl')),[])
        self.assertEqual(len(list((self.project/'.git').rglob('done.json'))),1)

    def test_failure_retries_instead_of_burning_claim(self):
        self.finish(self.worker(env={**self.env,'JOB_EXIT':'1'}))
        self.assertEqual(list((self.project/'.git').rglob('done.json')),[])
        self.finish(self.worker())
        self.assertEqual(len(self.calls()),1)  # failed session backs off before retrying
        attempts=next((self.project/'.git').rglob('attempts.json'))
        attempts.write_text(json.dumps({'count':1,'at':time.time()-7200}))
        self.finish(self.worker())
        self.assertEqual(len(self.calls()),2)

    def test_recent_rollout_is_not_read_by_backend(self):
        self.write_rollout(age=0)
        self.finish(self.worker())
        self.assertEqual(self.calls(),[])

    def test_delegated_rollout_is_not_read_even_with_legacy_user_channel(self):
        self.write_rollout(originator='codex_exec',source='exec')
        self.finish(self.worker())
        self.assertEqual(self.calls(),[])

    def test_snapshot_drops_incomplete_record(self):
        with self.rollout.open('a') as stream:stream.write('{"unfinished":')
        now=time.time()-3600;os.utime(self.rollout,(now,now))
        self.finish(self.worker())
        self.assertNotIn('unfinished',self.calls()[0]['text'])

    def test_worktrees_share_claim_and_write_to_primary(self):
        subprocess.run(['git','-C',str(self.project),'-c','user.name=Test','-c','user.email=test@example.invalid','commit','--allow-empty','-qm','init'],check=True)
        linked=self.root/'linked'
        subprocess.run(['git','-C',str(self.project),'worktree','add','-q','-b','linked',str(linked)],check=True)
        self.finish(self.worker(project=linked,env={**self.env,'CLAUDE_PROJECT_DIR':str(linked)}))
        self.finish(self.worker())
        self.assertEqual(len(self.calls()),1)
        self.assertEqual(Path(self.calls()[0]['cwd']).resolve(),self.project.resolve())
        self.assertEqual(self.calls()[0]['project'],self.calls()[0]['cwd'])

    def test_codex_merge_and_prompt_do_not_launch_live_transcript(self):
        bindir=self.root/'bin';bindir.mkdir()
        gh=bindir/'gh';gh.write_text("#!/usr/bin/env python3\nimport json,sys\nprint('MERGED' if 'state' in sys.argv else json.dumps({'files':[{'path':'src/x.py'}],'labels':[],'commits':[]}))\n");gh.chmod(0o755)
        cache=self.project/'.claude/.cache/pr-merge-seen.json';cache.parent.mkdir(parents=True);cache.write_text('{"seen":[],"pending":[]}')
        for event,extra in [('PostToolUse',{'tool_name':'Bash','tool_input':{'command':'gh pr merge 2 --squash'}}),('UserPromptSubmit',{'prompt':'머지했어'})]:
            env={**self.env,'PATH':str(bindir)+os.pathsep+self.env['PATH'],'CLAUDE_PROJECT_DIR':str(self.project),'CODEX_HOME':str(self.root/'codex')}
            r=subprocess.run([sys.executable,str(self.bundle/'pr-merge-reflect.py')],input=json.dumps({'hook_event_name':event,'cwd':str(self.project),'transcript_path':str(self.rollout),**extra}),env=env,text=True,capture_output=True,timeout=10)
            self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(self.calls(),[])
        self.assertFalse((self.project/'.claude/.cache/reflect.log').exists())
        self.assertEqual(list((self.project/'.git').rglob('done.json')),[])

    def test_session_start_seeds_then_processes_once_across_adapters(self):
        sessions=self.root/'codex/sessions';sessions.mkdir(parents=True)
        target=sessions/self.rollout.name;shutil.move(self.rollout,target);self.rollout=target
        env={**self.env,'CODEX_HOME':str(self.root/'codex')}
        # Avoid the real gh entirely, including credentials/network.
        bindir=self.root/'bin';bindir.mkdir();gh=bindir/'gh';gh.write_text('#!/bin/sh\nexit 1\n');gh.chmod(0o755)
        env['PATH']=str(bindir)+os.pathsep+env['PATH']
        payload=json.dumps({'hook_event_name':'SessionStart','cwd':str(self.project),'session_id':'current'})
        def hook():
            subprocess.run([sys.executable,str(self.bundle/'pr-merge-reflect.py')],input=payload,env=env,text=True,capture_output=True,check=True,timeout=10)
        hook();self.assertEqual(self.calls(),[])
        cache=self.project/'.claude/.cache/codex-reflect-seen.json';self.assertIn('session-1',cache.read_text())
        # A new session after the historical baseline, now idle.
        text=self.rollout.read_text().replace('session-1','session-2');self.rollout.write_text(text)
        now=time.time()-3600;os.utime(self.rollout,(now,now))
        hook()
        deadline=time.monotonic()+5
        while time.monotonic()<deadline and not list((self.project/'.git').rglob('done.json')):time.sleep(.02)
        self.assertEqual(len(self.calls()),1)
        hook();self.assertEqual(len(self.calls()),1)

    def test_missing_helper_cannot_open_live_read_path(self):
        (self.bundle/'codex_reflect_job.py').unlink()
        self.test_codex_merge_and_prompt_do_not_launch_live_transcript()

    def test_no_attributed_input_is_skipped_not_completed(self):
        self.rollout.write_text(self.rollout.read_text().splitlines()[0]+'\n')
        now=time.time()-3600;os.utime(self.rollout,(now,now))
        self.finish(self.worker())
        self.assertEqual(self.calls(),[])
        self.assertEqual(len(list((self.project/'.git').rglob('skipped.json'))),1)
        self.assertEqual(list((self.project/'.git').rglob('done.json')),[])

    def test_missing_primary_memory_does_not_consume_attempt(self):
        (self.project/'.claude/memory').rmdir()
        self.finish(self.worker())
        self.assertEqual(self.calls(),[])
        self.assertEqual(list((self.project/'.git').rglob('attempts.json')),[])

    def test_exhausted_attempts_do_not_call_backend(self):
        directory=self.project/'.git/agent-harness/codex-reflect-jobs'/hashlib.sha256(b'session-1').hexdigest()
        directory.mkdir(parents=True)
        (directory/'attempts.json').write_text(json.dumps({'count':3,'at':time.time()-86400}))
        self.finish(self.worker())
        self.assertEqual(self.calls(),[])

    def test_primary_drafts_announced_from_linked_worktree(self):
        subprocess.run(['git','-C',str(self.project),'-c','user.name=Test','-c','user.email=test@example.invalid','commit','--allow-empty','-qm','init'],check=True)
        linked=self.root/'linked'
        subprocess.run(['git','-C',str(self.project),'worktree','add','-q','-b','linked',str(linked)],check=True)
        (linked/'.claude/memory').mkdir(parents=True)
        pending=self.project/'.claude/memory/_pending';pending.mkdir();(pending/'draft.md').write_text('draft')
        bindir=self.root/'bin';bindir.mkdir();gh=bindir/'gh';gh.write_text('#!/bin/sh\nexit 1\n');gh.chmod(0o755)
        env={**self.env,'HARNESS_AUTO_REFLECT':'0','PATH':str(bindir)+os.pathsep+self.env['PATH']}
        r=subprocess.run([sys.executable,str(self.bundle/'pr-merge-reflect.py')],input=json.dumps({'hook_event_name':'SessionStart','cwd':str(linked)}),env=env,text=True,capture_output=True,check=True)
        self.assertIn(str(self.project),r.stdout)
        self.assertIn('primary project path',r.stdout)

    def test_bare_repository_does_not_choose_arbitrary_linked_worktree(self):
        subprocess.run(['git','-C',str(self.project),'-c','user.name=Test','-c','user.email=test@example.invalid','commit','--allow-empty','-qm','init'],check=True)
        bare=self.root/'bare.git';linked=self.root/'linked'
        subprocess.run(['git','clone','--bare','-q',str(self.project),str(bare)],check=True)
        subprocess.run(['git','-C',str(bare),'worktree','add','-q',str(linked)],check=True)
        (linked/'.claude/memory').mkdir(parents=True)
        self.finish(self.worker(project=linked))
        self.assertEqual(self.calls(),[])

    def test_failed_new_sessions_do_not_starve_older_session(self):
        sessions=self.root/'codex/sessions';sessions.mkdir(parents=True)
        cache=self.project/'.claude/.cache/codex-reflect-seen.json';cache.parent.mkdir(parents=True);cache.write_text('[]')
        for i in range(4):
            sid='candidate-'+str(i)
            file=sessions/('rollout-'+sid+'.jsonl')
            file.write_text(self.rollout.read_text().replace('session-1',sid))
            when=time.time()-3600-i*60;os.utime(file,(when,when))
            if i<3:
                directory=self.project/'.git/agent-harness/codex-reflect-jobs'/hashlib.sha256(sid.encode()).hexdigest()
                directory.mkdir(parents=True)
                (directory/'attempts.json').write_text(json.dumps({'count':3,'at':time.time()}))
        bindir=self.root/'bin';bindir.mkdir();gh=bindir/'gh';gh.write_text('#!/bin/sh\nexit 1\n');gh.chmod(0o755)
        env={**self.env,'PATH':str(bindir)+os.pathsep+self.env['PATH'],'CODEX_HOME':str(self.root/'codex')}
        subprocess.run([sys.executable,str(self.bundle/'pr-merge-reflect.py')],input=json.dumps({'hook_event_name':'SessionStart','cwd':str(self.project),'session_id':'current'}),env=env,text=True,capture_output=True,check=True,timeout=10)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline and not list((self.project/'.git').rglob('done.json')):time.sleep(.02)
        self.assertEqual(len(self.calls()),1)
        self.assertIn('candidate-3',self.calls()[0]['text'])
