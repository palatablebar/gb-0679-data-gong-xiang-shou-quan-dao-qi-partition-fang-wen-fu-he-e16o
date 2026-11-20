import hashlib,time
from app.config import ROOT,MODULES
from app.errors import DomainError
from app.values import scalar
from app.manifest import manifest
from app.receipt import canonicalize,fingerprint,new_receipt_id,now_iso
from app import store
from app.modules.m1_accesses.rules import evaluate as stage1
from app.modules.m2_resources.rules import evaluate as stage2
from app.modules.m3_grants.rules import evaluate as stage3
from app.modules.m4_conflicts.rules import evaluate as stage4
from app.modules.m5_partitions.rules import evaluate as stage5
from app.modules.m6_audit.rules import evaluate as stage6
from app.modules.m7_seals.rules import evaluate as stage7
STAGES=[stage1,stage2,stage3,stage4,stage5,stage6,stage7]
def load_sample(name):
    if name not in {"dirty.csv","clean.csv","legacy.csv"}: raise DomainError("BAD_SAMPLE","样例不存在",404)
    return (ROOT/"sample_data"/name).read_bytes()
def calculate(raw,params=None,stop=6,canonical_sha256=None):
    params=params or {};started=time.monotonic();context={"parameters":params,"raw":raw,"quarantine":[]};stages=[];rows=[]
    for index,stage in enumerate(STAGES[:stop+1]):
        result=stage(raw if index==0 else rows,context)
        result=scalar(result);rows=result["rows"]
        context["quarantine"].extend(result.get("quarantine",[]))
        if index==0: context["intake"]=result["metrics"]
        result["cumulative_quarantine"]=list(context["quarantine"])
        context[MODULES[index][0]]=result
        stages.append(result)
    return {"run_id":(canonical_sha256 or "")[:20] if canonical_sha256 else None,"stages":stages,"manifest":manifest(raw,params,started,canonical_sha256),"parameters":params}
def execute(raw,params=None,origin="api"):
    """每次送达形成唯一接收身份；同内容重发归并同一批次，原文件另存。

    判定失败时不触碰任何既有批次（恢复旧版），失败原文件仍作为失败送达留存可追回。
    """
    params=params or {}
    receipt_id=new_receipt_id();received_at=now_iso()
    try:
        canonical,encoding,column_order,_,raw_sha256=canonicalize(raw)
        canonical_sha256=fingerprint(canonical,params)
        run_id=canonical_sha256[:20]
        result=calculate(raw,params,canonical_sha256=canonical_sha256)
        result["run_id"]=run_id
        run,created=store.record_delivery({"receipt_id":receipt_id,"run_id":run_id,"received_at":received_at,"origin":origin,
                                           "encoding":encoding,"column_order":column_order,"input_sha256":raw_sha256,
                                           "canonical_sha256":canonical_sha256,
                                           "raw":raw,"payload":result})
        run["receipt_id"]=receipt_id
        run["delivery_status"]="created" if created else "merged"
        return run
    except DomainError as error:
        # 失败送达：保留原文件与失败原因，不新增批次、不改计数、不动旧版本
        info={"receipt_id":receipt_id,"received_at":received_at,"origin":origin,"raw":raw,
              "error_code":error.code,"error_message":error.message}
        try:
            canonical,encoding,column_order,_,raw_sha256=canonicalize(raw)
            info.update(encoding=encoding,column_order=column_order,input_sha256=raw_sha256,
                        canonical_sha256=fingerprint(canonical,params))
        except DomainError:
            info["input_sha256"]=hashlib.sha256(raw).hexdigest()
        store.record_failure(info)
        raise
def stage_preview(index,payload):
    if "rows" in payload and index>0:
        if not isinstance(payload["rows"],list) or any(not isinstance(row,dict) for row in payload["rows"]): raise DomainError("BAD_ROWS","记录需要对象列表")
        if not isinstance(payload.get("context",{}),dict): raise DomainError("BAD_CONTEXT","上下文需要对象")
        return scalar(STAGES[index](payload["rows"],payload.get("context",{"parameters":{},"quarantine":[]})))
    raw=payload.get("csv")
    raw=raw.encode() if isinstance(raw,str) else load_sample(payload.get("sample","dirty.csv"))
    # 预览不落库；仅在可规范化时附带内容指纹，不可解析的输入仍交给阶段1返回原有错误码
    try: canonical_sha256=fingerprint(canonicalize(raw)[0],payload.get("parameters",{}))
    except DomainError: canonical_sha256=None
    return calculate(raw,payload.get("parameters",{}),index,canonical_sha256)["stages"][-1]
