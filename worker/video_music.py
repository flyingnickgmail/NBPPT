"""A quiet original instrumental bed; no external recording or paid music asset."""
import numpy as np


def mix_original_bed(voice,rate):
    length=len(voice);bed=np.zeros(length,dtype=np.float32)
    # Gentle electric-piano arpeggios. This is reusable synthesis, not a film-specific edit.
    chords=[(130.8128,164.8138,195.9977,246.9417),
            (110.0,130.8128,164.8138,195.9977),
            (87.3071,110.0,130.8128,164.8138),
            (97.9989,130.8128,146.8324,195.9977)]
    for beat,start in enumerate(range(0,length,int(rate*1.2))):
        f=chords[(beat//8)%4][beat%4];n=min(int(rate*3.6),length-start)
        t=np.arange(n,dtype=np.float32)/rate
        envelope=(1-np.exp(-t*35))*np.exp(-t*1.7)
        tone=(np.sin(2*np.pi*f*t)+.25*np.sin(2*np.pi*2*f*t)+.08*np.sin(2*np.pi*3*f*t))*envelope*.014
        bed[start:start+n]+=tone
    # Duck from measured PCM energy, including pauses inside sentences.
    block=max(1,int(rate*.05));energy=np.array([np.sqrt(np.mean(voice[i:i+block]**2)) for i in range(0,length,block)])
    active=(energy>.003).astype(float)
    radius=8;active=np.maximum.reduce([np.roll(active,k) for k in range(-radius,radius+1)])
    smooth=np.convolve(active,np.ones(9)/9,mode='same')[:len(energy)]
    gain=np.interp(np.arange(length),np.arange(len(smooth))*block,1-.78*smooth)
    fade=min(int(rate*3),length//2)
    if fade:
        gain[:fade]*=np.linspace(0,1,fade);gain[-fade:]*=np.linspace(1,0,fade)
    mixed=voice+bed*gain
    if np.max(np.abs(mixed))>=1:
        raise ValueError('配音混音削波，拒绝发布')
    return mixed.astype(np.float32)
