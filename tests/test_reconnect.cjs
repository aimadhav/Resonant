const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(require('path').join(__dirname,'../web/live-ui.js'),'utf8');
const apiSource=source.slice(source.indexOf('async function api('),source.indexOf('function fail('));
async function run(error){
  const calls=[],meta={content:'old'};
  const context={TOKEN:'old',document:{querySelector:()=>meta},DOMParser:class{parseFromString(){return {querySelector:()=>({content:'new'})}}},log:()=>{},fetch:async(path,options)=>{
    calls.push({path,options});
    if(calls.length===1)return {status:403,ok:false,json:async()=>({error})};
    if(path==='/')return {ok:true,text:async()=>'<meta>'};
    return {status:200,ok:true,json:async()=>({success:true})};
  }};
  vm.createContext(context);vm.runInContext(apiSource,context);
  if(error==='Reload the app page before submitting'){
    const result=await context.api('/api/live/sessions',{method:'POST',body:'original'});
    assert(result.success);assert.equal(calls.length,3);assert.equal(calls[2].options.headers['X-App-Token'],'new');assert.equal(calls[2].options.body,'original');
  }else{await assert.rejects(()=>context.api('/api/live/sessions'),new RegExp(error));assert.equal(calls.length,1)}
}
(async()=>{await run('Reload the app page before submitting');await run('Permission denied');console.log('Reconnect checks passed: one safe retry after token rejection, no retry on other permission failures')})().catch(e=>{console.error(e);process.exitCode=1});
