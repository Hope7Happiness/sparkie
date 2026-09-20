"""Exercise the actual self-contained Zoom presentation JavaScript offline."""
import json
import shutil
import subprocess
import unittest

from sparkie.present_page import present_html


@unittest.skipUnless(shutil.which('node'), 'Node is required for presentation JavaScript checks')
class PresentPageTests(unittest.TestCase):
    def test_selection_progress_refresh_clear_and_stale_hydration(self):
        script = present_html('ws_123abc').split('<script>')[1].split('</script>')[0]
        result = subprocess.run(['node', '-e', NODE_TEST], input=json.dumps(script),
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


NODE_TEST = r'''
const vm=require('node:vm'), fs=require('node:fs'), assert=require('node:assert/strict');
const elements=new Map();
const element=id=>{if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',hidden:false});return elements.get(id)};
const sockets=[];
let snap={workspace:{title:'Synthetic Zoom meeting'},state:{active_artifact_id:'old'},seq:1,
          tasks:[{task_id:'work',status:'running',artifact_title:'Weather chart',instruction:'PRIVATE PROMPT'}],artifacts:[{artifact_id:'new'}]};
const artifacts={old:{title:'Report',summary:'Wrapper',content:{markdown:'# Report\n\nActual document'}},
                 new:{title:'Chart',content:{image:'data:image/png;base64,AAAA'}}};
let delayed=null;
const context=vm.createContext({console,location:{origin:'http://fixture',host:'fixture',protocol:'http:'},
 document:{getElementById:element},setTimeout:()=>{},
 WebSocket:class {constructor(){sockets.push(this)}},
 fetch:async url=>{
  if(url.includes('/api/workspaces/'))return {ok:true,json:async()=>snap};
  if(url.endsWith('/late'))return new Promise(resolve=>{delayed=resolve});
  return {ok:true,json:async()=>artifacts[url.split('/').at(-1)]};
 }});
vm.runInContext(JSON.parse(fs.readFileSync(0,'utf8')),context);
const run=code=>vm.runInContext(code,context);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const event=msg=>sockets.at(-1).onmessage({data:JSON.stringify(msg)});
(async()=>{
 await run('syncSnapshot()');await tick();
 assert.equal(element('meeting').textContent,'Synthetic Zoom meeting');
 assert.equal(element('stage').innerHTML.split('Report').length-1,1);
 assert.ok(!element('stage').innerHTML.includes('Wrapper'));
 assert.ok(element('generation').innerHTML.includes('Weather chart'));
 assert.ok(!element('generation').innerHTML.includes('PRIVATE PROMPT'));
 event({type:'artifact.ready',artifact_id:'new'});await tick();
 assert.ok(element('stage').innerHTML.includes('Actual document'));
 event({type:'artifact.present',artifact_id:'new'});await tick();
 assert.ok(element('stage').innerHTML.includes('<img'));
 event({type:'artifact.cleared'});
 assert.ok(element('stage').innerHTML.includes('No artifact selected'));
 snap.state.active_artifact_id=null;
 await run('syncSnapshot()');await tick();
 assert.ok(element('stage').innerHTML.includes('No artifact selected'),'refresh must not choose newest artifact');
 event({type:'artifact.present',artifact_id:'late'});await tick();
 event({type:'artifact.cleared'});
 delayed({ok:true,json:async()=>artifacts.old});await tick();
 assert.ok(element('stage').innerHTML.includes('No artifact selected'),'late hydration must not undo hide');
 event({type:'task.updated',task_id:'work',status:'completed'});
 assert.equal(element('generation').hidden,true);
 event({type:'task.updated',task_id:'legacy',status:'running',instruction:'SECRET EXECUTION PROMPT'});
 assert.ok(element('generation').innerHTML.includes('Task output'));
 assert.ok(!element('generation').innerHTML.includes('SECRET'));
 snap.tasks=[];
 event({type:'workspace.reset'});await tick();
 assert.equal(element('generation').hidden,true);
 assert.ok(element('stage').innerHTML.includes('No artifact selected'));
 assert.equal(run("safeMedia('javascript:alert(1)')"),'');
 assert.equal(run("safeMedia('data:text/html,unsafe')"),'');
 console.log('PASS presentation selection, unwrapped Markdown, image rendering, named progress, refresh, hide, reset, stale fetch and URL restrictions');
})().catch(error=>{console.error(error);process.exitCode=1});
'''
