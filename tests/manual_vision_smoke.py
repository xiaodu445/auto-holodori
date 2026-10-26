"""Local OCR and optional read-only desktop verification. Never prints recognized text."""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from modular_agent.perception import GeneralVision

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--desktop',action='store_true')
    args=parser.parse_args()
    if args.desktop:
        report=GeneralVision().observe(monitor=0)
        Path('runtime/desktop-vision-report.json').write_text(json.dumps(report.to_dict(),ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'windows':len(report.windows),'buttons':len(report.buttons),
            'texts':len(report.texts),'capabilities':report.capabilities,'timings_ms':report.timings_ms,
            'warnings':report.warnings},ensure_ascii=False))
        assert report.windows, 'No desktop windows found'
        assert report.capabilities['ocr']=='ok', 'OCR did not complete'
        assert report.capabilities['uia'] in ('ok','partial'), 'UI Automation did not complete'
        return
    image=Image.new('RGB',(900,300),'white')
    draw=ImageDraw.Draw(image)
    font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',42)
    draw.rectangle((80,80,650,170),outline='black',width=3)
    draw.text((120,90),'开始游戏 PLAY 123',font=font,fill='black')
    Path('runtime').mkdir(exist_ok=True)
    image.save('runtime/vision-fixture.png')
    report=GeneralVision().analyze(np.asarray(image)[:,:,::-1].copy())
    text=' '.join(t['text'] for t in report.texts)
    assert '开始游戏' in text and 'PLAY' in text and '123' in text, 'Chinese/English OCR fixture failed'
    assert report.buttons, 'Button shape not detected'
    assert any(t['button_ids'] for t in report.texts), 'Text was not associated with button'
    Path('runtime/vision-fixture-report.json').write_text(json.dumps(report.to_dict(),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'ocr_fixture_passed':True,'buttons':len(report.buttons),
        'texts':len(report.texts),'timings_ms':report.timings_ms,'warnings':report.warnings}))

if __name__=='__main__': main()
