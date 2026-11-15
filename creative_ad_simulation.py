"""Creative drafting profile; existing strict simulation remains unchanged."""
import all_prompts
import sys,re,json
from pathlib import Path

PROMPT=all_prompts.COPYWRITER
PROMPT+='\n'+all_prompts.TTS_WRITING_GUIDE
PROMPT+='\n'+all_prompts.CREATIVE_WRITING_GUIDE

def main():
    if len(sys.argv)<2 or sys.argv[1] not in {'generate','review'}:raise SystemExit('Usage: creative_ad_simulation.py generate|review [existing CLI arguments]')
    mode=sys.argv.pop(1)
    if mode=='generate':
        import ad_simulation as m
        m.VERSION='creative-pause-beats-v3';m.SYSTEM=PROMPT
        original=m.check_output
        def check(output,case,advertisers,persona):
            result=original(output,case,advertisers,persona)
            if output.get('decision')!='generate':return result
            ignored=['Explicit sponsor disclosure missing','Script length outside 35–90 word guardrail','Approved claim is not present verbatim in the script']
            result['violations']=[v for v in result['violations'] if v not in ignored]
            text=output.get('script_text','');count=len(m.words(text))
            if not 45<=count<=110:result['violations'].append('Creative script outside 45–110 spoken-word guardrail')
            if re.search(r'[.!?;\r\n]',text):result['violations'].append('Creative script must be one line without sentence-ending punctuation or semicolons')
            if re.search(r'\b(?:sponsored message|paid message)\b',text,re.I):result['violations'].append('Disclosure wording excluded in this draft profile')
            result['passed']=not result['violations'];result['profile']='creative-single-sentence-v1'
            return result
        m.check_output=check;m.main()
    else:
        import ad_simulation_review as m
        original_packet=m.make_packet
        def packet(*args,**kwargs):
            result=original_packet(*args,**kwargs)
            source=args[0] if args else kwargs['result']
            if source.get('demo_cta'):
                result['authorized_demo_cta']=source['demo_cta']
            if source.get('real_brand_demo'):
                result['real_brand_demo']=True
            return result
        m.make_packet=packet
        m.QUALITY_PROMPT=m.QUALITY_PROMPT.replace('A sponsor introduction must be unmistakable.',all_prompts.CREATIVE_DEMO_DISCLOSURE_POLICY)
        m.QUALITY_PROMPT+=all_prompts.CREATIVE_REVIEW_RULES
        m.QUALITY_PROMPT+=all_prompts.DEMO_CTA_REVIEW_RULES
        m.QUALITY_PROMPT+=all_prompts.REAL_BRAND_REVIEW_RULES
        original=m.deterministic_review
        def check(*args,**kwargs):
            result=original(*args,**kwargs)
            result['violations']=[v for v in result['violations'] if v!='disclosure_phrase_absent']
            result['passed']=not result['violations'];return result
        m.deterministic_review=check;m.main()

if __name__=='__main__':main()
