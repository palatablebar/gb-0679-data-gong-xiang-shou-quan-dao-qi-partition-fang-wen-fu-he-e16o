import hashlib,json,time
from datetime import datetime,timezone
from app.config import RULE_VERSION
def manifest(raw,params,started,canonical_sha256=None):
    item={"input_sha256":hashlib.sha256(raw).hexdigest(),"rule_version":RULE_VERSION,"parameters":params,"generated_at":datetime.now(timezone.utc).isoformat(),"elapsed_ms":round((time.monotonic()-started)*1000,2)}
    if canonical_sha256: item["canonical_sha256"]=canonical_sha256
    return item
