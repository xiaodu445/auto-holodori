import shutil,subprocess,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class ScoreViewTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node not installed')
    def test_timeline_draws_zoom_and_subdivision_lines_without_browser(self):
        js=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(process.argv[1],'utf8'),start=html.indexOf('function timeline(){');
const code=html.slice(start,html.indexOf('\nfunction ',start+1));
const colours=[],texts=[],ctx=new Proxy({}, {get:(o,k)=>o[k]||((...a)=>{if(k==='fillText')texts.push(a[0])}),set:(o,k,v)=>{o[k]=v;if(k==='strokeStyle')colours.push(v);return true}});
const controls={timeline:{width:1200,style:{},getContext:()=>ctx},scoreScroll:{clientWidth:800,scrollLeft:0},scoreZoom:{value:'4'},scoreLines:{checked:true},scoreFollow:{checked:false},scoreCandidate:{value:'auto',options:[{value:'auto'}],replaceChildren(...args){this.options=args}},scoreBpm:{value:''},scorePhase:{value:''},scoreInfo:{},inputSource:{value:'recorded'}};
const sandbox={$:id=>controls[id],begin:0,end:4,current:0,keys:['s','d','f','j','k','l'],
frames:[{time:1,music_clock:{epoch:0,step_ms:125,bar_ambiguous:true,candidates:[{bar_ticks:16,offset_ticks:0,next_bar:2,bpm_candidate:120}]} }],
DATA:{input_edges:[],recorded_input_edges:[{key:'d',time:.1,down:true}]},document:{createElement:()=>({})}};
vm.createContext(sandbox);vm.runInContext(code+';timeline()',sandbox);
assert.equal(controls.timeline.width,3600);assert.equal(controls.timeline.height,240);
for(const colour of ['#ffbf69','#357c91','#263847'])assert(colours.includes(colour));
assert(texts.some(t=>String(t).includes('候选小节')));assert(controls.scoreInfo.textContent.includes('未确认'));
controls.scoreBpm.value='150';controls.scorePhase.value='.25';vm.runInContext('timeline()',sandbox);
assert(controls.scoreInfo.textContent.includes('150.00'));assert(controls.scoreInfo.textContent.includes('0.250'));
'''
        result=subprocess.run([shutil.which('node'),'-e',js,str(ROOT/'tools/rhythm_review.html')],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

if __name__=='__main__':unittest.main()
