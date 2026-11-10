import json

from vnmacro.ingest import common

NO_PAUSE = common.HttpSettings(pause=0.0, retries=0)


class FakeResponse:
    def __init__(self, body: bytes, status_code: int = 200):
        self.status_code = status_code
        self.content = body
        self.text = body.decode()

    def raise_for_status(self) -> None:
        pass

    def json(self):
        return json.loads(self.content)


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls += 1
        return self.responses.pop(0)


def test_fetch_or_load_saves_raw_bytes(tmp_path):
    body = b'{"a": 1}'
    status, payload, rec = common.fetch_or_load(
        FakeSession([FakeResponse(body)]), "u", {}, tmp_path / "x.json", NO_PAUSE
    )
    assert (status, payload, rec["file"]) == ("ok", {"a": 1}, "x.json")
    assert (tmp_path / "x.json").read_bytes() == body


def test_fetch_or_load_rejects_invalid_without_saving(tmp_path):
    status, payload, rec = common.fetch_or_load(
        FakeSession([FakeResponse(b"[]")]),
        "u",
        {},
        tmp_path / "x.json",
        NO_PAUSE,
        is_valid=lambda p: bool(p),
    )
    assert (status, payload, rec["file"]) == ("invalid", None, None)
    assert not (tmp_path / "x.json").exists()


def test_fetch_or_load_reuses_existing_file(tmp_path):
    (tmp_path / "x.csv").write_text("A\n1\n")
    session = FakeSession([])
    status, payload, rec = common.fetch_or_load(
        session, "u", {}, tmp_path / "x.csv", NO_PAUSE, as_json=False
    )
    assert (status, payload, rec, session.calls) == ("existing", "A\n1\n", None, 0)
