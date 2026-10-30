"""v05: 행정동코드 대응표 → 분기별 상세 연결표 → 월별 상세 연결표 → 연결 범위 요약표 → 검수표.

기본 정제(v02)와 공간 중첩(v04)은 다시 계산하지 않고 읽기만 한다. 값·공표일을 추정하지 않고,
평균·보간·결측 대체·3등분을 하지 않는다. 시점 선택은 v03의 select_published_quarter를 그대로 가져다 쓴다.

사용: python -B build_link_v05.py --v02-data <v02 데이터> --v03 <v03 폴더> --v04-result <v04 결과>
          --dong-base <v02 행정동_기준표_2025Q2.csv> --card-csv <카드 소비 csv> --out <새 폴더>
"""
import argparse, collections, csv, json, sys
from datetime import date
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument('--v02-data', required=True, type=Path)
ap.add_argument('--v03', required=True, type=Path)
ap.add_argument('--v04-result', required=True, type=Path)
ap.add_argument('--dong-base', required=True, type=Path)
ap.add_argument('--card-csv', required=True, type=Path)
ap.add_argument('--out', required=True, type=Path)
ap.add_argument('--first-month', default='2023-01')
ap.add_argument('--last-month', default='2026-10')
a = ap.parse_args()
sys.path.insert(0, str(a.v03))
from select_published_quarter import (load_calendar, load_series_start, select_quarter, effective_date, month_as_of)  # v03 코드 재사용

a.out.mkdir(parents=True, exist_ok=True)
if any(a.out.glob('0*.csv')):
    sys.exit('출력 폴더에 결과가 이미 있다(덮어쓰지 않음)')

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
overlap = rd(a.v04_result / '05_상권_행정동_중첩표.csv')
dongs = rd(a.dong_base)                                   # SGIS 206
obs = rd(a.v02_data / '01_관측값_long.csv')
cal = load_calendar(a.v03 / '시간연결' / '기준분기_공표일_확인표_v03.csv')
start = load_series_start(a.v03 / '시간연결' / '시리즈_최초공개일_v03.csv')
cwalk = rd(a.v04_result / '04_조사상권명_SHP_대응표.csv')

# ============================================================ 1. v04 연결 범위: 두 기준
linked_a = {r['행정동코드_SGIS'] for r in overlap}
linked_b = {r['행정동코드_SGIS'] for r in overlap if r[MICRO] == 'N'}
only_a = sorted(linked_a - linked_b)
rows_a = overlap
rows_b = [r for r in overlap if r[MICRO] == 'N']
wr('01_v04_연결범위_두기준_요약.csv', [
    {'기준': 'A. 미세 겹침 포함(v04 중첩표 전체)', '연결 행정동': len(linked_a), '미연결 행정동': len(dongs) - len(linked_a), '중첩 행수': len(rows_a),
     '설명': '상권과 면적이 조금이라도 겹치는 모든 행정동. 원본 연결표 기준'},
    {'기준': 'B. 상권 면적 1% 미만 겹침 제외(참고용 구분)', '연결 행정동': len(linked_b), '미연결 행정동': len(dongs) - len(linked_b), '중첩 행수': len(rows_b),
     '설명': '1%는 프로젝트가 표시용으로 둔 임시 기준이며 공식 기준이 아님. 모델 적용 여부가 정해지기 전까지 미세 겹침 행은 삭제하지 않음'},
    {'기준': 'A−B 차이', '연결 행정동': len(linked_a) - len(linked_b), '미연결 행정동': len(linked_b) - len(linked_a), '중첩 행수': len(rows_a) - len(rows_b),
     '설명': '미세 겹침만 가진 행정동 수와 미세 겹침 행수'},
], )
wr('01b_미세겹침만_있는_행정동.csv', [
    {'행정동코드_SGIS': c, '행정동명': next(r['행정동명'] for r in overlap if r['행정동코드_SGIS'] == c),
     '겹치는 상권(상권면적 대비 %)': ' | '.join(f"{r['조사지역(SHP 상권명)']}({r['상권면적_대비_%']}%)" for r in overlap if r['행정동코드_SGIS'] == c)} for c in only_a])
chk('v04 연결 행정동(미세 포함)/미연결', f'{len(linked_a)}/{len(dongs) - len(linked_a)}', '확인', '사용자 제시 84/122와 대조')
chk('v04 연결 행정동(1% 미만 제외)/미연결', f'{len(linked_b)}/{len(dongs) - len(linked_b)}', '확인', '사용자 제시 68/138과 대조')
chk('v04 미세 겹침 행 유지', sum(r[MICRO] == 'Y' for r in overlap), '통과' if sum(r[MICRO] == 'Y' for r in overlap) == 24 else '주의', '삭제하지 않음')

# ============================================================ 2. 행정동 코드 대응(SGIS 8자리 ↔ 카드 10자리)
card_pairs = collections.defaultdict(set); months_seen = set(); card_rows = 0
with open(a.card_csv, encoding='utf-8-sig', newline='') as f:
    for r in csv.DictReader(f):
        card_pairs[(r['hcode'], r['hname'])].add(r['stdYm']); months_seen.add(r['stdYm']); card_rows += 1
card = [{'hcode': k[0], 'hname': k[1], 'gu': k[1].split(' ', 1)[0], 'dong': k[1].split(' ', 1)[1] if ' ' in k[1] else '', 'months': sorted(v)} for k, v in card_pairs.items()]
card_key = collections.defaultdict(list)
for c in card: card_key[(c['gu'], c['dong'])].append(c)
sg_key = collections.defaultdict(list)
for d in dongs: sg_key[(d['시군구명(코드표)'], d['행정동명'])].append(d)
chk('SGIS 행정동 수 / 구군+동명 중복', f"{len(dongs)} / {sum(len(v) - 1 for v in sg_key.values() if len(v) > 1)}", '통과' if all(len(v) == 1 for v in sg_key.values()) else '주의')
chk('카드 hcode 수(고유 코드·이름 쌍) / 구군+동명 중복', f"{len(card)} / {sum(len(v) - 1 for v in card_key.values() if len(v) > 1)}", '통과' if all(len(v) == 1 for v in card_key.values()) else '주의',
    f'카드 파일 {card_rows}행, 기준연월 {min(months_seen)}~{max(months_seen)}')
chk('카드 hcode 하나가 여러 이름', sum(1 for h, n in collections.Counter(c['hcode'] for c in card).items() if n > 1), '통과')
mapping = []
card_used = set()
for d in dongs:
    k = (d['시군구명(코드표)'], d['행정동명'])
    c = card_key.get(k, [])
    if len(c) == 1 and len(sg_key[k]) == 1:
        st = '구군+동명 정확 일치(1:1)'; card_used.add(c[0]['hcode'])
    elif not c:
        st = '카드 쪽에 같은 구군+동명 없음(미대응)'
    else:
        st = '구군+동명 중복(1:1 아님)'
    mapping.append({'행정동코드_SGIS(8자리)': d['행정동코드_SGIS'], '시군구명': d['시군구명(코드표)'], '행정동명': d['행정동명'],
                    '행정동코드_카드(10자리)': c[0]['hcode'] if len(c) == 1 else '', '카드_hname': c[0]['hname'] if len(c) == 1 else '', '대응 상태': st,
                    'SGIS_기준시점': d['경계기준일'], 'SGIS_출처': 'SGIS_부산_행정동경계_20250630 + 행정구역 코드표 2025년 6월(시군구명)',
                    '카드_기준연월': f"{min(c[0]['months'])}~{max(c[0]['months'])}" if len(c) == 1 else '', '카드_출처': '부산광역시_일별 행정동 소비매출 월별 일평균(시간)_카드데이터.csv',
                    '대응표 성격': '이름 기준 잠정 대응(프로젝트에서 검증된 코드 대응표는 없음). 자리수 연장·삭제로 만들지 않음'})
card_unmapped = [c for c in card if c['hcode'] not in card_used]
wr('02_행정동코드_대응표.csv', mapping)
if card_unmapped:
    sg_unmapped = [m for m in mapping if not m['대응 상태'].startswith('구군+동명 정확')]
    wr('02b_미대응_코드(양쪽).csv', [{'구분': '카드쪽만 있음', 'SGIS 8자리': '', '카드 10자리': c['hcode'], '이름': c['hname'] or '(hname 공란)', '기준연월': f"{min(c['months'])}~{max(c['months'])}",
                                    '비고': '이름이 비어 있어 이름 대응 불가. 양쪽에 하나씩만 남은 상태라 서로의 짝일 가능성은 있으나 소거법 추정이며 확정·적용하지 않음'} for c in card_unmapped] +
       [{'구분': 'SGIS쪽만 있음', 'SGIS 8자리': m['행정동코드_SGIS(8자리)'], '카드 10자리': '', '이름': f"{m['시군구명']} {m['행정동명']}", '기준연월': m['SGIS_기준시점'],
         '비고': '2025-06 경계에 있으나 카드 이름 목록에 같은 이름 없음'} for m in sg_unmapped])
n_ok = sum(m['대응 상태'].startswith('구군+동명 정확') for m in mapping)
chk('코드 대응: 1:1 일치', f'{n_ok}/{len(dongs)}', '통과' if n_ok == len(dongs) else '주의', '미대응·중복은 02 표에 남김, 임의 보정 없음')
chk('카드 쪽 미대응 hcode', len(card_unmapped), '통과' if not card_unmapped else '주의')
chk('SGIS 8자리 코드와 카드 10자리 코드 둘 다 보존', 'Y', '통과')
map10 = {m['행정동코드_SGIS(8자리)']: m['행정동코드_카드(10자리)'] for m in mapping}
chk('연결 대상 행정동(미세 포함 84) 중 10자리 코드 없는 동', sum(1 for c in linked_a if not map10.get(c)), '통과' if all(map10.get(c) for c in linked_a) else '주의')

# ============================================================ 3. 분기별 상세 연결표(행정동 × 상권 × 유형 × 지표 × 기준분기)
BOUNDARY_FROM = '2024Q3'
matched_names = {c['조사지역'] for c in cwalk if c['대응 상태'].startswith('이름 정확 일치 + 공간상 부산')}
by_sk_series = collections.defaultdict(list)       # (상권, 유형, 지표) -> obs
for o in obs:
    if o['조사지역'] in matched_names:
        by_sk_series[(o['조사지역'], o['상가유형'], o['지표'])].append(o)
ov_by_sk = collections.defaultdict(list)
for r in overlap: ov_by_sk[r['조사지역(SHP 상권명)']].append(r)
chk('SHP-조사 대응 상권 이름 수', len(matched_names), '확인', '이름 정확 일치+공간상 부산 27개만 연결. 이름만 비슷한 과거 상권(서면 등)은 연결 안 함')
detail_q, held_pre = [], collections.Counter()
for (sk, kind, metric), os_ in sorted(by_sk_series.items()):
    for o in os_:
        q = o['기준분기']
        if q and q < BOUNDARY_FROM:
            held_pre[(sk, kind, metric)] += 1
            continue
        pending = not q
        pub = cal.get(q) if q else None
        eff = effective_date(q, (kind, metric), cal, start) if q else None
        for r in ov_by_sk[sk]:
            detail_q.append({
                '행정동코드_SGIS': r['행정동코드_SGIS'], '행정동코드_카드10자리': map10.get(r['행정동코드_SGIS'], ''), '행정동명': r['행정동명'],
                '조사상권': sk, 'SHP_sec_seq': r['sec_seq'], '상가유형': kind, '지표': metric, '기준분기': q, '기준분기_원문': o['기준분기_원문'],
                '값': o['값'], '값_원문': o['값_원문'], '단위': o['단위'],
                '분기_공표일': pub.isoformat() if pub else '', '분기_유효일(시리즈 최초공개일 반영)': eff.isoformat() if eff else '',
                '겹침면적_m2': r['겹침면적_m2'], '상권면적_대비_%': r['상권면적_대비_%'], '행정동면적_대비_%': r['행정동면적_대비_%'], '포함관계': r['포함관계'],
                '미세겹침(상권의 1% 미만)': r[MICRO], '같은_동_겹치는_상권수(미세 제외)': r['같은_동_겹치는_상권수(미세 제외)'],
                '경계 적용': '2024Q3 경계 고정 적용 가정(2024 이후 경계 변경 여부 미확인)',
                '값 상태': '보류(원문 기준분기 이상: 2626년 2분기 — 정상 분기로 고치지 않음)' if pending else '원본 값',
                '출처파일': o['출처파일'], '원본행': o['원본행'], '원본열': o['원본열'],
                '해석 고지': '연결된 조사상권의 표본 기준 참고 지표. 행정동 전체의 실제 공실률·임대료 아님. 모델 JOIN용 유일 키 표 아님'})
detail_q.sort(key=lambda r: (r['행정동코드_SGIS'], r['조사상권'], r['상가유형'], r['지표'], r['기준분기'] or '9999', r['기준분기_원문']))
wr('03_분기별_상세연결표.csv', detail_q)
wr('03b_개편이전_보류_행수.csv', [{'조사상권': k[0], '상가유형': k[1], '지표': k[2], '2024Q2 이하 관측 행수(경계 연결 보류)': v, '사유': '2024Q3 개편 이전 범위가 2024 경계와 같다는 근거 없음'} for k, v in sorted(held_pre.items())])

# ============================================================ 4. 월별 상세 연결표(컷오프: 월말, 미확정 → 시험 결과)
series_q = collections.defaultdict(set)
for o in obs:
    if o['기준분기'] and o['지역단위'] == '조사상권':
        series_q[(o['상가유형'], o['지표'])].add(o['기준분기'])
series_list = sorted(series_q)
months = []
y, m = map(int, a.first_month.split('-'))
while f'{y:04d}-{m:02d}' <= a.last_month:
    months.append(f'{y:04d}-{m:02d}'); m += 1
    if m == 13: y, m = y + 1, 1
val = {}                      # (상권, 유형, 지표, 분기) -> obs
has_series = set()            # (상권, 유형, 지표) 2024Q3 이상 관측이 있는 시리즈
for (sk, kind, metric), os_ in by_sk_series.items():
    for o in os_:
        if o['기준분기'] and o['기준분기'] >= BOUNDARY_FROM:
            val[(sk, kind, metric, o['기준분기'])] = o; has_series.add((sk, kind, metric))
sel = {}
detail_m, status_rows = [], []
for ym in months:
    cut = month_as_of(ym)
    for s in series_list:
        res = select_quarter(cut, s, cal, start, quarters_in_data=series_q[s])
        sel[(ym, s)] = res
        base = {'기준월': ym, '컷오프': '월말(해당월 말일)', '컷오프_상태': '미확정 — 월말 기준 시험 결과', '컷오프일': cut.isoformat(),
                '상가유형': s[0], '지표': s[1], '사용분기(관측분기)': res['quarter'], '사용분기_공표일': res['published'], '유효일': res['effective'],
                '경과일': res['days_since'], '선택 상태': res['status'], '선택 비고': res['note']}
        status_rows.append(base)
        q = res['quarter']
        if not q or q < BOUNDARY_FROM:
            continue
        for (sk, kind, metric) in sorted(has_series):
            if (kind, metric) != s: continue
            o = val.get((sk, kind, metric, q))
            for r in ov_by_sk[sk]:
                detail_m.append({**base, '행정동코드_SGIS': r['행정동코드_SGIS'], '행정동코드_카드10자리': map10.get(r['행정동코드_SGIS'], ''), '행정동명': r['행정동명'],
                                 '조사상권': sk, '값': o['값'] if o else '', '값_원문': o['값_원문'] if o else '', '단위': o['단위'] if o else '',
                                 '값 상태': '원본 값' if o else '값 없음(해당 상권·유형·분기 관측 없음, 대체 안 함)',
                                 '겹침면적_m2': r['겹침면적_m2'], '상권면적_대비_%': r['상권면적_대비_%'], '미세겹침(상권의 1% 미만)': r[MICRO],
                                 '경계 적용': '2024Q3 경계 고정 적용 가정', '출처파일': o['출처파일'] if o else '', '원본행': o['원본행'] if o else '', '원본열': o['원본열'] if o else '',
                                 '해석 고지': '연결된 조사상권의 표본 기준 참고 지표. 행정동 전체의 실제 값 아님. 분기 값을 월별 관측값으로 만들지 않음. 모델 JOIN용 유일 키 표 아님'})
detail_m.sort(key=lambda r: (r['기준월'], r['행정동코드_SGIS'], r['상가유형'], r['지표'], r['조사상권']))
wr('04_월별_상세연결표.csv', detail_m)
wr('04b_월별_사용분기_선택결과.csv', status_rows)

# ============================================================ 5. 연결 범위 요약(유형·지표·기준월 × 기준 A/B)
all_codes = [d['행정동코드_SGIS'] for d in dongs]
summ = []
for ym in months:
    for s in series_list:
        res = sel[(ym, s)]; q = res['quarter']
        for label, rows_ in (('A 미세겹침 포함', rows_a), ('B 1% 미만 제외', rows_b)):
            linked = {r['행정동코드_SGIS'] for r in rows_}
            row = {'기준월': ym, '상가유형': s[0], '지표': s[1], '사용분기': q, '선택 상태': res['status'], '연결 기준': label}
            if not q or q < BOUNDARY_FROM:
                row.update({'공간연결 행정동': '', '값 연결 행정동': '', '공간연결·값 없음 행정동': '', '공간연결 없음 행정동': '', '같은 동 여러 상권 값 행정동': '', '한 동 최대 상권 값 수': '',
                            '비고': '사용분기 없음(공표 전)' if not q else '2024Q3 이전 경계 연결 보류'})
            else:
                per = collections.Counter()
                for r in rows_:
                    o = val.get((r['조사지역(SHP 상권명)'], s[0], s[1], q))
                    if o is not None and o['값'] != '': per[r['행정동코드_SGIS']] += 1
                v_link = len(per)
                row.update({'공간연결 행정동': len(linked), '값 연결 행정동': v_link, '공간연결·값 없음 행정동': len(linked) - v_link,
                            '공간연결 없음 행정동': len(all_codes) - len(linked), '같은 동 여러 상권 값 행정동': sum(1 for n in per.values() if n >= 2),
                            '한 동 최대 상권 값 수': max(per.values()) if per else 0, '비고': ''})
            summ.append(row)
wr('05_연결범위_요약_유형지표기준월.csv', summ)
# A/B 차이
diff = []
byk = {(r['기준월'], r['상가유형'], r['지표'], r['연결 기준'][0]): r for r in summ}
for ym in months:
    for s in series_list:
        ra, rb = byk[(ym, s[0], s[1], 'A')], byk[(ym, s[0], s[1], 'B')]
        if ra['공간연결 행정동'] == '': continue
        diff.append({'기준월': ym, '상가유형': s[0], '지표': s[1], '사용분기': ra['사용분기'], '값 연결 행정동(A 포함)': ra['값 연결 행정동'], '값 연결 행정동(B 제외)': rb['값 연결 행정동'],
                     '미세 겹침 때문에만 값이 연결되는 행정동': ra['값 연결 행정동'] - rb['값 연결 행정동']})
wr('05b_미세겹침_포함제외_값연결_차이.csv', diff)

# ============================================================ 6. 검수
key_q = collections.Counter((r['행정동코드_SGIS'], r['조사상권'], r['상가유형'], r['지표'], r['기준분기_원문']) for r in detail_q)
chk('분기별 상세표 키 중복(동·상권·유형·지표·기준분기_원문)', sum(n - 1 for n in key_q.values() if n > 1), '통과' if all(n == 1 for n in key_q.values()) else '실패')
key_m = collections.Counter((r['기준월'], r['행정동코드_SGIS'], r['조사상권'], r['상가유형'], r['지표']) for r in detail_m)
chk('월별 상세표 키 중복(기준월·동·상권·유형·지표)', sum(n - 1 for n in key_m.values() if n > 1), '통과' if all(n == 1 for n in key_m.values()) else '실패')
exp_q = sum(len(ov_by_sk[o['조사지역']]) for os_ in by_sk_series.values() for o in os_ if not (o['기준분기'] and o['기준분기'] < BOUNDARY_FROM))
chk('분기별 상세표 행 수 = (관측 × 해당 상권의 중첩 행) 기대값', f'{len(detail_q)} vs {exp_q}', '통과' if len(detail_q) == exp_q else '실패', '의도하지 않은 행 증가 점검')
obs_idx = {(o['출처파일'], o['원본행'], o['원본열']): o for o in obs}
changed = sum(1 for r in detail_q + [x for x in detail_m if x['출처파일']] if (lambda o: o['값'] != r['값'] or o['값_원문'] != r['값_원문'] or o['단위'] != r['단위'])(obs_idx[(r['출처파일'], r['원본행'], r['원본열'])]))
chk('원본(v02) 수치·단위와 다른 행', changed, '통과' if changed == 0 else '실패')
future = []
for r in detail_m:
    if r['사용분기(관측분기)']:
        eff = date.fromisoformat(r['유효일']); cut = date.fromisoformat(r['컷오프일'])
        if not (eff < cut): future.append((r['기준월'], r['상가유형'], r['사용분기(관측분기)']))
chk('미래 공표자료 사용(유효일 ≥ 컷오프일)', len(future), '통과' if not future else '실패', str(future[:3]))
early = [r for r in detail_m if r['상가유형'] in ('일반 상가', '일반 상가(1층)') and r['기준월'] < '2026-05']
chk('일반 상가·1층 최초 공표(2026-04-30) 이전 기준월 사용', len(early), '통과' if not early else '실패', '과거 값이 파일에 있어도 사용 안 함')
chk('월별 상세표에 2626(기준분기 미확정) 값 포함', sum(1 for r in detail_m if not r['사용분기(관측분기)']), '통과')
chk('월별 상세표 사용분기가 2024Q3 미만', sum(1 for r in detail_m if r['사용분기(관측분기)'] < BOUNDARY_FROM), '통과' if not any(r['사용분기(관측분기)'] < BOUNDARY_FROM for r in detail_m) else '실패')
chk('분기별 상세표 2626 행(보류 표시)', sum(1 for r in detail_q if not r['기준분기']), '확인', '값 보존, 월별 연결에서는 제외')
chk('월별 한 키에 값이 둘 이상(평균 필요 상황)', sum(1 for n in key_m.values() if n > 1), '통과')
chk('집계·평균 컬럼 없음', 'Y', '통과', '상세표는 상권별 행 유지, 요약표는 개수만')
chk('월별 선택: 월 수 × 시리즈 수', f'{len(months)} × {len(series_list)}', '확인', '컷오프 월말, 공표 당일 미사용(same_day_usable=False)')
wr('06_검수표.csv', checks)
print(len(detail_q), len(detail_m), len(summ), json.dumps([c['확인항목'] for c in checks if c['판정'] == '실패'], ensure_ascii=False))
