"""v07-2: 권장 초안(작은 겹침 제외 → 남은 연결에서만 면적가중평균) 생성과 전달 파일 정리.

처리 순서
  1) 작은 겹침을 제외할지 먼저 판단한다(상권면적 대비 겹침 % < --min-overlap-pct 인 연결 제외, 예외표에서 적용=Y 로 표시한 행만 예외).
  2) 남은 연결 중 해당 상가유형·지표에 사용 분기 값이 있는 상권만 모은다.
  3) 상권이 하나면 그 상권 값을 쓰고, 둘 이상이면 겹침면적 가중평균을 쓴다(가중치 = 겹침면적 ÷ 유효 상권 겹침면적 합).
  제외한 면적을 다른 행정동으로 옮기지 않는다. 최소 커버율 기준은 없다. 값 없는 동은 빈값. 증감률 없음.
시간 연결(v05 선택 결과: 월말 컷오프·공표 당일 미사용 '시험 가정')과 '2626년 2분기' 보류는 바꾸지 않는다.
이 결과는 실험 후보이며 공식 행정동 통계가 아니다.

사용: python -B build_delivery_v07.py --v04 .. --v05 .. --v06 .. --sgis-zip .. --exceptions 예외_후보_수동검토.csv --min-overlap-pct 1 --out <새 폴더>
"""
import argparse, collections, csv, io, json, shutil, sys, zipfile
from pathlib import Path
import shapefile
from shapely.geometry import shape
from shapely.ops import unary_union

ap = argparse.ArgumentParser()
for k in ('--v04', '--v05', '--v06', '--sgis-zip', '--exceptions', '--out'): ap.add_argument(k, required=True, type=Path)
ap.add_argument('--min-overlap-pct', type=float, default=1.0)
a = ap.parse_args()
if a.out.exists() and any(a.out.glob('*.csv')): sys.exit('출력 폴더에 결과가 이미 있다(덮어쓰지 않음)')
a.out.mkdir(parents=True, exist_ok=True)
rd = lambda p: list(csv.DictReader(open(p, encoding='utf-8-sig', newline='')))
def wr(name, rows, cols=None):
    with (a.out / name).open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols or list(rows[0])); w.writeheader(); w.writerows(rows)

SERIES = [('소규모 상가', '공실률', '연결상권_공실률_면적가중_소규모상가'), ('집합 상가', '공실률', '연결상권_공실률_면적가중_집합상가'),
          ('일반 상가', '공실률', '연결상권_공실률_면적가중_일반상가'), ('일반 상가(1층)', '공실률(1층)', '연결상권_1층공실률_면적가중_일반상가1층'),
          ('소규모 상가', '임대료', '연결상권_임대료_면적가중_소규모상가'), ('집합 상가', '임대료', '연결상권_임대료_면적가중_집합상가')]
BOUNDARY_FROM = '2024Q3'
ov = rd(a.v04 / '05_상권_행정동_중첩표.csv')
mapping = rd(a.v05 / '02_행정동코드_대응표.csv')
det = rd(a.v05 / '04_월별_상세연결표.csv')
sel = {(r['기준월'], r['상가유형'], r['지표']): r for r in rd(a.v05 / '04b_월별_사용분기_선택결과.csv')}
months = sorted({k[0] for k in sel})
code_of = {(m['시군구명'], m['행정동명']): m['행정동코드_SGIS(8자리)'] for m in mapping}

# ------------------------------------------------------------------ 1. 제외 판단(먼저)
exc = rd(a.exceptions)
force = {}
for e in exc:
    if e['적용(Y/N)'].strip().upper() != 'Y': continue
    force[(e['조사상권'], code_of[(e['시군구명'], e['행정동명'])])] = '포함' if e['검토 방향'].startswith('포함') else '제외'
kept, dropped = [], []
for r in ov:
    k = (r['조사지역(SHP 상권명)'], r['행정동코드_SGIS'])
    pk = float(r['상권면적_대비_%'])
    f = force.get(k)
    if f == '제외': why = '개별 예외(제외)'
    elif f == '포함': why = ''
    elif pk < a.min_overlap_pct: why = f'상권면적 대비 겹침 {a.min_overlap_pct:g}% 미만(실험 기준, 공식 기준 아님)'
    else: why = ''
    (dropped if why else kept).append({**r, '_why': why})
kept_keys = {(r['조사지역(SHP 상권명)'], r['행정동코드_SGIS']) for r in kept}
drop_by_dong = collections.defaultdict(list)
for r in dropped: drop_by_dong[r['행정동코드_SGIS']].append(r['조사지역(SHP 상권명)'])
wr('제외된_연결목록.csv', [{'조사상권': r['조사지역(SHP 상권명)'], '행정동코드_SGIS': r['행정동코드_SGIS'], '행정동명': r['행정동명'], '겹침면적_m2': r['겹침면적_m2'],
                       '상권면적_대비_%': r['상권면적_대비_%'], '행정동면적_대비_%': r['행정동면적_대비_%'], '제외 사유': r['_why'],
                       '비고': '원본 연결표(v04 05)에는 그대로 남아 있음. 제외한 면적을 다른 행정동에 옮기지 않음'} for r in sorted(dropped, key=lambda x: float(x['상권면적_대비_%']))])

# ------------------------------------------------------------------ 도형(커버율 합집합)
with zipfile.ZipFile(a.sgis_zip) as z:
    part = {e: io.BytesIO(z.read(n)) for n in z.namelist() for e in ('shp', 'shx', 'dbf') if n.lower().endswith('.' + e)}
rdr = shapefile.Reader(shp=part['shp'], shx=part['shx'], dbf=part['dbf'], encoding='utf-8')
dgeom = {rec[1]: (lambda g: g if g.is_valid else g.buffer(0))(shape(s.__geo_interface__)) for s, rec in zip(rdr.shapes(), rdr.records())}
gj = json.loads((a.v04 / '부산_상권경계_2024_EPSG5179.geojson').read_text(encoding='utf-8'))
sgeom = {f['properties']['sec_nm']: shape(f['geometry']) for f in gj['features']}
inter = {(r['조사지역(SHP 상권명)'], r['행정동코드_SGIS']): sgeom[r['조사지역(SHP 상권명)']].intersection(dgeom[r['행정동코드_SGIS']]) for r in ov}
_u = {}
def ua(code, sks):
    key = (code, frozenset(sks))
    if key not in _u: _u[key] = unary_union([inter[(s, code)] for s in sks]).area if sks else 0.0
    return _u[key]
darea = {c: g.area for c, g in dgeom.items()}

# ------------------------------------------------------------------ 2~3. 값 요약
kept_by_dong = collections.defaultdict(list)
for r in kept: kept_by_dong[r['행정동코드_SGIS']].append(r)
det_g = collections.defaultdict(list)
for r in det:
    if (r['조사상권'], r['행정동코드_SGIS']) in kept_keys: det_g[(r['기준월'], r['상가유형'], r['지표'], r['행정동코드_SGIS'])].append(r)
boundary_ok = {m: any(sel[(m, k, mt)]['사용분기(관측분기)'] >= BOUNDARY_FROM for k, mt, _ in SERIES if sel[(m, k, mt)]['사용분기(관측분기)']) for m in months}
TIME = '월말 컷오프·공표 당일 미사용(시험 가정, 프로젝트 확정 기준 아님)'
model_rows, detail_rows = [], []
for m in months:
    for mp in mapping:
        code = mp['행정동코드_SGIS(8자리)']
        R = kept_by_dong.get(code, []); sks = [r['조사지역(SHP 상권명)'] for r in R]
        key = f'{m}|{code}'
        base = {'행_키': key, '기준월': m, '행정동코드_SGIS': code, '행정동코드_카드10자리': mp['행정동코드_카드(10자리)'], '시군구명': mp['시군구명'], '행정동명': mp['행정동명']}
        mrow = dict(base); drow = dict(base)
        mrow['공간커버율_유형무관(0~1)'] = round(ua(code, sks) / darea[code], 8) if boundary_ok[m] else ''
        mrow['연결상권수_유형무관'] = len(R) if boundary_ok[m] else ''
        drow['연결상권목록(제외 후)'] = ' | '.join(sorted(sks)) if boundary_ok[m] else ''
        drow['작은 겹침으로 제외된 상권(이 동)'] = ' | '.join(sorted(drop_by_dong.get(code, []))) if boundary_ok[m] else ''
        drow['시간 기준'] = TIME; drow['후보 상태'] = '실험 후보(권장 초안, 최종 채택본 아님)'
        for kind, metric, var in SERIES:
            s = sel[(m, kind, metric)]; q = s['사용분기(관측분기)']
            val = cov = nval = ''
            d = {'요약방식': '', '유효상권수': '', '유형보유상권수': '', '값없음상권수': '', '유형보유커버율(0~1)': '', '관측분기': q, '분기_공표일': s['사용분기_공표일'], '선택상태(시험가정)': s['선택 상태'], '연결·결측 사유': ''}
            if not q: d['연결·결측 사유'] = 'no_published_quarter(공표 전 또는 최초 공표 이전)'
            elif q < BOUNDARY_FROM: d['연결·결측 사유'] = 'boundary_hold_pre_2024Q3(개편 이전 경계 연결 보류)'
            else:
                rows = det_g.get((m, kind, metric, code), []); valid = [r for r in rows if r['값'] != '']
                if not R: d['연결·결측 사유'] = 'no_spatial_link(제외 후 겹치는 상권 없음)'
                elif not rows: d['연결·결측 사유'] = 'linked_but_no_type_series(겹치는 상권에 해당 상가유형 자료 없음)'
                elif not valid: d['연결·결측 사유'] = 'linked_type_series_no_value(해당 유형 상권은 있으나 사용 분기 값 없음)'
                else:
                    w = [float(r['겹침면적_m2']) for r in valid]
                    val = round(sum(wi * float(r['값']) for wi, r in zip(w, valid)) / sum(w), 6)
                    nval = len(valid); t_sks = [r['조사상권'] for r in rows]; v_sks = [r['조사상권'] for r in valid]
                    cov = round(ua(code, v_sks) / darea[code], 8)
                    d.update({'요약방식': '단일 상권 값' if nval == 1 else f'겹침면적 가중평균({nval}개 상권)', '유효상권수': nval, '유형보유상권수': len(t_sks), '값없음상권수': len(t_sks) - nval,
                              '유형보유커버율(0~1)': round(ua(code, t_sks) / darea[code], 8),
                              '연결·결측 사유': 'ok_값 있음' + ('(값 없는 상권 제외로 사용 범위 축소)' if len(t_sks) > nval else '')})
                    d['유효상권'] = ' | '.join(sorted(v_sks))
            mrow[var] = val; mrow[f'{var}__유효값커버율(0~1)'] = cov; mrow[f'{var}__유효상권수'] = nval
            for c, v in d.items(): drow[f'{var}|{c}'] = v
            if f'{var}|유효상권' not in drow: drow[f'{var}|유효상권'] = d.get('유효상권', '')
        model_rows.append(mrow); detail_rows.append(drow)
wr('모델용_행정동x기준월_권장초안.csv', model_rows)
wr('상세관리_행정동x기준월_권장초안.csv', detail_rows)
for n in ('01_모델입력후보_A_미세겹침포함.csv', '01_모델입력후보_B_미세겹침제외.csv'):
    shutil.copy2(a.v06 / n, a.out / ('비교본_' + n.replace('01_모델입력후보_', '')))
schema = {'key': ['기준월', '행정동코드_SGIS'], '행_키': '기준월|행정동코드_SGIS (모델용·상세관리 두 파일을 잇는 키)',
          'dtype_str': ['행_키', '기준월', '행정동코드_SGIS', '행정동코드_카드10자리'], 'note': '행정동코드는 문자열로 읽을 것(엑셀로 열면 숫자로 바뀔 수 있음). pandas: dtype={"행정동코드_SGIS": str, "행정동코드_카드10자리": str}',
          'encoding': 'utf-8-sig', 'min_overlap_pct': a.min_overlap_pct, 'exceptions_applied': [list(k) + [v] for k, v in force.items()]}
(a.out / '스키마.json').write_text(json.dumps(schema, ensure_ascii=False, indent=1), encoding='utf-8')
print(len(model_rows), len(kept), len(dropped))
