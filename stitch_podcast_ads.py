"""Insert one contextual ad per distinct source cut and export an indexed podcast."""
import argparse,hashlib,html,json,math,subprocess,time,wave
from pathlib import Path
from gemini_review import write_json

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--root',type=Path,required=True);p.add_argument('--work',type=Path,required=True);args=p.parse_args()
    root=args.root.resolve();scratch=args.work.resolve();scratch.mkdir(parents=True,exist_ok=True);started=time.perf_counter();events=[]
    read=lambda f:json.loads(f.read_text(encoding='utf-8'))
    results={r['scenario_id']:r for r in read(root/'results.json')};manifest={r['scenario_id']:r for r in read(root/'audio/manifest.json')}
    selection=read(root/'insertion_selection.json') if (root/'insertion_selection.json').exists() else {}
    chosen=selection.get('scenario_ids',['paper_over_subscription','sleep_product_preferences','coffee_callback','vegetarian_meal_planning']);plan=[];temporary=[]
    def command(label,argv):
        before=time.perf_counter();r=subprocess.run(argv,capture_output=True,text=True,encoding='utf-8',errors='replace')
        events.append({'process':label,'seconds':round(time.perf_counter()-before,6),'exit_code':r.returncode})
        write_json(root/'stitch_process_log.json',events)
        if r.returncode:raise RuntimeError(label+': '+r.stderr[-2200:])
        return r
    def probe(path):
        r=command('probe_'+path.stem,['ffprobe','-v','error','-show_entries','format=duration:stream=sample_rate,channels','-of','json',str(path)])
        return json.loads(r.stdout)
    source_info=probe(args.source);source_duration=float(source_info['format']['duration']);sample_rate=44100
    for sid in chosen:
        item=manifest[sid];assert item['status']=='complete';assert .85<=item['speed']<=1.0
        cut=round(results[sid]['selected_context']['cut_time']*sample_rate)/sample_rate
        # Estimate the local podcast loudness, then use it as the ad's target
        measured=command('local_loudness_'+sid,['ffmpeg','-hide_banner','-nostdin','-ss',str(max(0,cut-35)),'-t','30','-i',str(args.source),'-af','loudnorm=I=-18:TP=-1.5:LRA=7:print_format=json','-f','null','-'])
        raw=measured.stderr[measured.stderr.rfind('{'):];stats,_=json.JSONDecoder().raw_decode(raw);local=float(stats['input_i']);target=max(-22,min(-16,local)) if math.isfinite(local) else -18
        normalized=scratch/('ad_'+sid+'.flac');temporary.append(normalized)
        duration=item['audio']['duration_s'];filtering=f'loudnorm=I={target}:TP=-1.5:LRA=7,afade=t=in:st=0:d=0.005,afade=t=out:st={max(0,duration-.01)}:d=0.01,adelay=250:all=1,apad=pad_dur=0.35'
        command('normalize_ad_'+sid,['ffmpeg','-hide_banner','-nostdin','-y','-i',str(root/'audio'/item['filename']),'-af',filtering,'-ar','44100','-ac','2','-c:a','flac',str(normalized)])
        padded=float(probe(normalized)['format']['duration'])
        plan.append({'scenario_id':sid,'source_cut_s':cut,'voice':item['voice'],'speed':item['speed'],'local_podcast_lufs':local,'ad_target_lufs':target,'ad_audio_s':duration,'inserted_span_s':padded,'lead_s':.25,'tail_s':.35,'normalized_file':str(normalized)})
    plan.sort(key=lambda x:x['source_cut_s']);assert len({x['source_cut_s'] for x in plan})==len(plan)
    # Stream decoded PCM once, inserting ads at exact source-frame boundaries
    # This avoids several large intermediate episode files and repeated decoding
    output=root/'podcast-with-ads.mp3'
    decoder_log=scratch/'decoder.log';encoder_log=scratch/'encoder.log';temporary.extend([decoder_log,encoder_log]);stream_started=time.perf_counter();offset=0;source_bytes=0;ad_bytes=0;frame_bytes=4
    with decoder_log.open('wb') as decoder_errors,encoder_log.open('wb') as encoder_errors:
        decoder=subprocess.Popen(['ffmpeg','-v','error','-nostdin','-i',str(args.source),'-map','0:a:0','-ar','44100','-ac','2','-f','s16le','pipe:1'],stdout=subprocess.PIPE,stderr=decoder_errors)
        encoder=subprocess.Popen(['ffmpeg','-v','error','-nostdin','-y','-f','s16le','-ar','44100','-ac','2','-i','pipe:0','-c:a','libmp3lame','-b:a','128k','-map_metadata','-1',str(output)],stdin=subprocess.PIPE,stderr=encoder_errors)
        try:
            for index,ad in enumerate(plan,1):
                target=round(ad['source_cut_s']*sample_rate)*frame_bytes
                while source_bytes<target:
                    chunk=decoder.stdout.read(min(1024*1024,target-source_bytes))
                    if not chunk:raise RuntimeError('Podcast ended before insertion boundary')
                    encoder.stdin.write(chunk);source_bytes+=len(chunk)
                decode_started=time.perf_counter()
                rendered=subprocess.run(['ffmpeg','-v','error','-nostdin','-i',ad['normalized_file'],'-ar','44100','-ac','2','-f','s16le','pipe:1'],capture_output=True)
                if rendered.returncode:raise RuntimeError('Could not decode normalized ad')
                events.append({'process':'decode_insert_'+ad['scenario_id'],'seconds':round(time.perf_counter()-decode_started,6),'exit_code':0})
                encoder.stdin.write(rendered.stdout);ad_bytes+=len(rendered.stdout)
                ad['inserted_span_s']=len(rendered.stdout)/frame_bytes/sample_rate
                ad['output_break_start_s']=ad['source_cut_s']+offset;ad['output_ad_start_s']=ad['output_break_start_s']+.25;ad['output_ad_end_s']=ad['output_ad_start_s']+ad['ad_audio_s'];offset+=ad['inserted_span_s']
                print(f'Inserted ad {index}/{len(plan)} at source {ad["source_cut_s"]:.2f}s',flush=True)
            while True:
                chunk=decoder.stdout.read(1024*1024)
                if not chunk:break
                encoder.stdin.write(chunk);source_bytes+=len(chunk)
            encoder.stdin.close();encoder.wait();decoder.wait()
            if decoder.returncode or encoder.returncode:raise RuntimeError('Podcast decoder or encoder failed, inspect scratch logs')
        except BaseException:
            decoder.kill();encoder.kill();decoder.wait();encoder.wait();raise
        finally:decoder.stdout.close()
    events.append({'process':'single_pass_decode_insert_encode','seconds':round(time.perf_counter()-stream_started,6),'exit_code':0,'original_pcm_bytes_retained':source_bytes,'inserted_pcm_bytes':ad_bytes});write_json(root/'stitch_process_log.json',events)
    output_duration=float(probe(output)['format']['duration']);expected=source_duration+offset
    if abs(output_duration-expected)>.15:raise RuntimeError(f'Duration mismatch: {output_duration} vs {expected}')
    for ad in plan:ad.pop('normalized_file')
    summary={'source_duration_s':source_duration,'output_duration_s':output_duration,'expected_duration_s':expected,'duration_error_s':round(output_duration-expected,6),'inserted_ads':len(plan),'regenerated_ads':len(manifest),'alternates':[sid for sid in manifest if sid not in chosen],'selection_reason':selection.get('reason','Seven scripts share four distinct source cuts, select one ad at each cut and preserve the other three as alternate creatives'),'source_audio_treatment':'Original episode sections retained in order and re-encoded once to 128kbps stereo MP3, ads normalized toward local episode loudness with 250ms lead and 350ms tail silence, no source speech intentionally removed','total_stitch_elapsed_s':round(time.perf_counter()-started,6),'source_file':str(args.source),'output_file':str(output),'limitations':'Placement points come from earlier automated review, transitions have not received human listening review'}
    write_json(root/'insertion_timeline.json',plan);write_json(root/'stitch_summary.json',summary)
    # Delete only files generated by this invocation within the verified scratch directory
    for path in temporary:
        if path.resolve().parent!=scratch:raise RuntimeError('Temporary path escaped scratch directory')
        path.unlink(missing_ok=True)
    print(json.dumps(summary,indent=2),flush=True)

if __name__=='__main__':main()
