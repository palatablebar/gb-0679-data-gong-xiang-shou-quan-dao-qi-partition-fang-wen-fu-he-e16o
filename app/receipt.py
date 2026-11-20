"""接收身份与内容指纹。

每次物理送达（无论成功或失败）都生成唯一接收身份 receipt_id；
批次身份由与编码、列顺序无关的规范化内容指纹决定，同内容重发复用同一批次。
"""
import csv
import hashlib
import io
import json
import uuid
from datetime import datetime, timezone

from app.config import RULE_VERSION
from app.errors import DomainError
from app.modules.m1_accesses.rules import decode


def new_receipt_id():
    return uuid.uuid4().hex


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def canonicalize(raw):
    """把原始字节解析为与编码、列顺序无关的规范化文本并返回附带信息。

    返回 (canonical_text, encoding, header, column_order, raw_sha256)。
    解析失败时抛出 DomainError（与采信阶段同构），由调用方登记失败送达。
    """
    text, encoding = decode(raw)
    if not text:
        raise DomainError("EMPTY_FILE", "文件为空")
    if not text.strip():
        raise DomainError("BLANK_ONLY", "全部为空行")
    stream = csv.reader(io.StringIO(text, newline=""))
    header = next(stream, None)
    if header is None:
        raise DomainError("BLANK_ONLY", "全部为空行")
    column_order = [name.strip() for name in header]
    # 规范化表头按列名排序，使列顺序不参与内容指纹
    lines = ["\t".join(sorted(column_order))]
    count = 0
    try:
        for cells in stream:
            count += 1
            if not cells or not any(c.strip() for c in cells):
                lines.append("__BLANK__")
                continue
            if [c.strip() for c in cells] == [name.strip() for name in header]:
                lines.append("__HEADER__")
                continue
            if len(cells) != len(column_order):
                # 坏行无法按列对齐，按物理位置保留以保证指纹仍能区分内容差异
                lines.append("__BAD_COLUMNS__\t" + "\t".join(c.strip() for c in cells))
                continue
            paired = sorted(zip(column_order, (c.strip() for c in cells)), key=lambda item: item[0])
            lines.append("\t".join(name + "=" + value for name, value in paired))
    except csv.Error:
        raise DomainError("BAD_CSV", "引号未闭合或文件损坏")
    if count == 0:
        raise DomainError("HEADER_ONLY", "仅有表头")
    canonical = "\n".join(lines)
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    return canonical, encoding, column_order, [name.strip() for name in header], raw_sha256


def fingerprint(canonical_text, params=None):
    """规范化内容 + 参数 + 规则版本 → 稳定批次指纹。"""
    payload = canonical_text.encode("utf-8")
    payload += json.dumps(params or {}, sort_keys=True, ensure_ascii=False).encode("utf-8")
    payload += RULE_VERSION.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
