import csv,io,json
from app import store
def build_archive(run):
    stream=io.StringIO(newline="");writer=csv.writer(stream)
    writer.writerow(["run_id","input_sha256","rule_version","kind","source_lines","reason","evidence"])
    meta=run["manifest"]
    for row in run["stages"][-1]["rows"]:
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"accepted",json.dumps(row.get("_sources",[])),row.get("status",""),json.dumps(row,ensure_ascii=False)])
    for row in run["stages"][-1].get("cumulative_quarantine",[]):
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"quarantine",json.dumps(row.get("_sources",[])),row.get("reason",""),json.dumps(row,ensure_ascii=False)])
    # 每次送达（含同内容重发）的原文件证据：归并批次不丢当次原件
    for receipt in store.list_receipts(run["run_id"]):
        evidence={"receipt_id":receipt["id"],"received_at":receipt["received_at"],"origin":receipt["origin"],
                  "encoding":receipt["encoding"],"column_order":receipt["column_order"],
                  "input_sha256":receipt["input_sha256"],"canonical_sha256":receipt["canonical_sha256"],
                  "status":receipt["status"]}
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"receipt",json.dumps([]),receipt["status"],json.dumps(evidence,ensure_ascii=False)])
    return "\ufeff"+stream.getvalue()
