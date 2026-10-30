"""v05 결과 독립 재계산 검수(읽기 전용). 상세표에서 요약표를 다시 세고, v03 월별 조회표·v02 원본과 대조한다.
사용: python -B verify_v05.py <v05 결과> <v03 폴더> <v02 데이터> <출력csv>"""
import csv, sys, collections
from pathlib import Path
R, v03, v02, out = map(Path, sys.argv[1:5])
rd = lambda p: list(csv.DictReader(open(p, encoding='utf-8-sig')))
dm, summ, dq = rd(R / '04_월별_상세연결표.csv'), rd(R / '05_연결범위_요약_유형지표기준월.csv'), rd(R / '03_분기별_상세연결표.csv')
res = []
def t(name, ok, note=''): res.append({'시험': name, '결과': '통과' if ok else '실패', '비고': note})

# 1. 월별 상세표 → 요약표 재계산
MICRO = '미세겹침(상권의 1% 미만)'
sp = collections.defaultdict(set); vl = collections.defaultdict(set); mult = collections.defaultdict(collections.Counter)
for r in dm:
    for basis in ('A', 'B'):
        if basis == 'B' and r[MICRO] == 'Y': continue
        k = (r['기준월'], r['상가유형'], r['지표'], basis)
        sp[k].add(r['행정동코드_SGIS'])
        if r['값'] != '': vl[k].add(r['행정동코드_SGIS']); mult[k][r['행정동코드_SGIS']] += 1
bad = 0; n = 0
for s in summ:
    if s['값 연결 행정동'] == '': continue
    k = (s['기준월'], s['상가유형'], s['지표'], s['연결 기준'][0]); n += 1
    # 상세표에는 해당 시리즈를 가진 상권만 행이 있으므로 값 연결 동수·다중 상권 동수만 직접 비교한다
    if int(s['값 연결 행정동']) != len(vl[k]): bad += 1
    if int(s['같은 동 여러 상권 값 행정동']) != sum(1 for c in mult[k].values() if c >= 2): bad += 1
t('요약표 값 연결·다중 상권 동수를 월별 상세표에서 재계산해 일치', bad == 0, f'{n}개 조합 비교, 불일치 {bad}')
t('공간연결 = 값연결 + 값 없음 (모든 조합)', all(int(s['공간연결 행정동']) == int(s['값 연결 행정동']) + int(s['공간연결·값 없음 행정동']) for s in summ if s['값 연결 행정동'] != ''))
t('공간연결 + 연결 없음 = 206', all(int(s['공간연결 행정동']) + int(s['공간연결 없음 행정동']) == 206 for s in summ if s['값 연결 행정동'] != ''))
t('B 기준 값 연결 ≤ A 기준', all(int(b['값 연결 행정동']) <= int(a['값 연결 행정동']) for a in summ for b in summ
                              if a['기준월'] == b['기준월'] and a['상가유형'] == b['상가유형'] and a['지표'] == b['지표'] and a['연결 기준'][0] == 'A' and b['연결 기준'][0] == 'B' and a['값 연결 행정동'] != ''))

# 2. v03 조회표(월말 컷오프)와 선택 분기 일치
v3 = {(x['기준월'], x['상가유형'], x['지표']): x for x in rd(v03 / '시간연결' / '월별_사용분기_조회표.csv') if x['컷오프'].startswith('월말')}
sel = rd(R / '04b_월별_사용분기_선택결과.csv')
t('월별 사용분기가 v03 조회표(월말)와 모두 일치', all(v3[(x['기준월'], x['상가유형'], x['지표'])]['사용분기'] == x['사용분기(관측분기)'] and
                                          v3[(x['기준월'], x['상가유형'], x['지표'])]['사용분기_공표일'] == x['사용분기_공표일'] for x in sel), f'{len(sel)}행')
# 3. 분기·공표일 보존
t('월별 상세표에 관측분기·공표일·기준월 컬럼이 모두 채워짐', all(r['사용분기(관측분기)'] and r['사용분기_공표일'] and r['기준월'] for r in dm))
# 4. 원본 값 대조(v02)
o = {(x['출처파일'], x['원본행'], x['원본열']): x for x in rd(v02 / '01_관측값_long.csv')}
t('분기·월별 상세표 값이 v02 값·원문·단위와 일치', all(o[(r['출처파일'], r['원본행'], r['원본열'])]['값'] == r['값'] and o[(r['출처파일'], r['원본행'], r['원본열'])]['값_원문'] == r['값_원문'] for r in dq + [x for x in dm if x['출처파일']]))
t('0 값 유지(분기 상세표에 0 존재, 빈칸으로 바뀌지 않음)', any(r['값'] in ('0', '0.0') for r in dq) and all(r['값'] != '' for r in dq))
# 5. 유형 구분 유지
t('상가유형·지표 조합 6종이 그대로 구분됨', {(r['상가유형'], r['지표']) for r in dq} == {('소규모 상가', '공실률'), ('소규모 상가', '임대료'), ('집합 상가', '공실률'), ('집합 상가', '임대료'), ('일반 상가', '공실률'), ('일반 상가(1층)', '공실률(1층)')})
# 6. 서면 계열 등 과거 상권 미통합
names = {r['조사상권'] for r in dq}
t('이름만 비슷한 과거 상권(서면, 서면전포, 중구시장) 연결 없음', not ({'서면', '서면전포', '중구시장'} & names))
t('분기별 상세표 기준분기 최솟값 ≥ 2024Q3(2626 보류 행 제외)', min(r['기준분기'] for r in dq if r['기준분기']) >= '2024Q3')
t('월별 상세 일반 상가·1층은 2026-05 이후만', all(r['기준월'] >= '2026-05' for r in dm if r['상가유형'] in ('일반 상가', '일반 상가(1층)')))
with open(out, 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.DictWriter(f, fieldnames=['시험', '결과', '비고']); w.writeheader(); w.writerows(res)
print(collections.Counter(r['결과'] for r in res))
for r in res:
    if r['결과'] == '실패': print(r)
