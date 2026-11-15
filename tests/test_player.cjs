const assert=require('node:assert/strict');const {PodcastPlayer,layout}=require('../web/player.js');
const episode={duration:5,chunks:[{index:0,start:0,duration:2,url:'a'},{index:1,start:2,duration:3,url:'b'}],slots:[{id:'s',cut_time:2}]};
function context(){return{currentTime:0,destination:{},started:[],async resume(){},async suspend(){},createBufferSource(){const ctx=this;return{connect(){},disconnect(){},stop(){},start(...args){ctx.started.push(args)}}}}}
async function setup(adReady=true){const ctx=context(),events=[];const p=new PodcastPlayer(episode,{context:ctx,loadBuffer:async u=>({duration:{a:2,b:3,ad:1}[u]}),onEvent:e=>events.push(e),lookahead:10});p.session={slots:[{id:'s',cut_time:2,status:adReady?'ready':'pending',url:'ad'}]};await p.ensure('a');await p.ensure('b');if(adReady)await p.ensure('ad');p.running=true;p.nextAt=.15;await p.pump();return{p,ctx,events}}
(async()=>{
 assert.equal(layout(episode).length,3);
 let {p,ctx,events}=await setup();assert.equal(ctx.started.length,3);assert.equal(ctx.started[1][0],ctx.started[0][0]+2);assert.equal(ctx.started[2][0],ctx.started[1][0]+1);assert.equal(p.underruns,0);assert.ok(events.some(e=>e.type==='ad_committed'));
 ({p,ctx,events}=await setup(false));assert.equal(ctx.started.length,2);assert.equal(ctx.started[1][0],ctx.started[0][0]+2);assert.ok(events.some(e=>e.type==='ad_skipped'));
 ({p,ctx}=await setup());ctx.currentTime=2.5;assert.equal(p.current().kind,'ad');assert.equal(p.current().sourceTime,2);ctx.currentTime=3.5;assert.ok(Math.abs(p.current().sourceTime-2.35)<1e-8);
 p.seek(1);assert.equal(p.offset,1);assert.equal(p.records.length,0);assert.equal(p.committed.size,0);
 const bound=new PodcastPlayer(episode,{context:context(),loadBuffer:async()=>({duration:1}),cacheLimit:3});for(let i=0;i<9;i++)await bound.ensure('url'+i);assert.equal(bound.buffers.size,3);
 console.log('Player checks passed: exact scheduling adjacency, late-ad fallback, dual timeline, seek reset, bounded decoded cache');
})().catch(e=>{console.error(e);process.exitCode=1});
