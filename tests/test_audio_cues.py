import numpy as np
import unittest
from modular_agent.realtime.audio_cues import features, dtw_distance, CueMatcher, sample_times


class AudioCueTests(unittest.TestCase):
    def test_gain_invariant_and_distinguishes_tones(self):
        t=np.arange(16000)/16000
        a=features(.1*np.sin(2*np.pi*440*t))
        b=features(.4*np.sin(2*np.pi*440*t))
        c=features(.1*np.sin(2*np.pi*1800*t))
        assert dtw_distance(a,b)<1e-6
        assert dtw_distance(a,c)>.1

    def test_matcher_requires_review_and_abstains_empty(self):
        with self.assertRaises(ValueError):CueMatcher([dict(label='accelerate',human_reviewed=False)])
        t=np.arange(16000)/16000
        a=.1*np.sin(2*np.pi*440*t);b=.1*np.sin(2*np.pi*1800*t)
        matcher=CueMatcher([dict(label='accelerate',human_reviewed=True,features=features(a)),dict(label='decelerate',human_reviewed=True,features=features(b))])
        assert matcher.classify(a)['label']=='accelerate'
        assert matcher.classify(np.array([]))['label'] is None

    def test_audio_sample_clock_mapping(self):
        rows=[dict(sample_start=0,frames=100,t=.2,duration=.1),dict(sample_start=100,frames=100,t=.31,duration=.1)]
        s,t=sample_times(rows,1000)
        assert s.tolist()==[0,.1,.2]
        assert np.allclose(t,[.2,.31,.41])
        rows[1]['t']=.1
        with self.assertRaises(ValueError):sample_times(rows,1000)
        with self.assertRaises(ValueError):sample_times([],1000)

    def test_reviewed_intervals_build_only_matching_known_cues(self):
        import tempfile, json, wave
        from pathlib import Path
        from modular_agent.realtime.audio_cues import build_templates, read_mono
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);rate=48000
            x=(2000*np.sin(2*np.pi*440*np.arange(rate)/rate)).astype('<i2')
            with wave.open(str(root/'audio.wav'),'wb') as w:
                w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes(x.tobytes())
            assert len(read_mono(root/'audio.wav'))==16000
            (root/'summary.json').write_text(json.dumps(dict(audio=dict(sample_rate=rate))))
            (root/'audio-timestamps.jsonl').write_text(json.dumps(dict(sample_start=0,frames=rate,t=.2,duration=1)))
            result=build_templates(root,[dict(start=.3,end=.8,label='accelerate',human_reviewed=True),dict(start=.3,end=.8,label='low_swing',human_reviewed=False)],root/'bank.json')
            assert len(result['templates'])==1 and not result['verified']
            with self.assertRaises(ValueError):build_templates(root,[dict(start=0,end=.5,label='accelerate',human_reviewed=True)],root/'bank.json')

    def test_obstacle_audio_never_changes_motion(self):
        from modular_agent.realtime.audio_cues import cue_effect
        assert cue_effect('falling_obstacles')==dict(motion_hint=None,occlusion_hint=True)
        assert cue_effect('accelerate')==dict(motion_hint='accelerate',occlusion_hint=False)
        assert cue_effect(None)==dict(motion_hint=None,occlusion_hint=False)

    def test_low_entry_requires_fresh_specific_audio(self):
        from modular_agent.realtime.audio_cues import low_entry_authorized
        low=dict(motion_hint='low_swing',time=48.204,distance=.183,margin=.124)
        assert low_entry_authorized(low,49.)
        assert not low_entry_authorized(low,55.67)
        assert not low_entry_authorized(dict(low,motion_hint='decelerate',time=56.365),57.)
        assert not low_entry_authorized(dict(low,time=60.365,distance=.242,margin=.064),60.5)
        assert not low_entry_authorized(low,48.)
        assert not low_entry_authorized(None,55.)
