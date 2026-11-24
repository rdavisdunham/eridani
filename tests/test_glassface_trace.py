import io
import json
import wave

from jarvis import glassface_dani, glassface_media as media, glassface_trace as trace
from jarvis.db import session_scope
from jarvis.models import BotCredential
from test_glassface_dani import key
from test_glassface_media import BODY, ROOT
from test_glassface_media import settings as settings

PROFILE = {"region": "eu", "public": "pk-lf-synthetic1", "secret": "sk-lf-synthetic1"}
TRACE = {"project": PROFILE, "trace_id": "1" * 32}


def test_credentials_stay_in_the_sealed_ticket(client):
    identity, headers = key(client, [glassface_dani.SCOPE])
    res = client.post(ROOT + "/tickets", headers=headers, json={**BODY, "diagnostics": TRACE})
    assert res.status_code == 200
    assert PROFILE["secret"] not in res.text
    with session_scope() as db:
        assert PROFILE["secret"] not in json.dumps(db.get(BotCredential, identity).glass_live_ticket)
    _, body = media.consume(res.json()["ticket"])
    assert body["diagnostics"] == TRACE
    assert PROFILE["secret"] not in json.dumps(media.glassface_media_stream.session_start("model", body["terminal"]))


def test_diagnostic_endpoint_auth_and_record(client, monkeypatch):
    records = []
    monkeypatch.setattr(trace, "upload", lambda *args: records.append(args))
    url = "/api/glassface/dani/diagnostics"
    form = {**TRACE, "name": "terminal.screen", "inputs": {}, "outputs": {"reply": "test"}}
    _, other = key(client, ["tasks:read"])
    assert client.post(url, headers=other, json=form).status_code == 403
    _, headers = key(client, [glassface_dani.SCOPE])
    assert client.post(url, headers=headers, json=form).json() == {"accepted": True}
    assert len(records) == 1
    assert records[0][1] == TRACE["trace_id"]
    assert records[0][4] == {"reply": "test"}
    assert client.post(url, headers=headers, json={**form, "wav": "not base64"}).status_code == 422


def test_timeline_contains_distinct_audio_lanes_and_redacts_credentials(monkeypatch):
    segments = []
    monkeypatch.setattr(trace, "background", lambda _, *args: segments.append(args))
    session = trace.Session(trace.Project(**PROFILE))
    session.event("provider-event", provider_type="session.output_audio.clear")
    session.audio("microphone", b"\xff" * 800)
    session.audio("model_voice", b"\x00" * 1600)
    session.audio("downlink", b"\x00" * 800)
    session.flush()
    assert len(segments) == 1
    _, identity, _, inputs, outputs, lanes = segments[0]
    assert identity == session.id
    assert outputs["timeline"][0]["provider_type"] == "session.output_audio.clear"
    assert {k: len(v) for k,v in lanes.items()} == {"microphone": 800, "model_voice": 1600, "downlink": 800}
    with wave.open(io.BytesIO(trace.wav_audio(lanes["microphone"]))) as audio:
        assert (audio.getframerate(), audio.getnframes()) == (8000, 800)
    assert trace.scrub({"ticket": "secret", "content": "sk-lf-synthetic-secret-value"}) == {"content":"[redacted]"}
