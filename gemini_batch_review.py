"""Five-context batches with the user's selected Gemini models and key failover."""
import argparse
import collections
import copy
import hashlib
import json
from pathlib import Path
import re
import time
import unicodedata
import urllib.error
import urllib.request

from gemini_review import load_env,select_packets,validate_review,write_json,make_report,SCHEMA,INSTRUCTIONS

VERSION='boundary-batch-v2'
PROMPT=INSTRUCTIONS.replace('"first dopamine"','"the first item in a list"')+'''
Evaluate each packet independently at its own CUT marker. Never transfer a judgment or evidence from one packet to another. Return exactly one review for each supplied slot_id inside the reviews array. Do not rank candidates. For an accept decision, support your explanation using both sides of the cut when possible. Quote one contiguous source excerpt per evidence item, with its exact sentence ID. If you cannot establish completion, choose uncertain rather than inventing evidence.'''
BATCH_SCHEMA={'type':'OBJECT','properties':{'reviews':{'type':'ARRAY','items':SCHEMA}},'required':['reviews']}


def normalize(text):
    return ' '.join(unicodedata.normalize('NFKC',text).translate(str.maketrans({'’':"'",'‘':"'",'“':'\"','”':'\"','–':'-','—':'-'})).split()).casefold()


def verify(review,packet):
    review=copy.deepcopy(review)
    sentences=packet['before_context']+packet['after_context']
    lookup={s['id']:s['text'] for s in sentences}
    repairs=[]
    for item in review.get('evidence',[]):
        quote=item.get('quote','')
        if not isinstance(quote,str) or not quote.strip():continue
        sid=item.get('sentence_id')
        if sid in lookup and normalize(quote) in normalize(lookup[sid]):continue
        matches=[s['id'] for s in sentences if normalize(quote) in normalize(s['text'])]
        if len(matches)==1:
            repairs.append({'provided_sentence_id':sid,'verified_sentence_id':matches[0]})
            item['sentence_id']=matches[0]
    result=validate_review(review,packet)
    if repairs:result['citation_id_repairs']=repairs
    return result


class Reviewer:
    def __init__(self,env_path,out):
        self.env_path=env_path;self.out=out;self.disabled=set();self.disabled_models=set();self.events=[];self.last_request=0

    def routes(self):
        env=load_env(self.env_path)
        primary=env.get('GEMINI_MODEL','gemini-3.5-flash-lite')
        backup=env.get('GEMINI_BACKUP_MODEL','gemini-3.1-flash-lite')
        if {primary,backup}-{'gemini-3.5-flash-lite','gemini-3.1-flash-lite'}:
            raise ValueError('This run is restricted to the two Gemini models requested by the user.')
        keys=[('primary',env.get('GEMINI_API_KEY','')),('backup',env.get('GEMINI_BACKUP_API_KEY',''))]
        unique=[];seen=set()
        for label,key in keys:
            if key and key not in seen:unique.append((label,key));seen.add(key)
        return [(model,label,key) for model in [primary,backup] for label,key in unique]

    def call(self,packets,batch_name,repair=False):
        routes=self.routes()
        if not routes:raise RuntimeError('No Gemini API key is configured in .env.')
        errors=[]
        for model,label,key in routes:
            identity=(model,hashlib.sha256(key.encode()).hexdigest())
            if identity in self.disabled or model in self.disabled_models:continue
            for attempt in range(2):
                if getattr(self,'isolated',False) and len(self.events)>=self.max_calls:raise RuntimeError('API request cap reached')
                elapsed=time.perf_counter()-self.last_request
                if elapsed<8:time.sleep(8-elapsed)
                self.last_request=time.perf_counter();began=time.perf_counter()
                data={'packets':packets}
                if repair:data['format_reminder']='Earlier response could not be verified. Copy contiguous excerpts exactly from their individual sentence records. Do not paraphrase quotes or omit slots.'
                body={'systemInstruction':{'parts':[{'text':getattr(self,'prompt_override',PROMPT)}]},
                    'contents':[{'role':'user','parts':[{'text':json.dumps(data,ensure_ascii=False)}]}],
                    'generationConfig':{'responseMimeType':'application/json','responseSchema':getattr(self,'schema_override',BATCH_SCHEMA),
                        'maxOutputTokens':12288,'thinkingConfig':{'thinkingLevel':'low'}}}
                request=urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models/'+model+':generateContent',
                    data=json.dumps(body).encode('utf-8'),headers={'Content-Type':'application/json','x-goog-api-key':key})
                try:
                    with urllib.request.urlopen(request,timeout=180) as response:payload=json.load(response)
                    event={'batch':batch_name,'model':model,'credential_label':label,'attempt':attempt+1,
                        'seconds':round(time.perf_counter()-began,6),'http_status':200,
                        'usage':payload.get('usageMetadata',{}),'model_version':payload.get('modelVersion',model)}
                    self.events.append(event);self.save_events()
                    write_json(self.out/'batch_responses'/f'{batch_name}-{model}.json',payload)
                    candidates=payload.get('candidates',[])
                    if not candidates:raise ValueError('Provider returned no review; inspect prompt feedback.')
                    candidate=candidates[0]
                    if candidate.get('finishReason')!='STOP':raise ValueError('Provider finish reason: '+str(candidate.get('finishReason')))
                    text=''.join(p.get('text','') for p in candidate.get('content',{}).get('parts',[]) if not p.get('thought'))
                    reviews=json.loads(text).get('reviews')
                    if not isinstance(reviews,list):raise ValueError('Response does not contain reviews[]')
                    return reviews,event
                except urllib.error.HTTPError as error:
                    try:provider=json.loads(error.read().decode('utf-8')).get('error',{})
                    except (ValueError,UnicodeError):provider={}
                    message=str(provider.get('message',''))
                    for _,_,secret in routes:message=message.replace(secret,'[redacted]')
                    quota_text=json.dumps(provider.get('details',[])).lower()
                    daily=error.code==429 and ('perday' in quota_text or 'per_day' in quota_text)
                    event={'batch':batch_name,'model':model,'credential_label':label,'attempt':attempt+1,
                        'seconds':round(time.perf_counter()-began,6),'http_status':error.code,
                        'daily_quota_exceeded':daily,'message':message[:1600]}
                    self.events.append(event);self.save_events();errors.append(f'{model}/{label}: HTTP {error.code}')
                    if daily or error.code in {401,403}:self.disabled.add(identity);break
                    if error.code==404:self.disabled_models.add(model);break
                    if error.code==400:raise RuntimeError('Gemini rejected the request format: '+message[:600]) from None
                    if attempt==0 and error.code in {429,500,502,503,504}:
                        time.sleep(15);continue
                    self.disabled.add(identity);break
                except (urllib.error.URLError,TimeoutError) as error:
                    message=str(error)
                    for _,_,secret in routes:message=message.replace(secret,'[redacted]')
                    self.events.append({'batch':batch_name,'model':model,'credential_label':label,
                        'seconds':round(time.perf_counter()-began,6),'error':message})
                    self.save_events()
                    if attempt==0:continue
                    self.disabled.add(identity);errors.append(model+'/'+label+': connection error');break
        raise RuntimeError('No configured Gemini route is currently available. '+ '; '.join(errors))

    def save_events(self):
        write_json(self.out/'request_log.json',self.events)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--preview-source',type=Path)
    parser.add_argument('--env',type=Path,default=Path(__file__).with_name('.env'))
    args=parser.parse_args();out=args.out;out.mkdir(parents=True,exist_ok=True)
    env=load_env(args.env);source=args.source
    candidates=json.loads((source/'candidates.json').read_text(encoding='utf-8'))
    meta=json.loads((source/'meta.json').read_text(encoding='utf-8'))
    packets=select_packets(candidates,meta['duration_s'],int(env.get('GEMINI_MAX_CANDIDATES',60)),
        int(env.get('GEMINI_REGIONS',12)),int(env.get('GEMINI_PER_REGION',5)))
    batch_size=min(5,max(1,int(env.get('GEMINI_BATCH_SIZE',5))))
    lookup={p['slot_id']:p for p in packets}
    fingerprints={p['slot_id']:hashlib.sha256(json.dumps([VERSION,PROMPT,p],sort_keys=True).encode()).hexdigest() for p in packets}
    write_json(out/'review_packets.json',packets)
    (out/'instructions.txt').write_text(PROMPT,encoding='utf-8')
    write_json(out/'request_manifest.json',{'primary_model':env.get('GEMINI_MODEL'),
        'backup_model':env.get('GEMINI_BACKUP_MODEL'),'backup_key_configured':bool(env.get('GEMINI_BACKUP_API_KEY')),
        'candidate_count':len(packets),'batch_size':batch_size,'prompt_version':VERSION,
        'scores_sent':False,'audio_sent':False,'model_judgments_are_not_human_validation':True})
    results={};failures={};started=time.perf_counter();reviewer=Reviewer(args.env,out)
    for p in packets:
        cache=out/'reviews'/(p['slot_id']+'.json')
        if cache.exists():
            saved=json.loads(cache.read_text())
            if saved.get('packet_hash')==fingerprints[p['slot_id']]:
                results[p['slot_id']]=saved['review']
    def persist():
        ordered=[results[p['slot_id']] for p in packets if p['slot_id'] in results]
        make_report(out,packets,ordered,source,args.preview_source or source)
        write_json(out/'failures.json',[{'slot_id':sid,'error':reason} for sid,reason in failures.items()])
        write_json(out/'review_timings.json',{'scope':'This invocation, including requests, waits and output writing.',
            'elapsed_s':round(time.perf_counter()-started,6),'request_count':len(reviewer.events),
            'requests':reviewer.events})
    persist()
    print(f'Prepared {len(packets)} packets; {batch_size} per request; primary={env.get("GEMINI_MODEL")}; backup={env.get("GEMINI_BACKUP_MODEL")}.',flush=True)
    for round_no in range(2):
        pending=[p for p in packets if p['slot_id'] not in results]
        if not pending:break
        for index in range(0,len(pending),batch_size):
            batch=pending[index:index+batch_size];batch_name=f'r{round_no+1}-b{index//batch_size+1:02}'
            try:
                reviews,event=reviewer.call(batch,batch_name,repair=round_no>0)
                expected={p['slot_id'] for p in batch};seen=collections.Counter(r.get('slot_id') for r in reviews if isinstance(r,dict))
                for p in batch:
                    sid=p['slot_id']
                    if seen[sid]!=1:failures[sid]='Missing or duplicated slot_id in batch response';continue
                    raw=next(r for r in reviews if isinstance(r,dict) and r.get('slot_id')==sid)
                    try:
                        review=verify(raw,p)
                        review.update(model=event['model_version'],credential_label=event['credential_label'],cut_time=p['cut_time'])
                        results[sid]=review;failures.pop(sid,None)
                        write_json(out/'reviews'/(sid+'.json'),{'packet_hash':fingerprints[sid],'review':review,
                            'batch':batch_name,'model':event['model_version']})
                    except ValueError as error:failures[sid]=str(error)
                print(f'{batch_name}: {len(results)}/{len(packets)} verified reviews; {event["model_version"]} / {event["credential_label"]}',flush=True)
            except (RuntimeError,ValueError) as error:
                for p in batch:failures[p['slot_id']]=str(error)
                persist()
                if isinstance(error,RuntimeError):raise SystemExit(str(error))
                print(batch_name+': response format needs repair',flush=True)
            persist()
    print(json.dumps(json.loads((out/'summary.json').read_text()),indent=2),flush=True)
    if len(results)!=len(packets):raise SystemExit('Some reviews need manual attention; see failures.json.')


if __name__=='__main__':main()
