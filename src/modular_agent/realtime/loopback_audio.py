"""Windows output-device loopback; no microphone or keyboard injection."""
import json
import math
import queue
import threading
import time
import wave
from pathlib import Path


def block_timing(info,received,frames,rate,origin):
    adc=info.get('input_buffer_adc_time',0.);current=info.get('current_time',0.)
    valid=all(math.isfinite(x) for x in (adc,current)) and adc>0 and current>0 and -.5<=current-adc<=2.
    start=received+(adc-current) if valid else received-frames/rate
    return dict(t=start-origin,received=received-origin,timestamp_source='portaudio_adc_to_perf_counter' if valid else 'callback_duration_estimate',duration=frames/rate,adc_time=adc,stream_current_time=current)

class LoopbackAudio:
    def __init__(self,device_index=None):
        import pyaudiowpatch as pa
        self.pa=pa;self.host=pa.PyAudio();self.stream=None;self.worker=None;self.errors=[];self.blocks=0;self.frames=0;self.peak=0;self.first_t=None;self.last_t=None;self.status_blocks=0;self.estimated_blocks=0
        try:
            self.device=self.host.get_default_wasapi_loopback() if device_index is None else self.host.get_device_info_by_index(device_index)
            if not self.device.get('isLoopbackDevice') or self.device['maxInputChannels']<1:raise ValueError('audio device must be a speaker loopback device')
            self.rate=int(self.device['defaultSampleRate']);self.channels=int(self.device['maxInputChannels'])
        except BaseException:self.host.terminate();raise
    def start(self,output,origin,stop):
        self.output=Path(output);self.origin=origin;self.stop=stop;self.queue=queue.Queue(maxsize=256)
        def write():
            try:
                with wave.open(str(self.output/'audio.wav'),'wb') as wav,(self.output/'audio-timestamps.jsonl').open('w',encoding='utf-8') as times:
                    wav.setnchannels(self.channels);wav.setsampwidth(2);wav.setframerate(self.rate)
                    while True:
                        item=self.queue.get()
                        if item is None:break
                        data,frames,metadata=item;metadata['sample_start']=self.frames;metadata['frames']=frames
                        if len(data)!=frames*self.channels*2:raise ValueError('audio block size mismatch')
                        wav.writeframesraw(data);times.write(json.dumps(metadata)+'\n')
                        import numpy as np
                        self.peak=max(self.peak,int(np.max(np.abs(np.frombuffer(data,dtype=np.int16).astype(np.int32))))) if data else self.peak
                        if self.first_t is None:self.first_t=metadata['t']
                        self.last_t=metadata['t']+frames/self.rate;self.frames+=frames;self.blocks+=1
                        self.status_blocks+=bool(metadata['status']);self.estimated_blocks+=metadata['timestamp_source']=='callback_duration_estimate'
            except Exception as error:self.errors.append(str(error));stop.set()
        self.worker=threading.Thread(target=write,daemon=True);self.worker.start()
        def callback(data,frames,info,status):
            received=time.perf_counter();metadata=block_timing(info,received,frames,self.rate,origin);metadata['status']=int(status)
            try:self.queue.put_nowait((data,frames,metadata))
            except queue.Full:self.errors.append('audio_queue_overflow');stop.set();return (None,self.pa.paAbort)
            return (None,self.pa.paContinue)
        self.stream=self.host.open(format=self.pa.paInt16,channels=self.channels,rate=self.rate,input=True,input_device_index=self.device['index'],frames_per_buffer=1024,stream_callback=callback,start=False)
        self.started=time.perf_counter()-origin;self.stream.start_stream()
    def close(self):
        try:
            if self.stream:
                self.stream.stop_stream();self.stream.close();self.stream=None
        finally:
            if self.worker:
                while self.worker.is_alive():
                    try:self.queue.put(None,timeout=.1);break
                    except queue.Full:pass
                self.worker.join();self.worker=None
            self.host.terminate()
    def summary(self):
        return dict(enabled=True,device=self.device['name'],device_index=self.device['index'],source='WASAPI speaker loopback (all sound on selected output)',microphone=False,sample_rate=self.rate,channels=self.channels,sample_frames=self.frames,blocks=self.blocks,first_sample_t=self.first_t,last_sample_t=self.last_t,peak_pcm16=self.peak,status_blocks=self.status_blocks,estimated_timestamp_blocks=self.estimated_blocks,errors=self.errors,wav='audio.wav',timestamps='audio-timestamps.jsonl',sync_limits='Per-block ADC time translated at callback to shared perf_counter. Driver latency/jitter uncalibrated; callback estimate explicitly marked when ADC unavailable. WAV samples are contiguous; gaps/status flags must be read from block timestamps.')
