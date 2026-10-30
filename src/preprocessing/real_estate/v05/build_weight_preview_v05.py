"""여러 상권이 겹치는 행정동의 겹침 면적·비중만 보여 준다(값 없음, 평균 계산 안 함).
사용: python -B build_weight_preview_v05.py <v04 결과> <출력 csv>"""
import csv, sys, collections
from pathlib import Path
rows = list(csv.DictReader(open(Path(sys.argv[1]) / '05_상권_행정동_중첩표.csv', encoding='utf-8-sig')))
by = collections.defaultdict(list)
for r in rows: by[(r['행정동코드_SGIS'], r['행정동명'])].append(r)
out = []
for (code, nm), rs in sorted(by.items()):
    if len(rs) < 2: continue
    tot = sum(float(r['겹침면적_m2']) for r in rs)
    for r in sorted(rs, key=lambda x: -float(x['겹침면적_m2'])):
        out.append({'행정동코드_SGIS': code, '행정동명': nm, '조사상권': r['조사지역(SHP 상권명)'], '겹침면적_m2': r['겹침면적_m2'],
                    '동 안 상권 면적합 대비 비중_%(미세 포함)': round(100 * float(r['겹침면적_m2']) / tot, 2), '상권면적_대비_%': r['상권면적_대비_%'],
                    '미세겹침(상권의 1% 미만)': r['미세겹침(상권의 1% 미만)'], '비고': '가중치 후보 확인용. 값·평균 없음'})
with open(sys.argv[2], 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
print(len({(o['행정동코드_SGIS']) for o in out}), len(out))
