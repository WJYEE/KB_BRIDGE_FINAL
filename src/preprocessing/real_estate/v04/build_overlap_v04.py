"""상권 경계 SHP(상권구획도2024) 검수 → 부산 상권 공간 식별 → 조사 표 대응 → 상권–행정동 중첩표.
임대료·공실률 값은 읽지도 평균하지도 않는다(이름·유형·기간 메타데이터만 사용). 입력은 읽기 전용.

사용:
  python -I build_overlap_v04.py --sangkwon-shp <상권구획도2024 (확장자 없이)> --sgis-zip <SGIS 행정동 경계 zip>
        --v02-data <v02 데이터 폴더> --out <새 출력 폴더>
필요: pyshp, shapely(>=2), pyproj
"""
import argparse, collections, csv, io, json, math, re, sys, zipfile
from pathlib import Path
import shapefile
from pyproj import CRS, Transformer
from shapely import make_valid
from shapely.geometry import shape, mapping
from shapely.ops import transform, unary_union
from shapely.strtree import STRtree
from shapely.validation import explain_validity

ap = argparse.ArgumentParser()
ap.add_argument('--sangkwon-shp', required=True, type=Path)
ap.add_argument('--sgis-zip', required=True, type=Path)
ap.add_argument('--v02-data', required=True, type=Path)
ap.add_argument('--out', required=True, type=Path)
ap.add_argument('--force', action='store_true')
a = ap.parse_args()
if a.out.exists() and any(a.out.glob('*.csv')) and not a.force:
    sys.exit('출력 폴더에 CSV가 이미 있다(덮어쓰지 않음)')
a.out.mkdir(parents=True, exist_ok=True)

def wr(name, rows, cols=None):
    with (a.out / name).open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols or list(rows[0])); w.writeheader(); w.writerows(rows)

checks = []
def chk(item, result, verdict, note=''):
    checks.append({'확인항목': item, '결과': result, '판정': verdict, '비고': note})

# ------------------------------------------------------------------ 1. 상권 SHP 읽기·검수
shp_base = str(a.sangkwon_shp)
prj = Path(shp_base + '.prj').read_text(encoding='utf-8', errors='replace')
crs_src = CRS.from_wkt(prj)
r = shapefile.Reader(shp_base, encoding=Path(shp_base + '.cpg').read_text().strip().lower().replace('-', '') if Path(shp_base + '.cpg').exists() else 'utf-8')
fields = [f[0] for f in r.fields[1:]]
recs = r.records(); shapes = r.shapes()
chk('좌표계(.prj)', crs_src.name, '확인', f'EPSG 후보 {crs_src.to_epsg()}. 원본 단위 m(웹 메르카토르는 위도에 따라 면적이 왜곡되므로 면적은 EPSG:5179로 재계산)')
chk('도형 수', len(shapes), '확인', f'속성 필드 {fields}')
chk('도형 유형', dict(collections.Counter(s.shapeTypeName for s in shapes)), '확인')
to5179 = Transformer.from_crs(crs_src, CRS.from_epsg(5179), always_xy=True)
to4326 = Transformer.from_crs(crs_src, CRS.from_epsg(4326), always_xy=True)
rows_sk = []
geoms = {}
for i, (s, rec) in enumerate(zip(shapes, recs)):
    attrs = dict(zip(fields, rec))
    g0 = shape(s.__geo_interface__)
    valid0 = g0.is_valid
    why = '' if valid0 else explain_validity(g0)
    g = transform(to5179.transform, g0)
    repaired = ''
    if not g.is_valid:
        area_before = g.area
        g = make_valid(g)
        g = g if g.geom_type in ('Polygon', 'MultiPolygon') else unary_union([x for x in getattr(g, 'geoms', []) if x.geom_type in ('Polygon', 'MultiPolygon')])
        repaired = f'make_valid 적용(면적 변화 {abs(g.area - area_before) / max(area_before, 1):.4%})'
    lon, lat = to4326.transform(g0.centroid.x, g0.centroid.y)
    nm = str(attrs['sec_nm'])
    geoms[i] = g
    rows_sk.append({'행번호': i, 'year': int(attrs['year']), 'sec_seq': int(attrs['sec_seq']), 'sec_nm': nm, 'buld_nm': attrs['buld_nm'],
                    '파트수': len(g0.geoms) if g0.geom_type == 'MultiPolygon' else 1, '원본_유효': '유효' if valid0 else '무효', '무효사유': why,
                    '보정': repaired, '빈도형': g.is_empty, '면적_m2(EPSG5179)': round(g.area, 1), '면적_m2(웹메르카토르 원본)': round(g0.area, 1),
                    '중심_경도': round(lon, 6), '중심_위도': round(lat, 6)})
chk('원본 도형 무효', sum(x['원본_유효'] == '무효' for x in rows_sk), '통과' if all(x['원본_유효'] == '유효' for x in rows_sk) else '주의', '무효는 make_valid로 보정해 계산하고 표에 기록')
chk('빈 도형', sum(x['빈도형'] for x in rows_sk), '통과' if not any(x['빈도형'] for x in rows_sk) else '실패')
chk('year 값', sorted({x['year'] for x in rows_sk}), '확인')
names = collections.Counter(x['sec_nm'] for x in rows_sk)
chk('상권명 중복(정확 일치)', sum(n - 1 for n in names.values() if n > 1), '통과' if all(n == 1 for n in names.values()) else '주의')
nn = collections.Counter(re.sub(r'\s+', '', x['sec_nm']) for x in rows_sk)
chk('상권명 중복(공백 제거)', sum(n - 1 for n in nn.values() if n > 1), '통과' if all(n == 1 for n in nn.values()) else '주의')
chk('sec_seq 중복', sum(n - 1 for n in collections.Counter(x['sec_seq'] for x in rows_sk).values() if n > 1), '통과')
chk('이름 앞뒤 공백', sum(x['sec_nm'] != x['sec_nm'].strip() for x in rows_sk), '통과' if all(x['sec_nm'] == x['sec_nm'].strip() for x in rows_sk) else '주의')
wkb = collections.Counter(g.normalize().wkb_hex for g in geoms.values())
chk('도형 완전 중복', sum(n - 1 for n in wkb.values() if n > 1), '통과' if all(n == 1 for n in wkb.values()) else '주의')
lons = [x['중심_경도'] for x in rows_sk]; lats = [x['중심_위도'] for x in rows_sk]
chk('중심 좌표 범위(WGS84)', f'경도 {min(lons)}~{max(lons)}, 위도 {min(lats)}~{max(lats)}', '통과' if 124 < min(lons) and max(lons) < 132 and 33 < min(lats) and max(lats) < 39 else '실패', '한반도 범위 확인')

# 상권끼리 겹침(전국)
tree = STRtree([geoms[i] for i in range(len(geoms))])
pair_rows = []
for i in range(len(geoms)):
    for j in tree.query(geoms[i]):
        if j <= i: continue
        inter = geoms[i].intersection(geoms[j])
        if inter.area > 1:
            pair_rows.append({'상권A': rows_sk[i]['sec_nm'], '상권B': rows_sk[j]['sec_nm'], '겹침면적_m2': round(inter.area, 1),
                              'A대비_%': round(100 * inter.area / geoms[i].area, 2), 'B대비_%': round(100 * inter.area / geoms[j].area, 2)})
chk('상권–상권 겹침 쌍(전국, 1㎡ 초과)', len(pair_rows), '확인', '겹침이 있으면 같은 행정동 위의 중복 상권 처리가 필요')

# ------------------------------------------------------------------ 2. 행정동(SGIS, EPSG:5179) 읽기·검수
with zipfile.ZipFile(a.sgis_zip) as z:
    part = {ext: io.BytesIO(z.read(n)) for n in z.namelist() for ext in ('shp', 'shx', 'dbf') if n.lower().endswith('.' + ext)}
    sgis_prj = next(z.read(n).decode('utf-8', 'replace') for n in z.namelist() if n.lower().endswith('.prj'))
rd = shapefile.Reader(shp=part['shp'], shx=part['shx'], dbf=part['dbf'], encoding='utf-8')
dong = []
for s, rec in zip(rd.shapes(), rd.records()):
    g = shape(s.__geo_interface__)
    ok = g.is_valid
    if not ok: g = make_valid(g)
    dong.append({'code': rec[1], 'name': rec[2], 'base': rec[0], 'geom': g, 'valid': ok})
crs_d = CRS.from_wkt(sgis_prj)
chk('행정동 좌표계', crs_d.name, '확인', 'Korea 2000 Unified(EPSG:5179와 동일 투영) — 상권은 이 좌표계로 변환해 비교')
chk('행정동 수', len(dong), '확인', f"경계기준일 {sorted({d['base'] for d in dong})}")
chk('행정동 도형 무효', sum(not d['valid'] for d in dong), '통과' if all(d['valid'] for d in dong) else '주의')
busan = unary_union([d['geom'] for d in dong])
dtree = STRtree([d['geom'] for d in dong])
dong_area = {d['code']: d['geom'].area for d in dong}
chk('좌표 정합 확인', f"상권 bbox와 행정동 bbox 겹침: {bool(__import__('shapely').box(*busan.bounds).intersects(__import__('shapely').box(*unary_union([geoms[i] for i in range(len(geoms))]).bounds)))}", '확인')

# ------------------------------------------------------------------ 3. 부산 상권 공간 식별
for x in rows_sk:
    g = geoms[x['행번호']]
    inside = g.intersection(busan).area
    x['부산행정동_내_면적_m2'] = round(inside, 1)
    x['부산행정동_내_비율_%'] = round(100 * inside / g.area, 2) if g.area else 0
    x['중심점_부산행정동_내'] = 'Y' if busan.contains(g.centroid) else 'N'
    x['부산_공간식별'] = ('부산(95% 이상 부산 행정동 안)' if x['부산행정동_내_비율_%'] >= 95 else
                       ('부산 경계에 걸침(5~95%)' if x['부산행정동_내_비율_%'] >= 5 else ('부산 밖(5% 미만)' if x['부산행정동_내_비율_%'] > 0 else '부산 밖(겹침 없음)')))
    x['이름에_부산_포함'] = 'Y' if '부산' in x['sec_nm'] else 'N'
wr('02_상권경계_속성_검수_전국.csv', rows_sk)
bus = [x for x in rows_sk if not x['부산_공간식별'].startswith('부산 밖')]
wr('03_부산_상권_공간식별.csv', [{k: v for k, v in x.items() if k in ('sec_seq', 'sec_nm', 'buld_nm', '면적_m2(EPSG5179)', '부산행정동_내_비율_%', '중심점_부산행정동_내', '부산_공간식별', '이름에_부산_포함', '파트수', '원본_유효')} for x in sorted(bus, key=lambda x: x['sec_nm'])])
chk('공간적으로 식별한 부산 상권', len(bus), '확인', f"완전 부산 {sum(x['부산_공간식별'].startswith('부산(') for x in bus)}개, 경계 걸침 {sum(x['부산_공간식별'].startswith('부산 경계') for x in bus)}개")
chk('이름에 ‘부산’ 포함 상권(참고, 식별에 쓰지 않음)', sum(x['이름에_부산_포함'] == 'Y' for x in rows_sk), '참고')
tok = collections.Counter(t for x in bus for t in x['buld_nm'].split(','))
chk('부산 상권 수(유형 토큰별, 공간 식별 기준)', dict(tok), '확인', '공식 2024Q3 보도자료의 부산 상권 수(중대형 21, 소규모 21, 집합 16)와 비교')

# ------------------------------------------------------------------ 4. 조사 표 ↔ 상권 SHP 이름·유형 대응표
sk_by_name = {x['sec_nm']: x for x in rows_sk}
norm = lambda s: re.sub(r'[\s/·\-]', '', s)
by_norm = collections.defaultdict(list)
for x in rows_sk: by_norm[norm(x['sec_nm'])].append(x)
survey = list(csv.DictReader(open(a.v02_data / '05_조사지역_유형지표_범위.csv', encoding='utf-8-sig')))
types_of = {'소규모 상가': ['소규모'], '집합 상가': ['집합'], '일반 상가': ['중대형', '소규모'], '일반 상가(1층)': ['중대형', '소규모']}
cw = []
for s in survey:
    if s['지역단위'] != '조사상권': continue
    nm = s['조사지역']
    ex = sk_by_name.get(nm)
    cand = [x for x in by_norm.get(norm(nm), []) if x is not ex]
    toks = ex['buld_nm'].split(',') if ex else []
    need = types_of.get(s['상가유형'], [])
    if ex:
        in_bus = not ex['부산_공간식별'].startswith('부산 밖')
        status = '이름 정확 일치 + 공간상 부산' if in_bus else '이름 일치하나 공간상 부산 밖(동명 상권 가능성)'
        type_ok = '유형 일치' if any(t in toks for t in need) else '유형 불일치(상권 속성에 해당 유형 없음)'
    else:
        status = '이름 정확 일치 없음' + (f' (정규화 일치 후보 {cand[0]["sec_nm"]}, 확정 아님)' if cand else '')
        type_ok = ''
    cw.append({'조사지역': nm, '상가유형': s['상가유형'], '지표': s['지표'], '조사_최초분기': s['최초분기'], '조사_최종분기': s['최종분기'],
               'SHP_상권명': ex['sec_nm'] if ex else '', 'SHP_sec_seq': ex['sec_seq'] if ex else '', 'SHP_건물유형(buld_nm)': ex['buld_nm'] if ex else '',
               '부산_공간식별': ex['부산_공간식별'] if ex else '', '대응 상태': status, '유형 대응 점검': type_ok})
wr('04_조사상권명_SHP_대응표.csv', cw)
surv_names = sorted({s['조사지역'] for s in survey if s['지역단위'] == '조사상권'})
matched = [n for n in surv_names if n in sk_by_name and not sk_by_name[n]['부산_공간식별'].startswith('부산 밖')]
unmatched = [n for n in surv_names if n not in matched]
shp_only = sorted(x['sec_nm'] for x in bus if x['sec_nm'] not in surv_names)
chk('조사상권 이름(부산전체 제외)', len(surv_names), '확인')
chk('이름 일치 + 공간상 부산', len(matched), '확인')
chk('이름 일치 안 된 조사상권', unmatched, '확인', '이름만 비슷한 상권은 확정하지 않음')
chk('SHP 부산 상권 중 조사 표에 없는 것', shp_only, '확인', '조사 표에 값이 없거나 이름이 다른 상권')
chk('유형 불일치 행 수', sum(c['유형 대응 점검'].startswith('유형 불일치') for c in cw), '확인', '2024Q3 이후 조사 유형과 SHP buld_nm 비교. 개편 이전 전용 상권은 해당 없을 수 있음')

# ------------------------------------------------------------------ 5. 상권–행정동 중첩표(부산)
ov = []
dong_sk = collections.defaultdict(list)
for x in bus:
    g = geoms[x['행번호']]
    for j in dtree.query(g):
        d = dong[j]
        inter = g.intersection(d['geom'])
        if inter.area <= 0.5: continue
        pk = inter.area / g.area; pd_ = inter.area / dong_area[d['code']]
        rel = ('행정동이 상권을 포함' if pk >= 0.99 else ('상권이 행정동을 포함' if pd_ >= 0.99 else '일부 겹침'))
        sliver = 'Y' if pk < 0.01 else 'N'
        row = {'조사지역(SHP 상권명)': x['sec_nm'], 'sec_seq': x['sec_seq'], 'SHP_건물유형': x['buld_nm'], '행정동코드_SGIS': d['code'], '행정동명': d['name'],
               '겹침면적_m2': round(inter.area, 1), '상권면적_m2': round(g.area, 1), '행정동면적_m2': round(dong_area[d['code']], 1),
               '상권면적_대비_%': round(100 * pk, 2), '행정동면적_대비_%': round(100 * pd_, 2), '포함관계': rel,
               '미세겹침(상권의 1% 미만)': sliver, '상권이_부산_경계에_걸침': 'Y' if x['부산_공간식별'].startswith('부산 경계') else 'N'}
        ov.append(row); dong_sk[d['code']].append(row)
for row in ov:
    others = [o for o in dong_sk[row['행정동코드_SGIS']] if o['미세겹침(상권의 1% 미만)'] == 'N']
    row['같은_동_겹치는_상권수(미세 제외)'] = len(others)
    row['경계_출처'] = '상권구획도2024.shp (year=2024), 행정동 SGIS 2025-06-30'
    row['경계_적용기간'] = '2024Q3~ (2024년 판 경계. 이후 판 교체 여부 미확인)'
    row['개편이전(2024Q2 이하) 자료 연결'] = '미확정 — 별도 표(06) 참조'
    row['임대료·공실률 값'] = '미연결(평균·복제 없음)'
    row['해석 고지'] = '연결된 조사상권의 표본 기준 참고 지표이며 행정동 전체의 실제 공실률·임대료가 아님'
ov.sort(key=lambda r: (r['조사지역(SHP 상권명)'], -r['겹침면적_m2']))
wr('05_상권_행정동_중첩표.csv', ov)
# 상권별 합계 점검
chk('중첩표 행 수', len(ov), '확인', f"미세겹침(상권 1% 미만) {sum(r['미세겹침(상권의 1% 미만)'] == 'Y' for r in ov)}행 — 삭제하지 않고 표시")
gap = []
for x in bus:
    s_ = sum(r['겹침면적_m2'] for r in ov if r['sec_seq'] == x['sec_seq'])
    gap.append((x['sec_nm'], round(100 * s_ / geoms[x['행번호']].area, 2)))
chk('상권 면적 중 행정동과 겹친 비율이 95% 미만인 상권', [g for g in gap if g[1] < 95], '확인', '바다·하천·경계 어긋남 가능')

# 행정동 요약
dsum = []
for d in dong:
    rs = dong_sk.get(d['code'], [])
    main = [r_ for r_ in rs if r_['미세겹침(상권의 1% 미만)'] == 'N']
    covered = unary_union([geoms[next(x['행번호'] for x in bus if x['sec_seq'] == r_['sec_seq'])] for r_ in main]).intersection(d['geom']).area if main else 0
    dsum.append({'행정동코드_SGIS': d['code'], '행정동명': d['name'], '행정동면적_m2': round(dong_area[d['code']], 1), '겹치는 상권 수(미세 제외)': len(main),
                 '겹치는 상권': ' | '.join(r_['조사지역(SHP 상권명)'] for r_ in sorted(main, key=lambda z: -z['겹침면적_m2'])),
                 '상권들의 합집합이 행정동에서 차지하는 비율_%': round(100 * covered / dong_area[d['code']], 2),
                 '해석': '겹치는 상권 없음' if not main else ('상권 1개 겹침' if len(main) == 1 else '상권 여러 개 겹침 — 평균·복제 없이 개별 보관')})
wr('07_행정동별_겹치는상권_요약.csv', dsum)
dist = collections.Counter(len([r_ for r_ in dong_sk.get(d['code'], []) if r_['미세겹침(상권의 1% 미만)'] == 'N']) for d in dong)
chk('행정동별 겹치는 상권 수 분포(미세 제외)', dict(sorted(dist.items())), '확인', '키=상권 수, 값=행정동 수')
chk('한 상권이 걸치는 행정동 수 분포(미세 제외)', dict(sorted(collections.Counter(
    len([r_ for r_ in ov if r_['sec_seq'] == x['sec_seq'] and r_['미세겹침(상권의 1% 미만)'] == 'N']) for x in bus).items())), '확인')

# ------------------------------------------------------------------ 6. 적용기간·개편 이전 연결 표
q_by = collections.defaultdict(set)
for d in csv.DictReader(open(a.v02_data / '01_관측값_long.csv', encoding='utf-8-sig')):
    if d['기준분기'] and d['지역단위'] == '조사상권':
        q_by[d['조사지역']].add(d['기준분기'])
per = []
for nm in surv_names:
    qs = sorted(q_by.get(nm, []))
    ex = sk_by_name.get(nm)
    pre = [q for q in qs if q <= '2024Q2']; post = [q for q in qs if q >= '2024Q3']
    if not ex:
        st = '2024 경계 없음 — 경계 연결 불가'
    elif not pre:
        st = '2024Q3 개편 이후 신규 자료(이 상권은 개편 이전 자료 없음)'
    elif not post:
        st = '개편 이전에만 자료(2024 경계와 시기 불일치)'
    else:
        st = '이름은 개편 전후 이어지나 개편 이전 범위가 2024 경계와 같다는 근거 없음 — 개편 이전 분기 연결 미확정'
    per.append({'조사지역': nm, 'SHP에 이름 일치': 'Y' if ex else 'N', '조사 자료 최초분기': qs[0] if qs else '', '조사 자료 최종분기': qs[-1] if qs else '',
                '2024Q2 이하 분기 수': len(pre), '2024Q3 이상 분기 수': len(post), '2024 경계 적용 가능 구간': '2024Q3~' if ex and post else '',
                '개편 이전 자료 연결': st, '근거': '공식 보도자료: 2024Q3 상권 재구획·추가(328→368). 개편 이전 경계 자료는 보유하지 않음'})
wr('06_경계_적용기간_개편이전_연결상태.csv', per)
chk('2024 경계와 이름이 일치하며 개편 이전 자료가 있는 상권', sum(p['개편 이전 자료 연결'].startswith('이름은') for p in per), '확인', '개편 이전 분기 연결은 별도 결정 필요')

# ------------------------------------------------------------------ 7. 부산 상권 경계(재투영) 파생 파일
feats = [{'type': 'Feature', 'properties': {'sec_seq': x['sec_seq'], 'sec_nm': x['sec_nm'], 'buld_nm': x['buld_nm'], 'year': x['year'], 'area_m2_5179': x['면적_m2(EPSG5179)']},
          'geometry': mapping(geoms[x['행번호']])} for x in bus]
(a.out / '부산_상권경계_2024_EPSG5179.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'name': '부산 상권(공간 식별) 2024 — 원본 상권구획도2024.shp를 EPSG:5179로 재투영, 도형 변형 없음(무효 도형만 make_valid)',
                                                              'crs': {'type': 'name', 'properties': {'name': 'urn:ogc:def:crs:EPSG::5179'}}, 'features': feats}, ensure_ascii=False), encoding='utf-8')
wr('01_검수표.csv', [{'확인항목': c['확인항목'], '결과': json.dumps(c['결과'], ensure_ascii=False) if not isinstance(c['결과'], (str, int, float)) else c['결과'], '판정': c['판정'], '비고': c['비고']} for c in checks])
if pair_rows: wr('08_상권간_겹침_전국.csv', pair_rows)
print(len(rows_sk), len(bus), len(ov))
