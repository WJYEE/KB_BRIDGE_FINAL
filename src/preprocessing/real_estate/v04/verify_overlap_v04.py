"""build_overlap_v04.py 결과의 내부 일관성 점검(읽기 전용). 사용: python -I verify_overlap_v04.py <결과 폴더> <출력 csv>"""
import csv, sys, collections, json
from pathlib import Path
D, out = Path(sys.argv[1]), Path(sys.argv[2])
rd = lambda n: list(csv.DictReader(open(D / n, encoding='utf-8-sig')))
sk, bus, ov, cw, per, ds = (rd('02_상권경계_속성_검수_전국.csv'), rd('03_부산_상권_공간식별.csv'), rd('05_상권_행정동_중첩표.csv'),
                            rd('04_조사상권명_SHP_대응표.csv'), rd('06_경계_적용기간_개편이전_연결상태.csv'), rd('07_행정동별_겹치는상권_요약.csv'))
res = []
def t(name, ok, note=''): res.append({'시험': name, '결과': '통과' if ok else '실패', '비고': note})
area = {r['sec_seq']: float(r['면적_m2(EPSG5179)']) for r in bus}
by = collections.defaultdict(float)
for r in ov: by[r['sec_seq']] += float(r['겹침면적_m2'])
t('상권별 겹침 합계가 상권 면적을 넘지 않음(0.1% 허용)', all(by[k] <= area[k] * 1.001 for k in area), f'최대 {max(by[k] / area[k] for k in area):.4f}')
t('모든 부산 상권이 중첩표에 1행 이상', set(area) <= set(by))
t('중첩표 키(상권, 행정동) 중복 없음', len({(r['sec_seq'], r['행정동코드_SGIS']) for r in ov}) == len(ov))
t('상권면적_대비_% 재계산 일치', all(abs(float(r['겹침면적_m2']) / float(r['상권면적_m2']) * 100 - float(r['상권면적_대비_%'])) < 0.01 for r in ov))
t('행정동 요약의 상권 수 = 중첩표(미세 제외) 집계', all(int(d['겹치는 상권 수(미세 제외)']) == sum(1 for r in ov if r['행정동코드_SGIS'] == d['행정동코드_SGIS'] and r['미세겹침(상권의 1% 미만)'] == 'N') for d in ds))
t('행정동 206개 전부 요약에 있음', len(ds) == 206)
t('부산 상권 27개, 전국 368개', len(bus) == 27 and len(sk) == 368)
t('이름만으로 식별한 상권 없음(이름 ‘부산’ 포함 상권도 공간 기준으로 판정)', all(r['부산_공간식별'].startswith('부산') for r in bus))
t('조사 표 대응: 일치 27개 상권, 미일치 3개(서면, 서면전포, 중구시장)', {r['조사지역'] for r in cw if r['대응 상태'].startswith('이름 정확 일치 + 공간상 부산')} .__len__() == 27 and
  {r['조사지역'] for r in cw if '정확 일치 없음' in r['대응 상태']} == {'서면', '서면전포', '중구시장'})
t('정규화 일치 후보(서면전포→서면/전포)는 확정으로 표시되지 않음', all('확정 아님' in r['대응 상태'] for r in cw if r['조사지역'] == '서면전포'))
t('조사 상권명 30개가 개편 이전 연결 표에 모두 있음', len(per) == 30)
t('값 컬럼 없음(임대료·공실률 미연결)', all('공실률_pct' not in r and '임대료_천원per㎡' not in r for r in ov) and all(r['임대료·공실률 값'].startswith('미연결') for r in ov))
t('모든 중첩 행에 경계 적용기간·개편 이전 상태·해석 고지 존재', all(r['경계_적용기간'] and r['개편이전(2024Q2 이하) 자료 연결'] and r['해석 고지'] for r in ov))
with open(out, 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.DictWriter(f, fieldnames=['시험', '결과', '비고']); w.writeheader(); w.writerows(res)
print(collections.Counter(r['결과'] for r in res))
