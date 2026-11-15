/* Bounded, audio-clock-scheduled playback. No ad-generation await on the audio path. */
(function(root){
  function layout(episode){
    const items=[];
    for(const c of episode.chunks){
      const s=episode.slots.find(s=>Math.abs(s.cut_time-c.start)<1/44100);
      if(s)items.push({kind:'opportunity',slot:s});
      items.push({kind:'content',...c});
    }
    return items;
  }
  class PodcastPlayer{
    constructor(episode,{context,loadBuffer,onEvent=()=>{},lookahead=20,cacheLimit=8}={}){
      this.episode=episode;this.items=layout(episode);this.ctx=context;this.loader=loadBuffer;this.emit=onEvent;this.lookahead=lookahead;this.cacheLimit=cacheLimit;
      this.buffers=new Map();this.pending=new Map();this.nodes=new Set();this.records=[];this.committed=new Map();this.session={slots:[]};this.cursor=0;this.offset=0;this.running=false;this.epoch=0;this.pumping=false;this.timer=null;this.underruns=0;this.position=0;
    }
    setSession(session){this.session=session;this.prefetch();}
    async ensure(url){
      if(this.buffers.has(url)){const b=this.buffers.get(url);this.buffers.delete(url);this.buffers.set(url,b);return b;}
      if(this.pending.has(url))return this.pending.get(url);
      const promise=this.loader(url).then(b=>{this.buffers.set(url,b);while(this.buffers.size>this.cacheLimit)this.buffers.delete(this.buffers.keys().next().value);return b;}).finally(()=>this.pending.delete(url));
      this.pending.set(url,promise);return promise;
    }
    prefetch(){
      let count=0;
      for(let i=this.cursor;i<this.items.length&&count<4;i++){
        const item=this.items[i];
        if(item.kind==='content'){count++;this.ensure(item.url).catch(e=>this.emit({type:'fetch_error',message:String(e)}));}
        else{const ad=this.session.slots.find(s=>s.id===item.slot.id);if(ad?.status==='ready')this.ensure(ad.url).catch(()=>{});}
      }
    }
    async play(position=null){
      if(position!==null)this.seek(position);
      if(!this.ctx)throw Error('Audio context required');
      await this.ctx.resume();
      if(this.running)return;
      if(this.paused){this.paused=false;this.running=true;this.timer=setInterval(()=>this.pump(),250);return;}
      const epoch=this.epoch;this.emit({type:'buffering'});this.prefetch();
      const first=this.items.slice(this.cursor).filter(x=>x.kind==='content').slice(0,3);
      await Promise.all(first.map(x=>this.ensure(x.url)));
      if(epoch!==this.epoch)return;
      this.nextAt=this.ctx.currentTime+.15;this.running=true;this.timer=setInterval(()=>this.pump(),250);await this.pump();
    }
    async pause(){if(!this.running)return;this.position=this.current().sourceTime;await this.ctx.suspend();this.running=false;this.paused=true;clearInterval(this.timer);this.emit({type:'paused'});}
    seek(position){
      this.epoch++;clearInterval(this.timer);for(const node of this.nodes){try{node.stop();node.disconnect();}catch{}}this.nodes.clear();this.records=[];this.running=false;this.paused=false;this.pumping=false;this.committed.clear();
      const t=Math.max(0,Math.min(position,this.episode.duration-.001));let i=this.items.findIndex(x=>x.kind==='content'&&x.start+x.duration>t);
      if(i<0)i=this.items.length-1;this.offset=Math.max(0,t-this.items[i].start);
      if(this.offset===0&&i>0&&this.items[i-1].kind==='opportunity')i--;
      this.cursor=i;this.position=t;this.emit({type:'seek',sourceTime:t});
    }
    schedule(buffer,item,offset=0){
      const node=this.ctx.createBufferSource();node.buffer=buffer;node.connect(this.ctx.destination);
      if(this.nextAt<this.ctx.currentTime+.025){this.underruns++;this.emit({type:'underrun',count:this.underruns});this.nextAt=this.ctx.currentTime+.1;}
      const start=this.nextAt;const duration=buffer.duration-offset;
      const record={kind:item.kind,start,end:start+duration,sourceTime:item.kind==='ad'?item.cut_time:item.start+offset,slot:item.id||null,url:item.url};this.records.push(record);this.nodes.add(node);
      node.onended=()=>{this.nodes.delete(node);node.disconnect();};node.start(start,offset,duration);this.nextAt+=duration;
      this.emit({type:'scheduled',...record});
    }
    async pump(){
      if(!this.running||this.pumping)return;this.pumping=true;const epoch=this.epoch;let forceReturn=false;
      try{
        this.prefetch();
        while(this.cursor<this.items.length&&(this.nextAt-this.ctx.currentTime<this.lookahead||forceReturn)){
          const item=this.items[this.cursor];
          if(item.kind==='opportunity'){
            const ad=this.session.slots.find(s=>s.id===item.slot.id);const after=this.items[this.cursor+1];
            const buffer=ad?.status==='ready'?this.buffers.get(ad.url):null;const returnReady=after&&this.buffers.has(after.url);
            if(buffer&&returnReady){this.committed.set(item.slot.id,{status:'ad',asset:ad.asset_key});this.schedule(buffer,{kind:'ad',...ad});this.cursor++;forceReturn=true;this.emit({type:'ad_committed',slot:item.slot.id});continue;}
            // Give a prefetch time to finish, but never await it at the break
            if(this.nextAt-this.ctx.currentTime>3)break;
            this.committed.set(item.slot.id,{status:'skipped'});this.cursor++;this.emit({type:'ad_skipped',slot:item.slot.id,reason:'Ad or return audio not ready before deadline'});continue;
          }
          const buffer=await this.ensure(item.url);if(epoch!==this.epoch||!this.running)return;
          this.schedule(buffer,item,this.offset);this.offset=0;this.cursor++;forceReturn=false;
        }
        this.records=this.records.filter(r=>r.end>this.ctx.currentTime-5);
        if(this.cursor>=this.items.length&&this.ctx.currentTime>=this.nextAt){this.running=false;clearInterval(this.timer);this.emit({type:'ended'});}
      }catch(e){this.emit({type:'error',message:String(e)});}
      finally{if(epoch===this.epoch)this.pumping=false;}
    }
    current(){
      if(!this.ctx)return{sourceTime:this.position,kind:'content'};
      const r=this.records.find(r=>r.start<=this.ctx.currentTime&&r.end>this.ctx.currentTime);
      if(!r)return{sourceTime:this.position,kind:'buffering'};
      const sourceTime=r.kind==='ad'?r.sourceTime:Math.min(this.episode.duration,r.sourceTime+this.ctx.currentTime-r.start);this.position=sourceTime;
      return{sourceTime,kind:r.kind,slot:r.slot,bufferedSeconds:Math.max(0,this.nextAt-this.ctx.currentTime),decodedBuffers:this.buffers.size,underruns:this.underruns};
    }
    destroy(){this.seek(this.position);this.buffers.clear();}
  }
  const exports={PodcastPlayer,layout};if(typeof module!=='undefined'&&module.exports)module.exports=exports;else root.LivePodcast=exports;
})(typeof globalThis!=='undefined'?globalThis:this);
