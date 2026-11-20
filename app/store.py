import sqlite3,json
from pathlib import Path
from app.config import DATA_DIR
from app.errors import DomainError
def connect():
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DATA_DIR/"records.db",timeout=20)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=20000")
    db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY,payload TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,decision TEXT NOT NULL DEFAULT '待复核')")
    db.execute("CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY,run_id TEXT,received_at TEXT NOT NULL,origin TEXT NOT NULL,encoding TEXT,column_order TEXT,input_sha256 TEXT,canonical_sha256 TEXT,status TEXT NOT NULL,error_code TEXT,error_message TEXT,raw BLOB NOT NULL)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_receipts_run ON receipts(run_id)")
    return db
def get(run_id):
    with connect() as db: row=db.execute("SELECT payload,version,decision FROM runs WHERE id=?",(run_id,)).fetchone()
    if not row: raise DomainError("NOT_FOUND","批次不存在",404)
    return {**json.loads(row[0]),"version":row[1],"decision":row[2]}
def latest():
    with connect() as db: row=db.execute("SELECT id FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()
    return get(row[0]) if row else None
def history():
    with connect() as db:
        rows=db.execute("SELECT id,version,decision FROM runs ORDER BY rowid DESC").fetchall()
        counts=dict(db.execute("SELECT run_id,COUNT(*) FROM receipts WHERE run_id IS NOT NULL AND status='merged' GROUP BY run_id").fetchall())
    return [{"run_id":i,"version":v,"decision":d,"deliveries":counts.get(i,0)+1} for i,v,d in rows]
def review(run_id,version,decision):
    if decision not in {"已复核","退回复核"}: raise DomainError("BAD_DECISION","复核状态无效")
    with connect() as db:
        cursor=db.execute("UPDATE runs SET version=version+1,decision=? WHERE id=? AND version=?",(decision,run_id,version))
        if cursor.rowcount!=1:
            if not db.execute("SELECT 1 FROM runs WHERE id=?",(run_id,)).fetchone(): raise DomainError("NOT_FOUND","批次不存在",404)
            raise DomainError("STALE_VERSION","版本已更新，请刷新",409)
    return get(run_id)
_RECEIPT_COLUMNS="id,run_id,received_at,origin,encoding,column_order,input_sha256,canonical_sha256,status,error_code,error_message"
def _receipt(row):
    item=dict(zip(_RECEIPT_COLUMNS.split(","),row))
    if item.get("column_order"): item["column_order"]=json.loads(item["column_order"])
    return item
def record_delivery(receipt):
    """在同一事务内登记送达，并在需要时新建批次。返回 (run, created)。

    并发同内容送达竞争建批时，输的一方回退为 merged，保证只有一个批次。
    """
    for attempt in range(2):
        try:
            with connect() as db:
                existing=db.execute("SELECT payload FROM runs WHERE id=?",(receipt["run_id"],)).fetchone()
                created=existing is None
                db.execute("INSERT INTO receipts(id,run_id,received_at,origin,encoding,column_order,input_sha256,canonical_sha256,status,error_code,error_message,raw) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           (receipt["receipt_id"],receipt["run_id"],receipt["received_at"],receipt.get("origin","unknown"),
                            receipt.get("encoding"),json.dumps(receipt.get("column_order"),ensure_ascii=False),
                            receipt.get("input_sha256"),receipt.get("canonical_sha256"),
                            "created" if created else "merged",receipt.get("error_code"),receipt.get("error_message"),receipt["raw"]))
                if created:
                    db.execute("INSERT INTO runs(id,payload) VALUES (?,?)",(receipt["run_id"],json.dumps(receipt["payload"],ensure_ascii=False)))
            return get(receipt["run_id"]),created
        except sqlite3.IntegrityError:
            if attempt==0: continue
            raise
def record_failure(receipt):
    """登记判定失败的送达：不创建批次、不改任何既有批次，原文件仍留存。"""
    with connect() as db:
        db.execute("INSERT INTO receipts(id,run_id,received_at,origin,encoding,column_order,input_sha256,canonical_sha256,status,error_code,error_message,raw) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (receipt["receipt_id"],None,receipt["received_at"],receipt.get("origin","unknown"),
                    receipt.get("encoding"),json.dumps(receipt.get("column_order"),ensure_ascii=False),
                    receipt.get("input_sha256"),receipt.get("canonical_sha256"),"failed",
                    receipt.get("error_code"),receipt.get("error_message"),receipt["raw"]))
def list_receipts(run_id=None):
    with connect() as db:
        if run_id is None:
            rows=db.execute("SELECT "+_RECEIPT_COLUMNS+" FROM receipts ORDER BY rowid DESC").fetchall()
        else:
            if not db.execute("SELECT 1 FROM runs WHERE id=?",(run_id,)).fetchone(): raise DomainError("NOT_FOUND","批次不存在",404)
            rows=db.execute("SELECT "+_RECEIPT_COLUMNS+" FROM receipts WHERE run_id=? ORDER BY rowid",(run_id,)).fetchall()
    return [_receipt(row) for row in rows]
def get_receipt(receipt_id):
    with connect() as db:
        row=db.execute("SELECT "+_RECEIPT_COLUMNS+",raw FROM receipts WHERE id=?",(receipt_id,)).fetchone()
    if not row: raise DomainError("NOT_FOUND","接收记录不存在",404)
    item=_receipt(row[:-1]);item["raw"]=row[-1]
    return item
