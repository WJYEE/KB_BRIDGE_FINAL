"""전달 파일(권장 초안) 독립 검수. build 코드와 다른 방식으로 v04·v05 입력에서 다시 계산해 대조한다(읽기 전용).
사용: python -B verify_v07.py <전달용 폴더> <v04 결과> <v05 결과> <v06 결과> <v03 폴더> <출력 csv>"""
import csv, sys, collections, hashlib, re
from datetime import date
from pathlib import Path
D, v04, v05, v06, v03, out = map(Path, sys.argv[1:7])
rd = lambda p: list(csv.DictReader(open(p, encoding='utf-8-sig', newline='')))
SERIES = [('소규모 상가', '공실률', '연결상권_공실률_면적가중_소규모상가'), ('집합 상가', '공실률', '연결상권_공실률_면적가중_집합상가'),
          ('일반 상가', '공실률', '연결상권_공실률_면적가중_일반상가'), ('일반 상가(1층)', '공실률(1층)', '연결상권_1층공실률_면적가중_일반상가1층'),
          ('소규모 상가', '임대료', '연결상권_임대료_면적가중_소규모상가'), ('집합 상가', '임대료', '연결상권_임대료_면적가중_집합상가')]
res = []
def t(name, ok, note=''): res.append({'검수 항목': name, '결과': '통과' if ok else '실패', '비고': note})
model, detail = rd(D / '모델용_행정동x기준월_권장초안.csv'), rd(D / '상세관리_행정동x기준월_권장초안.csv')
ov, det = rd(v04 / '05_상권_행정동_중첩표.csv'), rd(v05 / '04_월별_상세연결표.csv')
TH = 1.0
# 키
kk = collections.Counter((r['기준월'], r['행정동코드_SGIS']) for r in model)
t('모델용: 키(기준월, 행정동코드_SGIS) 중복 없음', all(n == 1 for n in kk.values()), f'{len(model)}행, 중복 {sum(n - 1 for n in kk.values() if n > 1)}')
t('모델용·상세관리 두 파일의 행_키가 1:1로 일치', [r['행_키'] for r in model] == [r['행_키'] for r in detail] and all(r['행_키'] == f"{r['기준월']}|{r['행정동코드_SGIS']}" for r in model))
t('행 수 = 기준월 46 × 행정동 206', len(model) == 46 * 206 and len({r['기준월'] for r in model}) == 46 and len({r['행정동코드_SGIS'] for r in model}) == 206)
blank10 = {r['행정동명'] for r in model if r['행정동코드_카드10자리'] == ''}
t('행정동코드 문자열 보존(SGIS 8자리, 카드 10자리 — 대응 없는 신호동만 빈값)', all(re.fullmatch(r'21\d{6}', r['행정동코드_SGIS']) and (re.fullmatch(r'26\d{8}', r['행정동코드_카드10자리']) or r['행정동명'] == '신호동') for r in model) and blank10 == {'신호동'}, f'10자리 빈값: {sorted(blank10)}')
raw = (D / '모델용_행정동x기준월_권장초안.csv').read_text(encoding='utf-8-sig')
t('코드가 과학적 표기·소수점으로 저장되지 않음', not re.search(r'\d\.\d+E\+\d+|\b2\d{7}\.0\b', raw))
# 제외 판단 재계산
dropped = {(r['조사지역(SHP 상권명)'], r['행정동코드_SGIS']) for r in ov if float(r['상권면적_대비_%']) < TH}
kept = [r for r in ov if (r['조사지역(SHP 상권명)'], r['행정동코드_SGIS']) not in dropped]
dl = rd(D / '제외된_연결목록.csv')
t('제외 연결 = 상권면적 대비 1% 미만 24개(예외 적용 없음), 목록과 일치', len(dropped) == 24 == len(dl) and {(r['조사상권'], r['행정동코드_SGIS']) for r in dl} == dropped)
t('유지 연결 76개', len(kept) == 76)
t('원본 중첩표(v04 05)는 100행 그대로(삭제 안 함)', len(ov) == 100)
area = {r['행정동코드_SGIS']: float(r['행정동면적_m2']) for r in ov}
by = collections.defaultdict(list)
for r in det:
    if (r['조사상권'], r['행정동코드_SGIS']) not in dropped: by[(r['기준월'], r['상가유형'], r['지표'], r['행정동코드_SGIS'])].append(r)
mi = {r['행_키']: r for r in model}; di = {r['행_키']: r for r in detail}
bad_val = bad_cov = bad_meth = bad_n = fut = 0; nvals = 0; single = multi = 0
for key, m in mi.items():
    for kind, metric, var in SERIES:
        rows = [x for x in by.get((m['기준월'], kind, metric, m['행정동코드_SGIS']), []) if x['값'] != '']
        if not rows:
            if m[var] != '': bad_val += 1
            continue
        nvals += 1
        w = [float(x['겹침면적_m2']) for x in rows]
        exp = sum(wi / sum(w) * float(x['값']) for wi, x in zip(w, rows))
        if m[var] == '' or abs(float(m[var]) - exp) > 1e-5: bad_val += 1
        if abs(sum(w) / area[m['행정동코드_SGIS']] - float(m[f'{var}__유효값커버율(0~1)'])) > 1e-3: bad_cov += 1
        if int(m[f'{var}__유효상권수']) != len(rows): bad_n += 1
        meth = di[key][f'{var}|요약방식']
        if (len(rows) == 1) != (meth == '단일 상권 값'): bad_meth += 1
        if len(rows) == 1: single += 1
        else: multi += 1
        cut = date.fromisoformat(m['기준월'] + '-01'); cut = date(cut.year + (cut.month == 12), cut.month % 12 + 1, 1)
        if not date.fromisoformat(di[key][f'{var}|분기_공표일']) < cut: fut += 1
t('모든 값이 [제외 → 남은 유효 상권 겹침면적 가중평균] 독립 재계산과 일치, 값이 없어야 할 셀은 빈값', bad_val == 0, f'{nvals}개 값, 불일치 {bad_val}')
t('유효값 커버율 = 유효 상권 겹침면적 합 ÷ 행정동 면적(상권 겹침 중복 없음)', bad_cov == 0, f'불일치 {bad_cov}')
t('유효상권수 일치', bad_n == 0)
t('요약방식: 상권 1개면 ‘단일 상권 값’, 2개 이상이면 가중평균', bad_meth == 0, f'단일 {single}개 값, 가중평균 {multi}개 값')
t('미래 공표 정보 사용 없음(사용 분기 공표일 < 컷오프)', fut == 0, f'위반 {fut}')
t('일반 상가·1층: 2026-05 이전 기준월 값 없음', all(r[SERIES[2][2]] == '' and r[SERIES[3][2]] == '' for r in model if r['기준월'] < '2026-05'))
t('2024-11 이전(경계 보류 구간) 모든 값 없음', all(r[v] == '' for r in model if r['기준월'] < '2024-11' for _, _, v in SERIES))
t('‘2626년 2분기’ 값 미사용(관측분기가 정상 분기 형식인 값만 존재)', all(re.fullmatch(r'\d{4}Q[1-4]', di[k][f'{v}|관측분기']) for k, r in mi.items() for _, _, v in SERIES if r[v] != ''))
t('값이 빈 셀은 모두 연결·결측 사유가 있음', all(di[k][f'{v}|연결·결측 사유'] for k, r in mi.items() for _, _, v in SERIES if r[v] == ''))
t('증감·변화율 열 없음', not any(('증감' in c or '변화율' in c) for c in list(model[0]) + list(detail[0])))
mincov = min(float(r[f'{v}__유효값커버율(0~1)']) for r in model for _, _, v in SERIES if r[v] != '')
t('최소 커버율 기준을 적용하지 않음(낮은 커버율 값이 남아 있음)', mincov < 0.01, f'최소 유효값 커버율 {mincov:.6f}')
# 제외 면적 이동 없음: 제외 대상이 아닌 동의 연결 상권 구성은 A와 동일, 제외 대상 동은 해당 상권만 빠짐
A = {(r['기준월'], r['행정동코드_SGIS']): r for r in rd(v06 / '01_모델입력후보_A_미세겹침포함.csv')}
dong_drop = collections.defaultdict(set)
for sk, c in dropped: dong_drop[c].add(sk)
ok_move = True
for k, r in di.items():
    if not r['연결상권목록(제외 후)']:
        continue
    mm, c = k.split('|')
    a_list = set(filter(None, A[(mm, c)]['연결상권_목록'].split(' | ')))
    if set(filter(None, r['연결상권목록(제외 후)'].split(' | '))) != a_list - dong_drop.get(c, set()): ok_move = False
t('제외한 연결은 해당 동에서만 빠지고 다른 동의 연결·가중치로 옮겨지지 않음', ok_move)
# v06 B와 값 동일(예외 없는 1% 기준 = v06 B)
B = {(r['기준월'], r['행정동코드_SGIS']): r for r in rd(v06 / '01_모델입력후보_B_미세겹침제외.csv')}
neq = sum(1 for k, r in mi.items() for _, _, v in SERIES if (r[v] == '') != (B[tuple(k.split('|'))][v] == '') or (r[v] != '' and abs(float(r[v]) - float(B[tuple(k.split('|'))][v])) > 1e-6))
t('권장 초안(1% 기준, 예외 없음)의 값이 v06 B 비교본과 동일', neq == 0, f'불일치 셀 {neq}')
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
t('비교본 A·B가 v06 원본 파일과 바이트 동일', sha(D / '비교본_A_미세겹침포함.csv') == sha(v06 / '01_모델입력후보_A_미세겹침포함.csv') and sha(D / '비교본_B_미세겹침제외.csv') == sha(v06 / '01_모델입력후보_B_미세겹침제외.csv'))
# 시간 연결 불변: v05 선택 결과와 관측분기
sel = {(r['기준월'], r['상가유형'], r['지표']): r for r in rd(v05 / '04b_월별_사용분기_선택결과.csv')}
t('관측분기·공표일이 v05(v03 코드) 선택 결과와 동일(시간 연결 기준 변경 없음)', all(di[k][f'{v}|관측분기'] == sel[(r['기준월'], kd, mt)]['사용분기(관측분기)'] and di[k][f'{v}|분기_공표일'] == sel[(r['기준월'], kd, mt)]['사용분기_공표일'] for k, r in mi.items() for kd, mt, v in SERIES))
with open(out, 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.DictWriter(f, fieldnames=['검수 항목', '결과', '비고']); w.writeheader(); w.writerows(res)
print(collections.Counter(r['결과'] for r in res))
for r in res:
    if r['결과'] == '실패': print(r)
