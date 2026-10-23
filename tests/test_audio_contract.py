import json
from types import SimpleNamespace
import pytest
from gateway import audio_contract


@pytest.mark.parametrize('lufs,peak,valid',[(-16,-2,True),(-17.5,-2,False),(-16,-1.2,False),(-16.4,-1.9,True)])
def test_audio_gate_uses_encoded_measurements(monkeypatch,lufs,peak,valid):
    monkeypatch.setattr(audio_contract,'measure_loudness',lambda _: {'input_i':str(lufs),'input_tp':str(peak)})
    if valid:
        assert audio_contract.verify_loudness('trusted.mp4')=={'integrated_lufs':lufs,'true_peak_dbfs':peak}
    else:
        with pytest.raises(ValueError):audio_contract.verify_loudness('trusted.mp4')


def test_silent_audio_cannot_pass_loudness_check(monkeypatch):
    data={'input_i':'-inf','input_tp':'-inf','input_lra':'0','input_thresh':'-70','target_offset':'inf'}
    monkeypatch.setattr(audio_contract.subprocess,'run',lambda *a,**kw:SimpleNamespace(stderr=json.dumps(data)))
    with pytest.raises(ValueError,match='静音'): audio_contract.measure_loudness('trusted.mp4')
