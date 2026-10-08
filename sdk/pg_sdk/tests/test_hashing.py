from pg_sdk.hashing import canonical_json, content_hash, hash_json


def test_canonical_json_stable_regardless_of_key_order():
    a = canonical_json({"b": 2, "a": 1})
    b = canonical_json({"a": 1, "b": 2})
    assert a == b


def test_content_hash_differs_for_different_content():
    assert content_hash(b"one") != content_hash(b"two")


def test_content_hash_same_for_same_content():
    assert content_hash(b"same") == content_hash(b"same")


def test_hash_json_returns_hash_matching_its_own_bytes():
    digest, payload = hash_json({"x": 1})
    assert digest == content_hash(payload)
