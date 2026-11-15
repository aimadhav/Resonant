"""Synthesize reviewed ads with Gnani Timbre v3, keeping credentials local."""
import argparse,array,hashlib,html,io,json,re,sys,time,urllib.error,urllib.request,wave
from pathlib import Path
from gemini_review import load_env,write_json

ENDPOINT='https://api.vachana.ai/api/v1/tts/inference'

def prepare_audio_tags(text):
    tags=re.findall(r'<[^<>]*>',text)
    if any(tag!='<pauses>' for tag in tags):raise ValueError('Only the exact <pauses> cue is enabled for these ads')
    if '<' in text.replace('<pauses>','') or '>' in text.replace('<pauses>',''):raise ValueError('Malformed audio tag')
    if re.search(r'<pauses>\s*<pauses>',text):raise ValueError('Do not stack pause cues')
    if text.strip().startswith('<pauses>') or text.strip().endswith('<pauses>'):raise ValueError('Pause cues must separate spoken beats')
    return re.sub(r'\s*<pauses>\s*',' <pauses> ',text)

def spoken_text(text,pronunciations=None):
    if pronunciations is None:
        path=Path(__file__).with_name('tts_pronunciations.json')
        pronunciations=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    for canonical,spoken in sorted(pronunciations.items(),key=lambda pair:-len(pair[0])):
        if not canonical or not isinstance(spoken,str) or not spoken.strip():raise ValueError('Invalid pronunciation mapping')
        text=re.sub(r'(?<!\w)'+re.escape(canonical)+r'(?!\w)',lambda match:spoken,text)
    text=text.replace('250-gram','two hundred and fifty gram').replace('250 gram','two hundred and fifty gram')
    return prepare_audio_tags(text)

def inspect_audio(data):
    with wave.open(io.BytesIO(data),'rb') as wav:
        rate=wav.getframerate();frames=wav.getnframes();channels=wav.getnchannels();width=wav.getsampwidth()
        if width!=2 or channels!=1 or rate!=48000 or frames==0:raise ValueError('Unexpected or empty WAV format')
        pcm=wav.readframes(frames)
        samples=array.array('h',pcm)
        if sys.byteorder!='little':samples.byteswap()
        peak=max(abs(s) for s in samples)
        if peak==0:raise ValueError('Provider returned silent audio')
        return {'duration_s':round(len(samples)/channels/rate,3),'sample_rate':rate,'channels':channels,'sample_width':width,'peak':peak,'full_scale_sample_fraction':round(sum(abs(s)>=32767 for s in samples)/len(samples),6),'bytes':len(data),'validation':'Actual PCM frame count and nonzero samples verified; listening quality not certified'}

def normalize_wav(data):
    # REST can return a streaming WAV header with placeholder lengths
    with wave.open(io.BytesIO(data),'rb') as source:
        params=source.getparams();pcm=source.readframes(source.getnframes())
    target=io.BytesIO()
    with wave.open(target,'wb') as wav:
        wav.setnchannels(params.nchannels);wav.setsampwidth(params.sampwidth);wav.setframerate(params.framerate);wav.writeframes(pcm)
    return target.getvalue()

def main():
    parser=argparse.ArgumentParser();base=Path(__file__).resolve().parent
    parser.add_argument('--input',type=Path,default=base.parent/'ad-simulation/creative-final/results.json')
    parser.add_argument('--reviews',type=Path,default=base.parent/'ad-simulation/creative-final/independent-review/review.json')
    parser.add_argument('--env',type=Path,default=base/'.env');parser.add_argument('--out',type=Path,default=base.parent/'ad-simulation/tts-timbre-v3')
    parser.add_argument('--dry-run',action='store_true');parser.add_argument('--female-audition',action='store_true');parser.add_argument('--delivery-from-input',action='store_true');args=parser.parse_args();started=time.perf_counter()
    env=load_env(args.env);key=env.get('GNANI_API_KEY','').strip();model=env.get('GNANI_TTS_MODEL','timbre-v3.0')
    if model!='timbre-v3.0':raise SystemExit('This run requires timbre-v3.0')
    voice=env.get('GNANI_TTS_VOICE','Riyaa');language=env.get('GNANI_TTS_LANGUAGE','en-IN');speed=float(env.get('GNANI_TTS_SPEED','1.0'))
    if not .85<=speed<=1.0:raise SystemExit('User preference: speed must stay between 0.85 and 1.0')
    results=json.loads(args.input.read_text(encoding='utf-8'));reviews={r['scenario_id']:r for r in json.loads(args.reviews.read_text(encoding='utf-8'))}
    out=args.out;out.mkdir(parents=True,exist_ok=True);items=[];events=[]
    secrets=[v for k,v in env.items() if ('KEY' in k or 'TOKEN' in k) and v]
    def redact(text):
        for secret in secrets:text=text.replace(secret,'[redacted]')
        return text
    def save():
        write_json(out/'manifest.json',items);write_json(out/'request_log.json',events)
        summary={'model':model,'voice':sorted({i['voice'] for i in items}) if args.delivery_from_input else 'seven female voices' if args.female_audition else voice,'language':language,'speed':sorted({i['speed'] for i in items}) if args.delivery_from_input else speed,'prepared_ads':len(items),'completed_ads':sum(i.get('status')=='complete' for i in items),'failed_ads':sum(i.get('status')=='failed' for i in items),'api_attempts':len(events),'total_elapsed_s':round(time.perf_counter()-started,6),'total_audio_s':round(sum(i.get('audio',{}).get('duration_s',0) for i in items),3),'dry_run':args.dry_run}
        write_json(out/'timings.json',summary)
        cards=[]
        for item in items:
            audio='<audio controls preload="none" src="'+html.escape(item['filename'],quote=True)+'"></audio>' if item.get('status')=='complete' else ''
            cards.append('<article><h2>'+html.escape(item.get('voice',voice)+' — '+item['scenario_id'])+'</h2>'+audio+'<p>'+html.escape(item['spoken_text'])+'</p><pre>'+html.escape(json.dumps({k:v for k,v in item.items() if k not in {'spoken_text','source_text'}},indent=2))+'</pre></article>')
        (out/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>Timbre v3 podcast ads</title><style>body{font:17px system-ui;max-width:1000px;margin:40px auto;padding:20px;background:#f5f4ef}article{background:white;padding:24px;margin:20px 0;border-radius:12px}p{line-height:1.7}pre{white-space:pre-wrap}audio{width:100%}</style><h1>Timbre v3 podcast ads</h1><pre>'+html.escape(json.dumps(summary,indent=2))+'</pre>'+''.join(cards),encoding='utf-8')
    for result in results:
        sid=result['scenario_id'];output=result['model_output']
        if output.get('decision')!='generate' or not result['deterministic_checks']['passed'] or reviews.get(sid,{}).get('decision')!='pass':continue
        selected_voice=['Lakshmi','Riyaa','Vasudha','Shivani','Chetana','Kalpana','Tarika'][len(items)%7] if args.female_audition else voice
        selected_speed=speed
        if args.delivery_from_input:
            selected_voice=result['delivery']['voice'];selected_speed=float(result['delivery']['speed'])
            if selected_voice not in {'Riyaa','Shivani'} or not .85<=selected_speed<=1.0:raise ValueError('Use Riyaa or Shivani at 0.85–1.0 speed only')
        text=spoken_text(output['script_text']);body={'text':text,'voice':selected_voice,'model':model,'language':language,'speed':selected_speed,'audio_config':{'sample_rate':48000,'num_channels':1,'sample_width':2,'encoding':'linear_pcm','container':'wav'}}
        fingerprint=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest();filename=sid+'.wav'
        item={'scenario_id':sid,'voice':selected_voice,'speed':selected_speed,'filename':filename,'source_text':output['script_text'],'spoken_text':text,'request_hash':fingerprint,'status':'prepared','cut_time_s':result['selected_context']['cut_time']};items.append(item)
        write_json(out/'requests'/(sid+'.json'),body)
    save()
    if args.dry_run:print(f'Prepared {len(items)} ads; no API calls');return
    if not key:raise SystemExit('GNANI_API_KEY is not saved in the local .env yet; no API calls made')
    for item in items:
        checkpoint=out/'checkpoints'/(item['scenario_id']+'.json');path=out/item['filename']
        if checkpoint.exists() and path.exists():
            prior=json.loads(checkpoint.read_text())
            if prior.get('request_hash')==item['request_hash']:
                data=normalize_wav(path.read_bytes());path.write_bytes(data)
                item.update(prior);item['audio']=inspect_audio(data);item['cache_hit']=True;write_json(checkpoint,item);save();continue
        body=json.loads((out/'requests'/(item['scenario_id']+'.json')).read_text());began=time.perf_counter()
        for attempt in range(1,4):
            request=urllib.request.Request(ENDPOINT,data=json.dumps(body).encode('utf-8'),headers={'Content-Type':'application/json','Accept':'audio/wav, application/json','User-Agent':'GnaniPodcastTTS/1.0','X-API-Key-ID':key},method='POST');call_started=time.perf_counter()
            try:
                with urllib.request.urlopen(request,timeout=180) as response:data=response.read();status=response.status
                data=normalize_wav(data);meta=inspect_audio(data);path.write_bytes(data)
                events.append({'scenario_id':item['scenario_id'],'attempt':attempt,'http_status':status,'seconds':round(time.perf_counter()-call_started,6)})
                item.update(status='complete',audio=meta,elapsed_s=round(time.perf_counter()-began,6));write_json(checkpoint,item);save()
                print(f"Saved {item['filename']}: {meta['duration_s']}s audio",flush=True);break
            except urllib.error.HTTPError as error:
                message=redact(error.read().decode('utf-8',errors='replace'))[:800]
                events.append({'scenario_id':item['scenario_id'],'attempt':attempt,'http_status':error.code,'seconds':round(time.perf_counter()-call_started,6),'message':message});save()
                if error.code in {401,402,403}:item.update(status='failed',error=message);save();raise SystemExit(f'Gnani HTTP {error.code}: '+message)
                if error.code not in {429,500,502,503,504} or attempt==3:item.update(status='failed',error=message);save();break
                time.sleep(min(2**attempt,8))
            except (ValueError,wave.Error,EOFError,TimeoutError,urllib.error.URLError) as error:
                item.update(status='failed',error=redact(str(error)));save();break
    save();print(json.dumps(json.loads((out/'timings.json').read_text()),indent=2))

if __name__=='__main__':main()
