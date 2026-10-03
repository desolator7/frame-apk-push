from urllib.error import HTTPError
from frame_apk_push.worker import error_message, execute
from frame_apk_push import core
import pytest


def test_pairing_403_has_actionable_headset_hint():
    message = error_message(HTTPError('http://frame:32000/register', 403, 'Forbidden', {}, None))
    assert 'Neuen Host koppeln' in message
    assert '403' in message


def test_upload_checks_original_hash_before_restaging(tmp_path, monkeypatch):
    apk = tmp_path / 'ChromePublic.apk'
    apk.write_bytes(b'changed')
    def forbidden(*args, **kwargs):
        pytest.fail('Restaging would overwrite the original hash')
    monkeypatch.setattr(core, 'stage_apk', forbidden)
    with pytest.raises(ValueError, match='verändert'):
        execute('upload', {'host': 'frame', 'metadata': {'apk': str(apk), 'sha256': 'old'}})
