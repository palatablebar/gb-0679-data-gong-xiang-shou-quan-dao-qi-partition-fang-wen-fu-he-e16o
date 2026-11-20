import csv, io
from app.pipeline import execute, load_sample
from app.receipt import canonicalize, fingerprint, new_receipt_id
from app.config import COLUMNS
from app import store


def _reorder(raw, swap=(0, 1)):
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    order = list(range(len(COLUMNS)))
    order[swap[0]], order[swap[1]] = order[swap[1]], order[swap[0]]
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    for row in rows:
        writer.writerow([row[i] for i in order] if len(row) == len(COLUMNS) else row)
    return buf.getvalue().encode("utf-8"), [COLUMNS[i] for i in order]


def test_receipt_id_unique_per_delivery(sample):
    a = execute(sample)
    b = execute(sample)
    assert a["receipt_id"] != b["receipt_id"]
    assert a["run_id"] == b["run_id"]
    assert a["delivery_status"] == "created" and b["delivery_status"] == "merged"


def test_reencoded_resend_merges_same_batch():
    "换编码重发（GB18030 legacy 与 utf-8-sig dirty 同内容）归为一批"
    first = execute(load_sample("dirty.csv"))
    again = execute(load_sample("legacy.csv"))
    assert again["run_id"] == first["run_id"]
    assert again["delivery_status"] == "merged"
    assert len(store.history()) == 1


def test_reordered_columns_resend_merges(sample):
    "换列顺序重发归为一批，采信指标不变"
    first = execute(sample)
    reordered_raw, new_order = _reorder(sample)
    again = execute(reordered_raw)
    assert again["run_id"] == first["run_id"]
    receipts = store.list_receipts(first["run_id"])
    assert receipts[-1]["column_order"] == new_order
    # 直接走采信规则时保留换序事实
    from app.modules.m1_accesses.rules import evaluate
    metrics = evaluate(reordered_raw)["metrics"]
    assert metrics["reordered"] is True and metrics["column_order"] == new_order
    baseline = evaluate(sample)["metrics"]
    assert metrics["input"] == baseline["input"] and metrics["accepted"] == baseline["accepted"]


def test_canonical_fingerprint_ignores_encoding_and_order(sample):
    legacy = load_sample("legacy.csv")
    reordered, _ = _reorder(sample)
    f1 = fingerprint(canonicalize(sample)[0])
    f2 = fingerprint(canonicalize(legacy)[0])
    f3 = fingerprint(canonicalize(reordered)[0])
    assert f1 == f2 == f3


def test_real_value_change_creates_new_batch(sample):
    first = execute(sample)
    changed = sample.replace(b"00032,guest", b"00032,root", 1)
    second = execute(changed)
    assert second["run_id"] != first["run_id"]
    assert second["delivery_status"] == "created"
    assert len(store.history()) == 2


def test_merged_resend_does_not_inflate_counts(sample):
    first = execute(sample)
    execute(load_sample("legacy.csv"))
    execute(_reorder(sample)[0])
    run = store.get(first["run_id"])
    assert run["stages"][0]["metrics"]["accepted"] == first["stages"][0]["metrics"]["accepted"]
    assert run["stages"][5]["metrics"]["input"] == first["stages"][5]["metrics"]["input"]
    history = store.history()
    assert len(history) == 1 and history[0]["deliveries"] == 3


def test_failed_delivery_preserves_old_batch_and_keeps_raw(sample):
    first = execute(sample)
    before = store.get(first["run_id"])
    try:
        execute(b"bad")
        assert False
    except Exception as error:
        assert error.code == "HEADER_ONLY"
    # 旧批次与版本原样保留
    after = store.get(first["run_id"])
    assert after["version"] == before["version"] and after["decision"] == before["decision"]
    assert len(store.history()) == 1
    # 失败原文件仍登记且可追回
    failed = [r for r in store.list_receipts() if r["status"] == "failed"]
    assert len(failed) == 1 and failed[0]["run_id"] is None
    assert store.get_receipt(failed[0]["id"])["raw"] == b"bad"


def test_each_original_file_is_recoverable(sample):
    first = execute(sample)
    execute(load_sample("legacy.csv"))
    receipts = store.list_receipts(first["run_id"])  # 按送达先后排序
    raws = {r["id"]: store.get_receipt(r["id"])["raw"] for r in receipts}
    assert raws[receipts[0]["id"]] == sample
    assert raws[receipts[1]["id"]] == load_sample("legacy.csv")
    # 不同编码的原件字节不同，但归属于同一批次
    assert raws[receipts[0]["id"]] != raws[receipts[1]["id"]]
    assert len({r["run_id"] for r in receipts}) == 1


def test_archive_lists_every_delivery(sample):
    execute(sample)
    execute(load_sample("legacy.csv"))
    run = execute(_reorder(sample)[0])
    from app.archive import build_archive
    rows = list(csv.reader(io.StringIO(build_archive(run).encode("utf-8").decode("utf-8-sig"))))
    receipt_rows = [r for r in rows[1:] if r[3] == "receipt"]
    assert len(receipt_rows) == 3
    assert rows[0][:4] == ["run_id", "input_sha256", "rule_version", "kind"]
    assert any(r[3] == "quarantine" for r in rows[1:])


def test_receipts_api_and_404(client, sample):
    run = client.post("/api/runs", json={"sample": "dirty.csv"}).get_json()
    client.post("/api/runs", json={"sample": "legacy.csv"})
    listing = client.get("/api/receipts", query_string={"run_id": run["run_id"]}).get_json()["receipts"]
    assert len(listing) == 2 and {r["status"] for r in listing} == {"created", "merged"}
    raw = client.get("/api/receipts/" + listing[1]["id"] + "/raw")
    assert raw.status_code == 200 and raw.data == load_sample("legacy.csv")
    assert client.get("/api/receipts/nope").status_code == 404
    assert client.get("/api/receipts", query_string={"run_id": "nope"}).status_code == 404


def test_failed_upload_api_atomic_with_receipt(client):
    assert client.post("/api/runs", json={"csv": "bad"}).status_code == 422
    assert client.get("/api/runs").get_json()["runs"] == []
    failed = client.get("/api/receipts").get_json()["receipts"]
    assert len(failed) == 1 and failed[0]["status"] == "failed"
    assert client.get("/api/receipts/" + failed[0]["id"] + "/raw").status_code == 200


def test_resend_after_review_keeps_version(client):
    p = client.post("/api/runs", json={"sample": "dirty.csv"}).get_json()
    u = "/api/runs/" + p["run_id"] + "/review"
    client.post(u, json={"version": 1, "decision": "已复核"})
    again = client.post("/api/runs", json={"sample": "legacy.csv"}).get_json()
    assert again["run_id"] == p["run_id"] and again["version"] == 2
    assert again["decision"] == "已复核"


def test_new_receipt_id_is_unique():
    assert new_receipt_id() != new_receipt_id()
    assert len(new_receipt_id()) == 32
