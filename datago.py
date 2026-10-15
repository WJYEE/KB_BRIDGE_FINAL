"""공공데이터포털(data.go.kr) 범용 조회. URL + 디코딩 키만 넣으면 DataFrame 반환."""
import xml.etree.ElementTree as ET

import pandas as pd
import requests


def _xml_to_dict(el):
    kids = list(el)
    if not kids:
        return el.text
    out = {}
    for k in kids:
        v = _xml_to_dict(k)
        if k.tag in out:
            if not isinstance(out[k.tag], list):
                out[k.tag] = [out[k.tag]]
            out[k.tag].append(v)
        else:
            out[k.tag] = v
    return out


def _find_records(obj):
    """중첩 구조에서 '레코드 리스트(dict 리스트)'를 찾아 반환."""
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj):
            return obj
        for x in obj:
            r = _find_records(x)
            if r is not None:
                return r
    elif isinstance(obj, dict):
        for key in ("item", "items", "data", "list", "row", "records"):
            if key in obj:
                v = obj[key]
                if isinstance(v, dict) and "item" in v:
                    v = v["item"]
                if isinstance(v, dict):
                    v = [v]
                if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                    return v
        for v in obj.values():
            r = _find_records(v)
            if r is not None:
                return r
    return None


def _parse(r):
    txt = r.text.strip()
    if txt.startswith("{") or txt.startswith("["):
        return r.json()
    if txt.startswith("<"):
        root = ET.fromstring(txt)
        return {root.tag: _xml_to_dict(root)}
    raise ValueError(f"알 수 없는 응답 형식:\n{txt[:300]}")


def _total(obj):
    if isinstance(obj, dict):
        for k in ("totalCount", "total_count", "totalCnt", "matchCount", "count"):
            if k in obj:
                try:
                    return int(obj[k])
                except (TypeError, ValueError):
                    pass
        for v in obj.values():
            t = _total(v)
            if t is not None:
                return t
    return None


def fetch(url, key, rows=1000, max_pages=50, **extra):
    """
    url   : 요청 URL (엔드포인트)
    key   : 디코딩 인증키
    rows  : 페이지당 건수
    extra : API별 추가 파라미터 (예: sigunguCd="26110")
    """
    items, page = [], 1
    while page <= max_pages:
        params = {"serviceKey": key, "pageNo": page, "numOfRows": rows,
                  "resultType": "json", "type": "json", "_type": "json", **extra}
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = _parse(r)
        batch = _find_records(data)
        if batch is None:
            print("레코드 못 찾음. 원본 응답:")
            print(r.text[:1500])
            return pd.DataFrame()
        items.extend(batch)
        total = _total(data)
        print(f"page {page}: {len(batch)}건 (누적 {len(items)}" + (f"/{total})" if total else ")"))
        if total is None or len(items) >= total or len(batch) < rows:
            break
        page += 1
    df = pd.DataFrame(items)
    # 숫자처럼 생긴 컬럼은 숫자로
    for c in df.columns:
        conv = pd.to_numeric(df[c], errors="coerce")
        if conv.notna().sum() == df[c].notna().sum() and df[c].notna().any():
            df[c] = conv
    return df
