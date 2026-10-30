"""v07-1: 작은 겹침 검토(상권면적 대비 2% 미만 연결) + 제외 기준 0/1/2% 비교 + 지도.
1%·2%는 공식 기준이 아닌 실험 기준이다. 값은 월 1개(대표월)로 비교하고, 연결 구성이 월마다 같은지도 확인한다.
사용: python -B build_review_v07.py --v04 <v04 결과> --v05 <v05 결과> --v06 <v06 결과> --sgis-zip <zip> --out <새 폴더> [--rep-month 2026-06]
필요: pyshp, shapely, matplotlib
"""
import argparse, collections, csv, io, json, statistics, sys, zipfile
from pathlib import Path
import shapefile
from shapely.geometry import shape
from shapely.ops import unary_union

ap = argparse.ArgumentParser()
ap.add_argument('--v04', required=True, type=Path); ap.add_argument('--v05', required=True, type=Path)
ap.add_argument('--v06', required=True, type=Path); ap.add_argument('--sgis-zip', required=True, type=Path)
ap.add_argument('--out', required=True, type=Path); ap.add_argument('--rep-month', default='2026-06')
ap.add_argument('--no-maps', action='store_true')
a = ap.parse_args()
if a.out.exists() and any(a.out.glob('0*.csv')): sys.exit('출력 폴더에 결과가 이미 있다(덮어쓰지 않음)')
a.out.mkdir(parents=True, exist_ok=True)
rd = lambda p: list(csv.DictReader(open(p, encoding='utf-8-sig', newline='')))
def wr(name, rows, cols=None):
    with (a.out / name).open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols or list(rows[0])); w.writeheader(); w.writerows(rows)

SERIES = [('소규모 상가', '공실률', '연결상권_공실률_면적가중_소규모상가'), ('집합 상가', '공실률', '연결상권_공실률_면적가중_집합상가'),
          ('일반 상가', '공실률', '연결상권_공실률_면적가중_일반상가'), ('일반 상가(1층)', '공실률(1층)', '연결상권_1층공실률_면적가중_일반상가1층'),
          ('소규모 상가', '임대료', '연결상권_임대료_면적가중_소규모상가'), ('집합 상가', '임대료', '연결상권_임대료_면적가중_집합상가')]
THRESH = [0.0, 1.0, 2.0]
ov = rd(a.v04 / '05_상권_행정동_중첩표.csv')
mapping = {r['행정동코드_SGIS(8자리)']: r for r in rd(a.v05 / '02_행정동코드_대응표.csv')}
det = rd(a.v05 / '04_월별_상세연결표.csv')

# ------------------------------------------------------------------ 도형
with zipfile.ZipFile(a.sgis_zip) as z:
    part = {e: io.BytesIO(z.read(n)) for n in z.namelist() for e in ('shp', 'shx', 'dbf') if n.lower().endswith('.' + e)}
rdr = shapefile.Reader(shp=part['shp'], shx=part['shx'], dbf=part['dbf'], encoding='utf-8')
dgeom, dname = {}, {}
for s, rec in zip(rdr.shapes(), rdr.records()):
    g = shape(s.__geo_interface__); dgeom[rec[1]] = g if g.is_valid else g.buffer(0); dname[rec[1]] = rec[2]
gj = json.loads((a.v04 / '부산_상권경계_2024_EPSG5179.geojson').read_text(encoding='utf-8'))
sgeom = {f['properties']['sec_nm']: shape(f['geometry']) for f in gj['features']}
inter = {(r['행정동코드_SGIS'], r['조사지역(SHP 상권명)']): sgeom[r['조사지역(SHP 상권명)']].intersection(dgeom[r['행정동코드_SGIS']]) for r in ov}
for r in ov:
    r['_pk'] = float(r['상권면적_대비_%']); r['_m2'] = float(r['겹침면적_m2']); r['_code'] = r['행정동코드_SGIS']; r['_sk'] = r['조사지역(SHP 상권명)']
by_sk = collections.defaultdict(list)
for r in ov: by_sk[r['_sk']].append(r)

# 대표월 값(상권별·시리즈별)
val = {}
for r in det:
    if r['기준월'] == a.rep_month and r['값'] != '':
        val[(r['조사상권'], r['상가유형'], r['지표'])] = float(r['값'])
series_of = collections.defaultdict(set)       # 상권 -> 값이 있는 변수(대표월)
for (sk, kind, metric), v in val.items(): series_of[sk].add((kind, metric))
VAR = {(k, m): v for k, m, v in SERIES}

# ------------------------------------------------------------------ 1. 작은 겹침 검토표
small = sorted([r for r in ov if r['_pk'] < 2.0], key=lambda r: (r['_pk'], r['_m2']))
rev, cases = [], []
for i, r in enumerate(small, 1):
    code, sk = r['_code'], r['_sk']
    g = inter[(code, sk)]
    others = [o for o in ov if o['_code'] == code and o is not r]
    lost = []
    for (kind, metric) in sorted(series_of[sk]):
        if not any((o['_sk'], kind, metric) in val for o in others):
            lost.append(VAR[(kind, metric)])
    dist = sorted(by_sk[sk], key=lambda o: -o['_pk'])
    width = 2 * g.area / g.length if g.length else 0
    rev.append({'번호': i, '조사상권': sk, '구군': mapping[code]['시군구명'], '행정동명': dname[code], '행정동코드_SGIS': code, '행정동코드_카드10자리': mapping[code]['행정동코드_카드(10자리)'],
                '겹침면적_m2': r['겹침면적_m2'], '상권면적_m2': r['상권면적_m2'], '상권면적_대비_%': r['상권면적_대비_%'], '행정동면적_m2': r['행정동면적_m2'], '행정동면적_대비_%': r['행정동면적_대비_%'],
                '구간': '1% 미만' if r['_pk'] < 1 else '1~2%', '겹침 도형 평균 폭_m(2×면적÷둘레, 얇은 띠일수록 작음)': round(width, 1), '겹침 도형 둘레_m': round(g.length, 1),
                '같은 상권이 걸친 행정동 수': len(dist), '같은 상권의 행정동별 점유(상권면적 대비 %)': ' | '.join(f"{dname[o['_code']]} {o['_pk']:.1f}%" for o in dist),
                '이 연결의 상권이 최대로 걸친 행정동': dname[dist[0]['_code']], '이 동의 다른 연결 상권 수': len(others), '이 동의 다른 연결 상권': ' | '.join(o['_sk'] for o in others),
                f'제외하면 값이 없어지는 변수({a.rep_month} 기준)': ' ; '.join(lost) if lost else '없음(다른 상권 값이 남음)' if others else '없음(해당 상권 값 변수 없음)',
                '확인된 사실': f"겹침 {r['겹침면적_m2']}㎡, 상권의 {r['상권면적_대비_%']}%, 행정동의 {r['행정동면적_대비_%']}%. 상권의 {dist[0]['_pk']:.1f}%는 {dname[dist[0]['_code']]}에 있음",
                '판단 필요': '경계 일치 오차(디지타이징·투영)인지 실제로 걸친 것인지는 면적 비율만으로 단정할 수 없음. 지도·원자료(공식 경계) 확인 필요'})
    cases.append((i, r, g))
wr('01_작은겹침_검토표.csv', rev)

# ------------------------------------------------------------------ 2. 기준별 비교(대표월)
def build(th):
    """th 미만(상권면적 대비 %) 연결 제외 → 남은 연결에서 값 있는 상권만 면적가중평균."""
    res = {}
    for kind, metric, var in SERIES:
        per = collections.defaultdict(list)
        for r in ov:
            if r['_pk'] < th: continue
            v = val.get((r['_sk'], kind, metric))
            if v is not None: per[r['_code']].append((r, v))
        out = {}
        for code, items in per.items():
            w = sum(r['_m2'] for r, _ in items)
            cov = unary_union([inter[(code, r['_sk'])] for r, _ in items]).area / dgeom[code].area
            out[code] = {'v': sum(r['_m2'] * v for r, v in items) / w, 'cov': cov, 'n': len(items), 'sks': [r['_sk'] for r, _ in items], 'm2': sum(r['_m2'] for r, _ in items)}
        res[var] = out
    return res
R = {th: build(th) for th in THRESH}
summ, lost_rows, chg_rows, low_rows = [], [], [], []
for th in THRESH:
    kept = sum(1 for r in ov if r['_pk'] >= th)
    for kind, metric, var in SERIES:
        cur, base = R[th][var], R[0.0][var]
        lost_ = sorted(set(base) - set(cur))
        diffs = [(c, abs(cur[c]['v'] - base[c]['v'])) for c in cur if abs(cur[c]['v'] - base[c]['v']) > 1e-9]
        covs = [x['cov'] for x in cur.values()]
        summ.append({'제외 기준(상권면적 대비 겹침 %)': f'{th:g}% 미만 제외' if th else '0%(현재 연결 전부 유지)', '변수': var, '유지 연결 수': kept, '제외 연결 수': len(ov) - kept,
                     '값이 연결되는 행정동': len(cur), '기준 0% 대비 새로 값이 없어지는 행정동': len(lost_), '가중평균 값이 달라지는 행정동': len(diffs),
                     '값 차이 평균(절대)': round(statistics.mean([d for _, d in diffs]), 6) if diffs else 0, '값 차이 최대(절대)': round(max([d for _, d in diffs]), 6) if diffs else 0,
                     '유효값 커버율 1% 미만인 동': sum(c < 0.01 for c in covs), '유효값 커버율 5% 미만인 동': sum(c < 0.05 for c in covs), '유효값 커버율 중앙값': round(statistics.median(covs), 4),
                     '유효값 커버율 최소': round(min(covs), 8), '단위': '%p(공실률)' if metric != '임대료' else '천원/㎡'})
        for c in lost_:
            lost_rows.append({'제외 기준': f'{th:g}% 미만', '변수': var, '행정동': dname[c], '행정동코드_SGIS': c, '구군': mapping[c]['시군구명'], '없어지는 값(0% 기준)': round(base[c]['v'], 6),
                              '연결 상권': ' | '.join(base[c]['sks']), '겹침면적_m2': round(base[c]['m2'], 1), '0% 기준 유효값 커버율': round(base[c]['cov'], 8)})
        for c, d in diffs:
            chg_rows.append({'제외 기준': f'{th:g}% 미만', '변수': var, '행정동': dname[c], '행정동코드_SGIS': c, '0% 기준 값': round(base[c]['v'], 6), '기준 적용 값': round(cur[c]['v'], 6), '차이(절대)': round(d, 6),
                             '0% 기준 연결 상권': ' | '.join(base[c]['sks']), '기준 적용 연결 상권': ' | '.join(cur[c]['sks'])})
        for c, x in cur.items():
            if x['cov'] < 0.05:
                low_rows.append({'제외 기준': f'{th:g}% 미만' if th else '0%', '변수': var, '행정동': dname[c], '행정동코드_SGIS': c, '유효값 커버율': round(x['cov'], 6), '연결 상권': ' | '.join(x['sks']),
                                 '겹침면적_m2': round(x['m2'], 1), '행정동면적_m2': round(dgeom[c].area, 1)})
wr('02_제외기준_비교_요약.csv', summ)
wr('02b_기준별_새로_값없어지는_행정동.csv', lost_rows or [{'비고': '없음'}])
wr('02c_기준별_값_달라지는_행정동.csv', chg_rows or [{'비고': '없음'}])
wr('02d_값이_있으나_커버율_낮은_사례(5%미만).csv', low_rows or [{'비고': '없음'}])

# 연결 구성이 월마다 같은지(2024-11 이후, 일반은 2026-05 이후)
cand = rd(a.v06 / '01_모델입력후보_A_미세겹침포함.csv')
pres = collections.defaultdict(set)
for r in cand:
    for _, _, var in SERIES:
        if r[var] != '': pres[(r['기준월'], var)].add(r['행정동코드_SGIS'])
inv = True
for _, _, var in SERIES:
    sets = {frozenset(v) for (m, vv), v in pres.items() if vv == var}
    inv &= len(sets) == 1
wr('02e_월별_연결구성_불변_확인.csv', [{'확인': '2024-11 이후 값이 있는 월들에서 변수별 값 연결 행정동 집합이 모두 같음', '결과': 'Y' if inv else 'N', '비고': '같으면 대표월 비교가 다른 월에도 적용됨(값 크기는 분기마다 다름)'}])

# ------------------------------------------------------------------ 지도
if not a.no_maps:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font_manager.fontManager.addfont(r'C:\Windows\Fonts\malgun.ttf'); plt.rcParams['font.family'] = 'Malgun Gothic'; plt.rcParams['axes.unicode_minus'] = False
    mdir = a.out / '지도'; mdir.mkdir(exist_ok=True)
    def draw(ax, g_dong, g_sk, g_ov, bbox, code, ctx_dongs):
        for c in ctx_dongs:
            gg = dgeom[c]
            for poly in (gg.geoms if gg.geom_type == 'MultiPolygon' else [gg]):
                x, y = poly.exterior.xy; ax.plot(x, y, color='#9aa0a6', lw=0.8)
        for poly in (g_dong.geoms if g_dong.geom_type == 'MultiPolygon' else [g_dong]):
            x, y = poly.exterior.xy; ax.plot(x, y, color='#1a56db', lw=2)
        for poly in (g_sk.geoms if g_sk.geom_type == 'MultiPolygon' else [g_sk]):
            x, y = poly.exterior.xy; ax.fill(x, y, color='#f59e0b', alpha=0.35); ax.plot(x, y, color='#b45309', lw=1.5)
        for poly in (g_ov.geoms if g_ov.geom_type in ('MultiPolygon', 'GeometryCollection') else [g_ov]):
            if poly.geom_type != 'Polygon': continue
            x, y = poly.exterior.xy; ax.fill(x, y, color='#dc2626', alpha=0.8)
        ax.set_xlim(bbox[0], bbox[2]); ax.set_ylim(bbox[1], bbox[3]); ax.set_aspect('equal'); ax.set_xticks([]); ax.set_yticks([])
    for i, r, g in cases:
        code, sk = r['_code'], r['_sk']
        gs, gd = sgeom[sk], dgeom[code]
        b1 = gs.union(gd).bounds if gd.area < 5 * gs.area else gs.buffer(300).bounds
        m1 = max(b1[2] - b1[0], b1[3] - b1[1]) * 0.08
        b2 = g.bounds; m2 = max(40, max(b2[2] - b2[0], b2[3] - b2[1]) * 0.6)
        ctx = [c for c, gg in dgeom.items() if gg.intersects(gs.buffer(500))]
        fig, axs = plt.subplots(1, 2, figsize=(11, 5.2))
        draw(axs[0], gd, gs, g, (b1[0] - m1, b1[1] - m1, b1[2] + m1, b1[3] + m1), code, ctx)
        draw(axs[1], gd, gs, g, (b2[0] - m2, b2[1] - m2, b2[2] + m2, b2[3] + m2), code, ctx)
        axs[0].set_title(f"전체 보기: {sk} (주황) / {dname[code]} (파랑 윤곽)", fontsize=10); axs[1].set_title('겹침 부분 확대 (빨강). 격자 없음, 단위 m', fontsize=10)
        fig.suptitle(f"#{i} {sk} × {mapping[code]['시군구명']} {dname[code]} — 겹침 {r['겹침면적_m2']}㎡ (상권의 {r['상권면적_대비_%']}%, 행정동의 {r['행정동면적_대비_%']}%)", fontsize=11)
        fig.tight_layout(); fig.savefig(mdir / f'{i:02d}_{sk.replace("/", "-")}_{dname[code]}.png', dpi=80); plt.close(fig)
print(len(ov), len(small), len(summ))
