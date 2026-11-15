"""Offline processor. Heavy dependencies are imported only inside Kaggle stages."""
import bisect
import contextlib
import csv
import hashlib
import html
import json
import math
import re
import time
import wave
from pathlib import Path

import numpy as np

TERMINAL = re.compile(r'[.!?।][\"\u201d\u2019\)\]]*$')
CONTINUATION = re.compile(r'^(and|but|so|because|which|then)\b', re.I)


def is_terminal(text):
    tail=text.rstrip().rstrip('\"\u201d\u2019)]').rstrip()
    if re.search(r'(?:\.{2,}|…)$',tail):
        return False
    if re.search(r'\b(?:dr|mr|mrs|ms|prof|vs)\.$',tail,re.I):
        return False
    return bool(TERMINAL.search(text))


def review_candidate(candidate, previous, following, cfg):
    """Conservative lexical risk checks. This is not semantic acceptance."""
    values={'question_then_answer':.8,'continuation_start':.6,'short_turn':.3,
            'low_asr_confidence':.5,'inferred_timing':.4,'incomplete_boundary':.9,
            'example_pending':.8,'short_fragment':.65,'short_response_after':.7,
            'promotional_context':.7,'dependent_resume':.5}
    values.update(cfg.get('risk_values',{}))
    flags=set(candidate.get('risk_flags',[]))
    text=previous['text'].strip();after=following['text'].strip()
    clean=text.rstrip('\"\u201d\u2019)]').rstrip()
    if not is_terminal(text):flags.add('incomplete_boundary')
    if clean.endswith('?'):flags.add('question_then_answer')
    if re.search(r'\b(?:like this|as follows|for example|for instance|let me explain|let me show you|the reason is)\s*[.!:]?$',clean,re.I):
        flags.add('example_pending')
    tokens=lambda t:re.findall(r"\b\w+(?:['\u2019]\w+)*\b",t)
    if len(tokens(text))<=2:flags.add('short_fragment')
    after_words=tokens(after.lower())
    if len(after_words)<=2 or re.fullmatch(r'(?:yeah|yes|nice|right|exactly|okay|ok|sure|well|listen|you got this)[\W_]*',after,re.I):
        flags.add('short_response_after')
    if len(after_words)<9 and re.match(r"^(?:that|this|those|these|it|they)(?:\b|['\u2019])",after,re.I):
        flags.add('dependent_resume')
    nearby=[s['text'] for s in candidate.get('context',{}).get('before',[])
            if s['end']>=candidate['time']-30]
    if re.search(r'\b(?:link in (?:the )?description|promo(?:tional)? code|use (?:the )?code|sponsored by|brought to you by)\b',' '.join(nearby),re.I):
        flags.add('promotional_context')
    risk=max([candidate.get('interruption_risk',0)]+[values.get(f,.5) for f in flags])
    candidate['risk_flags']=sorted(flags)
    candidate['interruption_risk']=risk
    candidate['base_score']=round(candidate['boundary_quality']*(1-risk),6)
    candidate['shortlist_eligible']=risk<=cfg.get('shortlist_max_risk',.5) and candidate['base_score']>=cfg.get('shortlist_min_score',.35)
    candidate['editorial_status']='unreviewed_heuristic_candidate'
    return candidate


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    indent=2, allow_nan=False) + '\n', encoding='utf-8')


class Timings:
    def __init__(self, directory, scope='Kaggle worker; excludes scheduler queue and local transfers'):
        self.scope=scope
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.started = time.perf_counter()
        self.rows = []

    @contextlib.contextmanager
    def stage(self, name):
        started = time.perf_counter()
        status = 'complete'
        print(f'START {name}', flush=True)
        try:
            yield
        except BaseException:
            status = 'failed'
            raise
        finally:
            row = {'stage': name, 'seconds': round(time.perf_counter() - started, 6),
                   'status': status}
            self.rows.append(row)
            self.save()
            print(f'END {name}: {row["seconds"]:.3f}s ({status})', flush=True)

    def save(self):
        write_json(self.directory / 'compute_timings.json', {
            'scope': self.scope,
            'total_seconds': round(time.perf_counter() - self.started, 6),
            'stages': self.rows})
        (self.directory / 'compute.log').write_text('\n'.join(
            f'{r["stage"]}: {r["seconds"]:.6f} s [{r["status"]}]' for r in self.rows
        ) + f'\nWorker elapsed: {time.perf_counter() - self.started:.6f} s\n', encoding='utf-8')


def normalize_transcript(data, duration):
    words = []
    for segment in data.get('segments', []):
        raw = segment.get('words') or []
        if not raw:
            raw = [{'word': t} for t in segment.get('text', '').split()]
        if not raw:
            continue
        raw = [dict(w) for w in raw]
        for w in raw:
            w['inferred_timing'] = w.get('start') is None or w.get('end') is None
        # Interpolate missing runs between the nearest real anchors; retain overlaps.
        i = 0
        while i < len(raw):
            if not raw[i]['inferred_timing']:
                i += 1
                continue
            j = i
            while j < len(raw) and raw[j]['inferred_timing']:
                j += 1
            left = float(raw[i-1]['end']) if i else float(segment.get('start', 0))
            right = float(raw[j]['start']) if j < len(raw) else float(segment.get('end', duration))
            if right < left:
                raise ValueError('Missing timestamps cannot be interpolated between reversed anchors')
            for k in range(i, j):
                raw[k]['start'] = left + (right-left) * (k-i)/(j-i)
                raw[k]['end'] = left + (right-left) * (k-i+1)/(j-i)
            i = j
        for w in raw:
            start, end = float(w['start']), float(w['end'])
            if not (math.isfinite(start) and math.isfinite(end) and 0 <= start <= end <= duration + .05):
                raise ValueError(f'Invalid word timestamp: {start}, {end}')
            if words and start < words[-1]['start']:
                raise ValueError('Transcript word starts are out of order; fix alignment rather than sorting')
            score = w.get('score', w.get('probability'))
            words.append({'id': len(words), 'text': w.get('word', '').strip(),
                          'start': start, 'end': min(end, duration),
                          'speaker': w.get('speaker', segment.get('speaker')),
                          'confidence': float(score) if score is not None else None,
                          'inferred_timing': w['inferred_timing']})
    if not words:
        raise ValueError('Transcript contains no words')
    sentences, group = [], []
    def finish():
        if not group:
            return
        confidences = [w['confidence'] for w in group if w['confidence'] is not None]
        speakers = set(w['speaker'] for w in group)
        sentences.append({'id': f't{len(sentences):05}', 'start': group[0]['start'],
            'end': max(w['end'] for w in group), 'text': ' '.join(w['text'] for w in group),
            'speaker': next(iter(speakers)) if len(speakers) == 1 else None,
            'avg_conf': float(np.mean(confidences)) if confidences else None,
            'word_ids': [w['id'] for w in group],
            'inferred_timing': any(w['inferred_timing'] for w in group)})
        group.clear()
    for w in words:
        if group and (w['start'] - group[-1]['end'] > .7 or
                      (w['speaker'] and group[-1]['speaker'] and w['speaker'] != group[-1]['speaker'])):
            finish()
        group.append(w)
        if is_terminal(w['text']):
            finish()
    finish()
    return words, sentences


def frame_energy(audio, sr=16000):
    # Max channel energy avoids cancellation of opposite-phase stereo speech.
    if audio.ndim == 1:
        audio = audio[:, None]
    n, hop = int(.020*sr), int(.010*sr)
    starts = np.arange(0, max(0, len(audio)-n+1), hop)
    values = np.empty(len(starts), dtype=np.float32)
    for i, start in enumerate(starts):
        values[i] = 20*np.log10(max(1e-10, float(np.sqrt(np.mean(audio[start:start+n]**2, axis=0)).max())))
    return starts/sr, starts/sr + n/sr, values


def merge_intervals(intervals):
    result = []
    for a, b in sorted(intervals):
        if result and a <= result[-1][1] + 1e-7:
            result[-1][1] = max(b, result[-1][1])
        else:
            result.append([float(a), float(b)])
    return result


def context_sentences(sentences, start, end):
    return [s for s in sentences if s['end'] > start and s['start'] < end]


def select_shortlist(candidates, cfg, duration=None):
    for c in candidates:
        c['shortlist'] = False
        c['shortlist_reason'] = None
    ranked = sorted(candidates, key=lambda c: (-c['base_score'], c['time']))
    for rank, c in enumerate(ranked, 1):
        c['rank'] = rank
    eligible=[c for c in ranked if c.get('shortlist_eligible',True)]
    if not eligible:return
    selected=[]
    start=cfg.get('min_start_s',0)
    end=(duration-cfg.get('min_tail_s',0)) if duration is not None else max(c['time'] for c in eligible)+.001
    span=max(end-start,.001)
    # Reserve at most half the budget for regions spanning the ENTIRE episode.
    regions=min(max(1,cfg['shortlist_size']//2),max(1,math.ceil(span/cfg['bin_s'])))
    for region in range(regions):
        pool=[c for c in eligible if min(regions-1,max(0,int((c['time']-start)/span*regions)))==region]
        for c in pool:
            if all(abs(c['time']-s['time'])>=cfg['shortlist_spacing_s'] for s in selected):
                c['shortlist_reason']='coverage'
                selected.append(c)
                break
    for c in eligible:
        if len(selected) >= cfg['shortlist_size']:
            break
        if c not in selected and all(abs(c['time']-s['time']) >= cfg['shortlist_spacing_s'] for s in selected):
            selected.append(c)
            c['shortlist_reason']='quality'
    for c in selected:
        c['shortlist'] = True


def generate_candidates(words, sentences, duration, frame_starts, frame_ends, db, speech, cfg, vectors=None):
    candidates = []
    counts = {'sentence_pairs': max(0, len(sentences)-1), 'punctuation_rejected': 0,
              'pause_rejected': 0, 'eligible_asr_gaps': 0, 'acoustic_rejected': 0,
              'bounds_rejected': 0}
    word_intervals = merge_intervals([(w['start']-cfg['word_margin_s'], w['end']+cfg['word_margin_s']) for w in words])
    vad_intervals = merge_intervals([(a-cfg['vad_margin_s'], b+cfg['vad_margin_s']) for a,b in speech])
    blockers = merge_intervals(word_intervals + vad_intervals)
    blocker_ends = [b for a,b in blockers]
    speech_frames = np.zeros(len(db), dtype=bool)
    for a,b in speech:
        lo = np.searchsorted(frame_ends, a, side='right')
        hi = np.searchsorted(frame_starts, b, side='left')
        speech_frames[lo:hi] = True
    for idx, (prev, nxt) in enumerate(zip(sentences, sentences[1:])):
        if not is_terminal(prev['text']):
            counts['punctuation_rejected'] += 1
            continue
        a,b = prev['end'], nxt['start']
        if b-a < cfg['min_pause_s']:
            counts['pause_rejected'] += 1
            continue
        counts['eligible_asr_gaps'] += 1
        local = (frame_starts >= a-10) & (frame_ends <= b+10) & speech_frames
        if not local.any():
            counts['acoustic_rejected'] += 1
            continue
        reference = float(np.median(db[local]))
        lo,hi = np.searchsorted(frame_starts, a), np.searchsorted(frame_ends, b, side='right')
        eligible = []
        block_idx = bisect.bisect_right(blocker_ends, a)
        for k in range(lo, min(hi, len(db))):
            x,y = float(frame_starts[k]), float(frame_ends[k])
            if x < a or y > b or db[k] > reference-cfg['energy_drop_db']:
                continue
            while block_idx < len(blockers) and blockers[block_idx][1] < x:
                block_idx += 1
            if block_idx < len(blockers) and blockers[block_idx][0] <= y:
                continue
            eligible.append((x,y))
        regions = [r for r in merge_intervals(eligible) if r[1]-r[0] >= cfg['min_quiet_s']-1e-7]
        if not regions:
            counts['acoustic_rejected'] += 1
            continue
        region = min(regions, key=lambda r: (-(r[1]-r[0]), r[0]))
        cut = round(sum(region)/2, 6)
        if not cfg['min_start_s'] <= cut <= duration-cfg['min_tail_s']:
            counts['bounds_rejected'] += 1
            continue
        assert not any(w['start'] <= cut <= w['end'] for w in words)
        assert not any(x <= cut <= y for x,y in speech)
        before = context_sentences(sentences, cut-cfg['before_s'], cut)
        after = context_sentences(sentences, cut, cut+cfg['after_s'])
        # Context is never allowed to include words from the other side.
        before = [s for s in before if s['end'] <= cut]
        after = [s for s in after if s['start'] >= cut]
        flags = {}
        changed = bool(prev['speaker'] and nxt['speaker'] and prev['speaker'] != nxt['speaker'])
        if prev['text'].rstrip().endswith('?') and (changed or b-a < .8):
            flags['question_then_answer'] = .8
        if CONTINUATION.match(nxt['text']):
            flags['continuation_start'] = .6
        if any(s['avg_conf'] is not None and s['avg_conf'] < .6 for s in [prev,nxt]):
            flags['low_asr_confidence'] = .5
        if any(s['inferred_timing'] for s in [prev,nxt]):
            flags['inferred_timing'] = .4
        # Compute actual consecutive known-speaker turn duration.
        turn_start,turn_end = prev['start'],prev['end']
        if prev['speaker']:
            j = idx-1
            while j >= 0 and sentences[j]['speaker'] == prev['speaker']:
                turn_start = sentences[j]['start']; j -= 1
            if turn_end-turn_start < 8:
                flags['short_turn'] = .3
        topic = None
        if vectors is not None:
            left = [j for j,s in enumerate(sentences) if a-45 < s['end'] <= cut]
            right = [j for j,s in enumerate(sentences) if cut <= s['start'] < b+45]
            if left and right:
                v1,v2 = vectors[left].mean(0),vectors[right].mean(0)
                topic = float(np.clip(1-np.dot(v1,v2)/(np.linalg.norm(v1)*np.linalg.norm(v2)+1e-10),0,1))
        components = {'pause': min((b-a)/1.2,1),
                      'quiet_duration': min((region[1]-region[0])/.5,1),
                      'topic_shift': topic, 'speaker_change': int(changed)}
        weights = cfg.get('weights',{'pause': .45, 'quiet_duration': .35, 'topic_shift': .20})
        available = [k for k in weights if components[k] is not None]
        quality = sum(weights[k]*components[k] for k in available)/sum(weights[k] for k in available)
        text = ' '.join(s['text'] for s in before+after)
        sensitive = [term for term in cfg['sensitive_terms'] if re.search(r'(?<!\w)'+re.escape(term)+r'(?!\w)',text,re.I)]
        risk = max(flags.values(), default=0)
        candidates.append({'slot_id': f's{len(candidates):05}', 'time': cut,
            'gap': {'start':a,'end':b,'length_s':b-a}, 'quiet_interval':region,
            'prev_sentence_id':prev['id'],'next_sentence_id':nxt['id'],
            'boundary_quality':round(quality,6),'boundary_components':components,
            'interruption_risk':risk,'risk_flags':list(flags),'sensitive_flags':sensitive,
            'base_score':round(quality*(1-risk),6),
            'timing_confidence': 'reduced' if 'inferred_timing' in flags or region[1]-region[0]<.2 else 'higher',
            'timing_evidence':{'inferred_timing_nearby':'inferred_timing' in flags,
                'quiet_duration_s':round(region[1]-region[0],6),
                'clearance_before_s':round(cut-a,6),'clearance_after_s':round(b-cut,6),
                'local_speech_db':round(reference,3), 'vad_checked':True},
            'context':{'before':before,'after':after},
            'preview_ref':f'previews/s{len(candidates):05}.wav'})
    lookup={s['id']:s for s in sentences}
    for c in candidates:
        review_candidate(c,lookup[c['prev_sentence_id']],lookup[c['next_sentence_id']],cfg)
    select_shortlist(candidates,cfg,duration)
    counts['accepted'] = len(candidates)
    return candidates,counts


def make_chunks(sentences, cfg):
    chunks = []
    if not sentences:
        return chunks
    start = sentences[0]['start']
    while start < sentences[-1]['end']:
        ss = context_sentences(sentences,start,start+cfg['chunk_s'])
        if ss:
            ids = [s['id'] for s in ss]
            if not chunks or chunks[-1]['sentence_ids'] != ids:
                chunks.append({'id':f'c{len(chunks):05}', 'start':ss[0]['start'],'end':ss[-1]['end'],
                    'sentence_ids':ids,'speakers':sorted(set(s['speaker'] for s in ss if s['speaker'])),
                    'text':' '.join(s['text'] for s in ss)})
        start += cfg['chunk_s']-cfg['chunk_overlap_s']
    return chunks


def search(directory, query, top_k=5, encoder=None):
    directory = Path(directory)
    chunks = json.loads((directory/'transcript_index.json').read_text(encoding='utf-8'))
    terms = set(re.findall(r'\w+',query.lower()))
    lexical = np.array([len(terms & set(re.findall(r'\w+',c['text'].lower())))/max(1,len(terms)) for c in chunks])
    semantic = np.zeros(len(chunks))
    if encoder is not None and chunks:
        q = encoder.encode(['query: '+query], normalize_embeddings=True)[0]
        semantic = np.load(directory/'chunk_embeddings.npy',allow_pickle=False) @ q
    ranks = sorted(range(len(chunks)),key=lambda i:(-(lexical[i]+semantic[i]),chunks[i]['start']))
    return [dict(chunks[i],keyword_score=float(lexical[i]),semantic_score=float(semantic[i])) for i in ranks[:top_k]]


def render_report(out, candidates, counts):
    rows = []
    cache_note=''
    if (out/'original_compute_timings.json').exists():
        cache_note='<p>This revision reuses the original transcription, alignment, VAD and embeddings. <a href="original_compute_timings.json">Original processing timings</a> · <a href="rerank_transfer_timings.json">Revision transfer timings</a></p>'
    for c in candidates:
        if not c['shortlist']:
            continue
        before = ' '.join(s['text'] for s in c['context']['before'])
        after = ' '.join(s['text'] for s in c['context']['after'])
        rows.append(f'''<article><h2>{c['slot_id']} · {c['time']:.2f}s · score {c['base_score']:.3f}
          {' · SHORTLIST' if c['shortlist'] else ''}</h2>
          <p>{html.escape(', '.join(c['risk_flags']+c['sensitive_flags']) or 'No rule flags')}</p>
          {f'<audio controls preload="none" src="{c["preview_ref"]}"></audio>' if c.get('preview_available',True) else '<p>Preview not exported.</p>'}
          <p>Preview includes a marker at the cut; original audio is unmodified.</p>
          <h3>Before</h3><p>{html.escape(before)}</p><h3>After</h3><p>{html.escape(after)}</p></article>''')
    (out/'report.html').write_text('''<!doctype html><html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
      <title>Podcast candidate report</title><style>body{font:16px system-ui;max-width:980px;margin:40px auto;padding:20px;background:#f4f5f0;color:#202922}article{background:white;border:1px solid #d9ded5;padding:24px;margin:20px 0;border-radius:12px}p{line-height:1.6}h2{font-size:20px}audio{width:100%}</style>
      <h1>Episode boundary report · shortlist</h1><p>These are unreviewed heuristic candidates. Full raw candidates are retained in JSON/CSV. Conversational and advertiser review is still required.</p>
      <p><a href="compute_timings.json">Compute timings</a> · <a href="compute.log">Compute log</a> · <a href="candidates.json">Candidates JSON</a></p>
      <pre>'''+html.escape(json.dumps(counts,indent=2))+'</pre>'+cache_note+''.join(rows)+'</html>',encoding='utf-8')


def process(audio_path, transcript_path, out, cfg, timings):
    with timings.stage('pipeline_imports'):
        import soundfile as sf
        import torch
        from silero_vad import load_silero_vad, get_speech_timestamps
        from sentence_transformers import SentenceTransformer
    out = Path(out)
    out.mkdir(parents=True,exist_ok=True)
    with timings.stage('audio_decode'):
        # ffmpeg preserves channel count; analysis uses 16 kHz per channel.
        import subprocess
        decoded = out.parent/'analysis.wav'
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(audio_path),'-ar','16000',str(decoded)],check=True)
        audio,sr = sf.read(decoded,dtype='float32',always_2d=True)
        duration = len(audio)/sr
    if transcript_path is None:
        import whisperx
        with timings.stage('asr_model_load'):
            device = cfg.get('device','auto')
            if device=='auto':device='cuda' if torch.cuda.is_available() else 'cpu'
            if device=='cuda' and not torch.cuda.is_available():raise RuntimeError('CUDA requested but no accessible CUDA GPU')
            model = whisperx.load_model(cfg['asr_model'],device,compute_type='float16' if device=='cuda' else 'int8',vad_method='silero')
            mono = np.mean(audio,axis=1)
        with timings.stage('transcription'):
            transcript = model.transcribe(mono,batch_size=cfg.get('batch_size',8))
            del model
            if device=='cuda': torch.cuda.empty_cache()
        with timings.stage('alignment_model_load'):
            aligner,metadata = whisperx.load_align_model(language_code=transcript['language'],device=device)
        with timings.stage('word_alignment'):
            transcript = whisperx.align(transcript['segments'],aligner,metadata,mono,device)
            del aligner
            if device=='cuda': torch.cuda.empty_cache()
        write_json(out/'transcript.whisperx.json',transcript)
    else:
        with timings.stage('transcript_load'):
            transcript = json.loads(Path(transcript_path).read_text(encoding='utf-8-sig'))
            write_json(out/'transcript.whisperx.json',transcript)
    with timings.stage('transcript_normalization'):
        words,sentences = normalize_transcript(transcript,duration)
    with timings.stage('energy_analysis'):
        starts,ends,db = frame_energy(audio,sr)
    with timings.stage('vad_model_load'):
        torch.set_num_threads(2)
        vad = load_silero_vad()
    with timings.stage('vad_inference'):
        intervals=[]
        for channel in range(audio.shape[1]):
            vad.reset_states()
            stamps=get_speech_timestamps(torch.from_numpy(audio[:,channel].copy()),vad,sampling_rate=sr,return_seconds=True)
            intervals.extend((s['start'],s['end']) for s in stamps)
        speech=merge_intervals(intervals)
    with timings.stage('embedding_model_load'):
        encoder=SentenceTransformer(cfg['embedding_model'],device='cpu')
    with timings.stage('sentence_embeddings'):
        vectors=encoder.encode(['passage: '+s['text'] for s in sentences],normalize_embeddings=True,show_progress_bar=False)
    with timings.stage('candidate_generation_scoring'):
        candidates,counts=generate_candidates(words,sentences,duration,starts,ends,db,speech,cfg,vectors)
    with timings.stage('transcript_index'):
        chunks=make_chunks(sentences,cfg)
        chunk_vectors=encoder.encode(['passage: '+c['text'] for c in chunks],normalize_embeddings=True,show_progress_bar=False)
        np.save(out/'chunk_embeddings.npy',chunk_vectors,allow_pickle=False)
        write_json(out/'transcript_index.json',chunks)
        contexts=['passage: '+' '.join(s['text'] for s in c['context']['before']) for c in candidates]
        context_vectors=encoder.encode(contexts,normalize_embeddings=True,show_progress_bar=False) if contexts else np.empty((0,vectors.shape[1]),np.float32)
        np.save(out/'context_embeddings.npy',context_vectors,allow_pickle=False)
        for i,c in enumerate(candidates):
            c['context_embedding_ref']={'file':'context_embeddings.npy','row':i}
    with timings.stage('previews'):
        (out/'previews').mkdir(exist_ok=True)
        preview_ids={c['slot_id'] for c in candidates if c['shortlist']}
        for c in sorted(candidates,key=lambda c:c['rank']):
            if len(preview_ids)>=cfg.get('preview_limit',30):break
            preview_ids.add(c['slot_id'])
        for c in candidates:
            c['preview_available']=c['slot_id'] in preview_ids
            if not c['preview_available']:continue
            start=max(0,int((c['time']-5)*sr)); end=min(len(audio),int((c['time']+5)*sr))
            clip=audio[start:end].copy()
            offset=int(c['time']*sr)-start
            n=min(int(.06*sr),len(clip)-offset)
            if n>0:
                beep=.12*np.sin(2*np.pi*1000*np.arange(n)/sr)*np.hanning(n)
                clip[offset:offset+n]+=beep[:,None]
            sf.write(out/c['preview_ref'],np.clip(clip,-1,1),sr,subtype='PCM_16')
    with timings.stage('output_report'):
        write_json(out/'words.json',words)
        write_json(out/'sentences.json',sentences)
        write_json(out/'candidates.json',candidates)
        write_json(out/'vad_intervals.json',speech)
        versions={}
        import importlib.metadata
        for package in ['numpy','torch','whisperx','silero-vad','sentence-transformers']:
            versions[package]=importlib.metadata.version(package)
        write_json(out/'meta.json',{'duration_s':duration,'config':cfg,'counts':counts,
            'versions':versions,'audio_reference':{'original_filename':Path(audio_path).name,
                'sha256':hash_file(audio_path)},
            'limitations':['Acoustic checks are estimates, not a guarantee of no missed speech.',
                'No sarcasm, stance, or final conversational acceptance is decided offline.',
                'Timing evidence is uncalibrated. Sensitive flags do not erase editorial scores.']})
        with (out/'candidates.csv').open('w',newline='',encoding='utf-8') as f:
            writer=csv.writer(f);writer.writerow(['slot_id','time','score','rank','shortlist','risk_flags','sensitive_flags'])
            for c in candidates:
                writer.writerow([c['slot_id'],c['time'],c['base_score'],c['rank'],c['shortlist'],','.join(c['risk_flags']),','.join(c['sensitive_flags'])])
        render_report(out,candidates,counts)
        # The full decoded episode is scratch, not a pre-cut deliverable.
        decoded.unlink()
    timings.save()
    return candidates


def hash_file(path):
    digest=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): digest.update(block)
    return digest.hexdigest()
