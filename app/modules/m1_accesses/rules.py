import csv,io
from app.config import COLUMNS
from app.errors import DomainError
from app.reasons import reject
def decode(raw):
    for encoding in ("utf-8-sig","gb18030"):
        try: return raw.decode(encoding),encoding
        except UnicodeDecodeError: continue
    raise DomainError("ENCODING","无法识别文件编码")
def evaluate(raw,context=None):
    text,encoding=decode(raw)
    if not text: raise DomainError("EMPTY_FILE","文件为空")
    if not text.strip(): raise DomainError("BLANK_ONLY","全部为空行")
    stream=csv.reader(io.StringIO(text,newline=""));header=next(stream,None)
    normalized=[name.strip() for name in (header or [])]
    # 允许同名列换序重发，但缺列、多列或改名仍按坏表头拒绝
    if set(normalized)!=set(COLUMNS) or len(normalized)!=len(set(normalized)): raise DomainError("BAD_HEADER","表头不匹配")
    rows=[];bad=[];seen={};duplicate=blank=repeated=count=0
    try:
        for cells in stream:
            count+=1;line=stream.line_num
            if not cells or not any(c.strip() for c in cells): blank+=1;continue
            if [c.strip() for c in cells]==normalized: repeated+=1;continue
            row={"_line":line,"_sources":[line],"_raw":cells}
            if len(cells)!=len(header): bad.append(reject(row,"BAD_COLUMNS","列数不匹配"));continue
            row.update(dict(zip(normalized,[x.strip() for x in cells])))
            business_key=COLUMNS[0]
            if not row[business_key]: bad.append(reject(row,"EMPTY_VALUE","业务键为空"));continue
            key=row[business_key]
            if key in seen:
                previous=seen[key]
                # 按规范化后的列含义比较，列顺序不同但同值仍计重复
                if dict(zip(normalized,(c.strip() for c in cells)))=={k:previous[k] for k in normalized}: duplicate+=1
                else: bad.append(reject(row,"DUPLICATE_CONFLICT","同键不同值"))
                continue
            seen[key]=row;rows.append(row)
    except csv.Error: raise DomainError("BAD_CSV","引号未闭合或文件损坏")
    if count==0: raise DomainError("HEADER_ONLY","仅有表头")
    if not rows and not bad: raise DomainError("BLANK_ONLY","全部为空行")
    return {"rows":rows,"quarantine":bad,"metrics":{"input":count,"accepted":len(rows),"quarantine":len(bad),"duplicate":duplicate,"blank":blank,"repeated_headers":repeated,"encoding":encoding,"column_order":normalized,"reordered":normalized!=COLUMNS}}
