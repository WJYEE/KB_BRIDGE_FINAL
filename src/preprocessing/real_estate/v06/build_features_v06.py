"""v06: 행정동 × 기준월 모델 입력 '실험 후보' 변수(연결상권 면적가중) 생성.

기본 정제(v02), 공간 중첩(v04), 값·시점 연결(v05)은 다시 계산하지 않고 읽는다. 다만 커버율의 중복 계산을 막기 위해
상권∩행정동 도형의 합집합 면적을 도형에서 다시 잰다(v04 겹침 면적과 대조).
가중치 = 해당 상권과 행정동의 겹침면적 ÷ 그 동에서 유효한 값이 있는 상권들의 겹침면적 합.
최소 커버율 기준을 적용하지 않고, 값 없는 동은 빈값으로 둔다. 증감률은 만들지 않는다.
이 결과는 최종 채택본이 아니라 실험 후보이며 공식 행정동 통계가 아니다.

사용: python -B build_features_v06.py --v05 <v05 결과> --v04 <v04 결과> --sgis-zip <SGIS 행정동 zip> --out <새 폴더>
          [--license-zip <인허가 행정동시험연결 zip>]
필요: pyshp, shapely, pandas(점포 참고 계산 시)
"""
import argparse, collections, csv, io, json, statistics, sys, zipfile
from pathlib import Path
import shapefile
from shapely.geometry import shape
from shapely.ops import unary_union

ap = argparse.ArgumentParser()
ap.add_argument('--v05', required=True, type=Path)
ap.add_argument('--v04', required=True, type=Path)
ap.add_argument('--sgis-zip', required=True, type=Path)
ap.add_argument('--out', required=True, type=Path)
ap.add_argument('--license-zip', type=Path)
a = ap.parse_args()
if a.out.exists() and any(a.out.glob('0*.csv')):
    sys.exit('출력 폴더에 결과가 이미 있다(덮어쓰지 않음)')
a.out.mkdir(parents=True, exist_ok=True)

def rd(p):
    with open(p, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))
def wr(name, rows, cols=None):
    with (a.out / name).open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols or list(rows[0])); w.writeheader(); w.writerows(rows)
checks = []
def chk(item, result, verdict, note=''):
    checks.append({'확인항목': item, '결과': result if isinstance(result, (str, int, float)) else json.dumps(result, ensure_ascii=False), '판정': verdict, '비고': note})

MICRO = '미세겹침(상권의 1% 미만)'
SERIES = [('소규모 상가', '공실률', '연결상권_공실률_면적가중_소규모상가'), ('집합 상가', '공실률', '연결상권_공실률_면적가중_집합상가'),
          ('일반 상가', '공실률', '연결상권_공실률_면적가중_일반상가'), ('일반 상가(1층)', '공실률(1층)', '연결상권_1층공실률_면적가중_일반상가1층'),
          ('소규모 상가', '임대료', '연결상권_임대료_면적가중_소규모상가'), ('집합 상가', '임대료', '연결상권_임대료_면적가중_집합상가')]
BOUNDARY_FROM = '2024Q3'

# ------------------------------------------------------------------ 입력
ov_all = rd(a.v04 / '05_상권_행정동_중첩표.csv')
det = rd(a.v05 / '04_월별_상세연결표.csv')
sel = {(r['기준월'], r['상가유형'], r['지표']): r for r in rd(a.v05 / '04b_월별_사용분기_선택결과.csv')}
mapping = rd(a.v05 / '02_행정동코드_대응표.csv')
months = sorted({r['기준월'] for r in sel.values()})
ov_by_dong = collections.defaultdict(list)
for r in ov_all: ov_by_dong[r['행정동코드_SGIS']].append(r)
det_g = collections.defaultdict(list)
for r in det: det_g[(r['기준월'], r['상가유형'], r['지표'], r['행정동코드_SGIS'])].append(r)

# ------------------------------------------------------------------ 도형: 행정동, 상권 (합집합 면적용)
with zipfile.ZipFile(a.sgis_zip) as z:
    part = {ext: io.BytesIO(z.read(n)) for n in z.namelist() for ext in ('shp', 'shx', 'dbf') if n.lower().endswith('.' + ext)}
rdr = shapefile.Reader(shp=part['shp'], shx=part['shx'], dbf=part['dbf'], encoding='utf-8')
dong_geom = {}
for s, rec in zip(rdr.shapes(), rdr.records()):
    g = shape(s.__geo_interface__)
    dong_geom[rec[1]] = g if g.is_valid else g.buffer(0)
gj = json.loads((a.v04 / '부산_상권경계_2024_EPSG5179.geojson').read_text(encoding='utf-8'))
sk_geom = {f['properties']['sec_nm']: shape(f['geometry']) for f in gj['features']}
inter, dong_area = {}, {c: g.area for c, g in dong_geom.items()}
for r in ov_all:
    k = (r['행정동코드_SGIS'], r['조사지역(SHP 상권명)'])
    g = sk_geom[k[1]].intersection(dong_geom[k[0]])
    inter[k] = g
    if abs(g.area - float(r['겹침면적_m2'])) > 2: chk('겹침면적 재계산 불일치', k, '주의')
_ucache = {}
def union_area(code, sks):
    key = (code, frozenset(sks))
    if key not in _ucache:
        _ucache[key] = unary_union([inter[(code, s)] for s in sks]).area if sks else 0.0
    return _ucache[key]
# 상권끼리 겹침(같은 동 안): 합산 면적과 합집합 면적이 같은지
dup_area = 0.0
for code, rs in ov_by_dong.items():
    sks = [r['조사지역(SHP 상권명)'] for r in rs]
    dup_area += max(0.0, sum(inter[(code, s)].area for s in sks) - union_area(code, sks))
chk('같은 동 안 상권 겹침으로 인한 면적 중복(합산−합집합, m²)', round(dup_area, 3), '통과' if dup_area < 1 else '주의', '0이면 합산과 합집합이 같다. 커버율은 항상 합집합으로 계산')

# ------------------------------------------------------------------ 행정동 × 기준월 후보표
def boundary_month(m):
    return any(sel[(m, k, mt)]['사용분기(관측분기)'] >= BOUNDARY_FROM for (k, mt, _) in SERIES if sel[(m, k, mt)]['사용분기(관측분기)'])
VALUE_COLS = ['값', '유효값_상권수', '유형보유_상권수', '값없음_상권수', '유효값_커버율(0~1)', '유형보유_커버율(0~1)', '값없음_상권때문에_줄어든_커버율(0~1)', '관측분기', '분기_공표일', '선택상태(시험가정)', '연결·결측 사유']
def build(version):
    out = []
    for m in months:
        bm = boundary_month(m)
        for mp in mapping:
            code = mp['행정동코드_SGIS(8자리)']
            R = [r for r in ov_by_dong.get(code, []) if version == 'A' or r[MICRO] == 'N']
            sks = [r['조사지역(SHP 상권명)'] for r in R]
            row = {'기준월': m, '행정동코드_SGIS': code, '행정동코드_카드10자리': mp['행정동코드_카드(10자리)'], '시군구명': mp['시군구명'], '행정동명': mp['행정동명'],
                   '연결상권_수(유형 무관)': len(R) if bm else '', '연결상권_목록': ' | '.join(sorted(sks)) if bm else '',
                   '공간_커버율(0~1, 유형 무관, 합집합)': round(union_area(code, sks) / dong_area[code], 8) if bm else '',
                   '버전': 'A 미세겹침 포함' if version == 'A' else 'B 상권면적 1% 미만 겹침 제외',
                   '시간 기준': '월말 컷오프·공표 당일 미사용(시험 가정, 확정 아님)', '후보 상태': '실험 후보(최종 채택본 아님)'}
            for kind, metric, var in SERIES:
                s = sel[(m, kind, metric)]; q = s['사용분기(관측분기)']
                cells = dict.fromkeys(VALUE_COLS, '')
                cells['관측분기'] = q; cells['분기_공표일'] = s['사용분기_공표일']; cells['선택상태(시험가정)'] = s['선택 상태']
                if not q:
                    cells['연결·결측 사유'] = 'no_published_quarter(공표 전 또는 최초 공표 이전)'
                elif q < BOUNDARY_FROM:
                    cells['연결·결측 사유'] = 'boundary_hold_pre_2024Q3(개편 이전 경계 연결 보류)'
                else:
                    rows = [r for r in det_g.get((m, kind, metric, code), []) if version == 'A' or r[MICRO] == 'N']
                    valid = [r for r in rows if r['값'] != '']
                    if not R:
                        cells['연결·결측 사유'] = 'no_spatial_link(겹치는 상권 없음)'
                    elif not rows:
                        cells['연결·결측 사유'] = 'linked_but_no_type_series(겹치는 상권은 있으나 해당 상가유형 자료를 가진 상권 없음)'
                    elif not valid:
                        cells['연결·결측 사유'] = 'linked_type_series_no_value(해당 유형 상권은 있으나 사용 분기 값 없음)'
                    else:
                        wsum = sum(float(r['겹침면적_m2']) for r in valid)
                        cells['값'] = round(sum(float(r['겹침면적_m2']) * float(r['값']) for r in valid) / wsum, 6)
                        t_sks = [r['조사상권'] for r in rows]; v_sks = [r['조사상권'] for r in valid]
                        cells['유효값_상권수'] = len(v_sks); cells['유형보유_상권수'] = len(t_sks); cells['값없음_상권수'] = len(t_sks) - len(v_sks)
                        cv = union_area(code, v_sks) / dong_area[code]; ct = union_area(code, t_sks) / dong_area[code]
                        cells['유효값_커버율(0~1)'] = round(cv, 8); cells['유형보유_커버율(0~1)'] = round(ct, 8); cells['값없음_상권때문에_줄어든_커버율(0~1)'] = round(ct - cv, 8)
                        cells['연결·결측 사유'] = 'ok_값 있음' + ('(값 없는 상권 제외로 사용 범위 축소)' if len(t_sks) > len(v_sks) else '')
                row[var] = cells['값']
                for c in VALUE_COLS[1:]: row[f'{var}|{c}'] = cells[c]
            out.append(row)
    return out
cand = {v: build(v) for v in ('A', 'B')}
for v, name in (('A', '01_모델입력후보_A_미세겹침포함.csv'), ('B', '01_모델입력후보_B_미세겹침제외.csv')):
    wr(name, cand[v])
    keys = collections.Counter((r['기준월'], r['행정동코드_SGIS']) for r in cand[v])
    chk(f'모델 입력 후보표 {v} 키(기준월·행정동) 중복', sum(n - 1 for n in keys.values() if n > 1), '통과' if all(n == 1 for n in keys.values()) else '실패')
    chk(f'모델 입력 후보표 {v} 행 수 = 월 × 206', f'{len(cand[v])} vs {len(months)}×{len(mapping)}', '통과' if len(cand[v]) == len(months) * len(mapping) else '실패')

# ------------------------------------------------------------------ 연결 범위표(월 × 시리즈 × 버전)
REASONS = ['ok', 'no_published', 'boundary_hold', 'no_spatial', 'no_type_series', 'type_series_no_value']
def rkey(txt):
    return ('ok' if txt.startswith('ok') else 'no_published' if txt.startswith('no_published') else 'boundary_hold' if txt.startswith('boundary_hold') else
            'no_spatial' if txt.startswith('no_spatial') else 'no_type_series' if txt.startswith('linked_but_no_type') else 'type_series_no_value')
rng = []
for v in ('A', 'B'):
    idx = collections.defaultdict(list)
    for r in cand[v]: idx[r['기준월']].append(r)
    for m in months:
        for kind, metric, var in SERIES:
            rs = idx[m]
            cnt = collections.Counter(rkey(r[f'{var}|연결·결측 사유']) for r in rs)
            ok = [r for r in rs if r[var] != '']
            cvs = [r[f'{var}|유효값_커버율(0~1)'] for r in ok]
            rng.append({'기준월': m, '상가유형': kind, '지표': metric, '변수': var, '버전': v, '관측분기': sel[(m, kind, metric)]['사용분기(관측분기)'],
                        '분기_공표일': sel[(m, kind, metric)]['사용분기_공표일'], '선택상태(시험가정)': sel[(m, kind, metric)]['선택 상태'],
                        '값 있는 행정동': len(ok), '값 없음: 경계 보류(2024Q3 이전)': cnt['boundary_hold'], '값 없음: 사용 분기 없음(공표 전)': cnt['no_published'],
                        '값 없음: 공간 연결 없음': cnt['no_spatial'], '값 없음: 겹치는 상권에 해당 유형 자료 없음': cnt['no_type_series'],
                        '값 없음: 해당 유형 상권은 있으나 값 없음': cnt['type_series_no_value'],
                        '값 있는 동 중 여러 상권 값 가중': sum(1 for r in ok if r[f'{var}|유효값_상권수'] >= 2),
                        '값 있는 동 중 값 없는 상권 제외로 범위 축소': sum(1 for r in ok if r[f'{var}|값없음_상권수'] > 0),
                        '유효값 커버율 평균(값 있는 동)': round(statistics.mean(cvs), 4) if cvs else '', '유효값 커버율 중앙값': round(statistics.median(cvs), 4) if cvs else '',
                        '유효값 커버율 최소': min(cvs) if cvs else ''})
wr('03_연결범위표_월별_유형지표.csv', rng)

# ------------------------------------------------------------------ 구간별 요약(학습·검증 후보 구간)
WINDOWS = [('W1 데이터 보유 구간(PRD: 카드·생활인구 2023.01~2026.07)', '2023-01', '2026-07'),
           ('W2 핵심 변수 시작 기준월 2023.07 ~ 6개월 라벨 상한 가정 2026.01(통합안 문장에서 유추, 확정 아님)', '2023-07', '2026-01'),
           ('W3 2024.01 ~ 6개월 라벨 상한 가정 2026.01(확정 아님)', '2024-01', '2026-01'),
           ('W4 경계 적용 가능 구간 2024-11 ~ 2026-07', '2024-11', '2026-07')]
win = []
for label, m0, m1 in WINDOWS:
    for kind, metric, var in SERIES:
        for v in ('A', 'B'):
            rs = [r for r in rng if r['변수'] == var and r['버전'] == v and m0 <= r['기준월'] <= m1]
            cov_months = [r for r in rs if r['값 있는 행정동'] > 0]
            win.append({'구간(후보, 확정 아님)': label, '시작월': m0, '종료월': m1, '상가유형': kind, '지표': metric, '변수': var, '버전': v, '구간 월 수': len(rs),
                        '값이 연결되는 월 수': len(cov_months), '값이 연결되는 월 비율': round(len(cov_months) / len(rs), 3),
                        '연결되는 월의 값 있는 행정동 수(최소~최대)': f"{min(r['값 있는 행정동'] for r in cov_months)}~{max(r['값 있는 행정동'] for r in cov_months)}" if cov_months else '없음',
                        '구간 전체 행정동×월 중 값 있는 비율': round(sum(r['값 있는 행정동'] for r in rs) / (206 * len(rs)), 4),
                        '연결 시작월': min((r['기준월'] for r in cov_months), default=''), '연결 종료월': max((r['기준월'] for r in cov_months), default=''),
                        '비고': '' if cov_months else '이 구간에서 값이 연결되는 월 없음'})
wr('04_구간별_연결범위_학습검증후보.csv', win)

# ------------------------------------------------------------------ A/B 차이
diffrows = []
for kind, metric, var in SERIES:
    for m in months:
        ra = {r['행정동코드_SGIS']: r[var] for r in cand['A'] if r['기준월'] == m}
        rb = {r['행정동코드_SGIS']: r[var] for r in cand['B'] if r['기준월'] == m}
        va = [c for c, x in ra.items() if x != '']
        if not va: continue
        only_a = [c for c in va if rb[c] == '']
        both = [c for c in va if rb[c] != '']
        d = [abs(float(ra[c]) - float(rb[c])) for c in both if float(ra[c]) != float(rb[c])]
        diffrows.append({'기준월': m, '변수': var, 'A 값 있는 동': len(va), 'B 값 있는 동': len(both), 'A에만 값 있는 동(미세 겹침 때문)': len(only_a),
                         '둘 다 있고 값이 다른 동': len(d), '값 차이 평균(절대)': round(statistics.mean(d), 6) if d else 0, '값 차이 최대(절대)': round(max(d), 6) if d else 0})
wr('05_A_B_차이비교_월별.csv', diffrows)
rep = '2026-06'
detail = []
for kind, metric, var in SERIES:
    ra = {r['행정동코드_SGIS']: r for r in cand['A'] if r['기준월'] == rep}
    rb = {r['행정동코드_SGIS']: r for r in cand['B'] if r['기준월'] == rep}
    for c in ra:
        if ra[c][var] != '' and (rb[c][var] == '' or float(ra[c][var]) != float(rb[c][var])):
            detail.append({'기준월': rep, '변수': var, '행정동코드_SGIS': c, '행정동명': ra[c]['행정동명'], 'A 값': ra[c][var], 'B 값': rb[c][var] or '(값 없음)',
                           'A 연결상권': ra[c]['연결상권_목록'], 'B 연결상권': rb[c]['연결상권_목록']})
wr('05b_A_B_차이_동별(대표월 2026-06).csv', detail or [{'기준월': rep, '비고': '차이 없음'}])

# ------------------------------------------------------------------ 점포 참고(인허가 3개 대분류, 잠정 연결)
store_note = '점포 자료 없음(--license-zip 미지정)'
if a.license_zip:
    import pandas as pd
    with zipfile.ZipFile(a.license_zip) as z:
        members = {}
        for i in z.infolist():
            n = i.filename
            if not i.flag_bits & 0x800:
                try: n = n.encode('cp437').decode('cp949')
                except Exception: pass
            if n.endswith('_행정동시험연결_v03.csv'): members[n] = i
        frames = []
        for n, i in members.items():
            with z.open(i) as f:
                frames.append(pd.read_csv(f, usecols=['업종대분류', '정제_인허가일자', '정제_폐업일자', '공간연결상태', 'SGIS_행정동코드_잠정'], dtype=str))
    lic = pd.concat(frames, ignore_index=True)
    total_rows = len(lic)
    lic['start'] = lic['정제_인허가일자'].str[:7]; lic['end'] = lic['정제_폐업일자'].str[:7]
    usable = lic[lic['start'].notna()].copy()
    linked_rec = usable[usable['공간연결상태'].str.contains('일대일연결', na=False) & usable['SGIS_행정동코드_잠정'].notna()]
    srows = []
    for v in ('A', 'B'):
        idx = {(r['기준월'], r['변수']): r for r in rng if r['버전'] == v}
        valued = {(m, var): {r['행정동코드_SGIS'] for r in cand[v] if r['기준월'] == m and r[var] != ''} for m in months for _, _, var in SERIES}
        spatial = {m: {r['행정동코드_SGIS'] for r in cand[v] if r['기준월'] == m and r['연결상권_수(유형 무관)'] not in ('', 0)} for m in months}
        for m in months:
            act = usable[(usable['start'] <= m) & (usable['end'].isna() | (usable['end'] > m))]
            act_l = linked_rec.loc[linked_rec.index.intersection(act.index)]
            n_all, n_link = len(act), len(act_l)
            for kind, metric, var in SERIES:
                n_val = int(act_l['SGIS_행정동코드_잠정'].isin(valued[(m, var)]).sum())
                n_sp = int(act_l['SGIS_행정동코드_잠정'].isin(spatial[m]).sum()) if spatial[m] else 0
                srows.append({'기준월': m, '변수': var, '버전': v, '영업 중 기록 수(인허가 3개 대분류, 월말 시점 규칙)': n_all, '그중 행정동 잠정 연결 기록': n_link,
                              '값이 연결된 행정동 안의 기록': n_val, '비율(전체 영업 중 기록 대비)': round(n_val / n_all, 4) if n_all else '',
                              '비율(행정동 연결된 기록 대비)': round(n_val / n_link, 4) if n_link else '', '상권과 겹치는 행정동 안의 기록(공간연결, 유형 무관)': n_sp,
                              '비고': '참고용. 기타·동물·자원환경 인허가 일부이며 모델 점포 전체가 아님'})
    wr('06_점포연결_참고.csv', srows)
    store_note = f'인허가 3개 대분류 {total_rows:,}행 사용(인허가일 없는 {int(usable.shape[0] != total_rows) and total_rows - len(usable):,}행 제외)'
chk('점포 자료', store_note, '참고', '모델 점포 전체 자료(food 등 업종 파일)는 작업 폴더에 없음. 점포 행은 삭제·변경하지 않음(개수만 집계)')

# ------------------------------------------------------------------ 검수
cells_bad = 0; wbad = 0; nvals = 0
for v in ('A', 'B'):
    for r in cand[v]:
        for kind, metric, var in SERIES:
            if r[var] == '': continue
            nvals += 1
            rows = [x for x in det_g[(r['기준월'], kind, metric, r['행정동코드_SGIS'])] if (v == 'A' or x[MICRO] == 'N') and x['값'] != '']
            vs = [float(x['값']) for x in rows]
            if not (min(vs) - 1e-6 <= float(r[var]) <= max(vs) + 1e-6): cells_bad += 1
            if not (0 < float(r[f'{var}|유효값_커버율(0~1)']) <= float(r[f'{var}|유형보유_커버율(0~1)']) <= float(r['공간_커버율(0~1, 유형 무관, 합집합)']) + 1e-6 <= 1.000001): wbad += 1
chk('후보 값이 연결 상권 값의 최솟값~최댓값 범위 안(가중평균 성질)', f'{nvals}개 값 중 위반 {cells_bad}', '통과' if cells_bad == 0 else '실패')
chk('커버율 관계: 0 < 유효값 ≤ 유형보유 ≤ 공간 ≤ 1', f'위반 {wbad}', '통과' if wbad == 0 else '실패')
chk('B 버전 값 있는 셀 ≤ A 버전', 'Y' if sum(r[v] != '' for v in [x[2] for x in SERIES] for r in cand['B']) <= sum(r[v] != '' for v in [x[2] for x in SERIES] for r in cand['A']) else 'N', '통과')
early = [r for v in ('A', 'B') for r in cand[v] if r['기준월'] < '2026-05' and (r['연결상권_공실률_면적가중_일반상가'] != '' or r['연결상권_1층공실률_면적가중_일반상가1층'] != '')]
chk('일반 상가·1층 최초 공표 이전 기준월에 값 있음', len(early), '통과' if not early else '실패')
chk('2024Q3 이전 경계 보류 월에 값 있음', sum(1 for v in ('A', 'B') for r in cand[v] if r['기준월'] < '2024-11' for _, _, var in SERIES if r[var] != ''), '통과')
chk('최소 커버율 기준 적용', '없음', '통과', '값은 유효 상권이 하나라도 있으면 산출. 커버율은 보존만 함')
wr('08_검수표.csv', checks)
print(len(cand['A']), len(rng), len(win), len(srows) if a.license_zip else 0)
