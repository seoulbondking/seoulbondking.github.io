"""미국 PPI 품목 트리 — indicators.yaml 의 us_ppi / us_ppi_nsa 시리즈 목록과
docs/index.html 의 US_PPI_ROWS 를 이 한 곳에서 만든다.

    python tools/ppi_tree.py          # 두 파일을 갱신
    python tools/bls_probe.py CODE..  # 코드가 살아 있는지 먼저 확인

(SA 코드, NSA 코드, 표시명, 들여쓰기, 주요항목)
SA 코드가 None 이면 계절조정본이 없는 품목 — SA 지표에도 원계열 코드를 넣고 이름에
'(계절조정본 없음 · 원계열)' 을 붙인다. 화면은 표시명의 ' (' 앞부분으로 맞춘다.
그래서 **원계열만 있는 품목 이름에는 ' (' 를 쓰지 말 것.**
"""
import re, sys, os
sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.join(os.path.dirname(__file__), '..')

TREE = [
    ('WPSFD4', 'WPUFD4', 'PPI 최종수요', 0, True),
    ('WPSFD41', 'WPUFD41', '재화', 1, True),
    ('WPSFD411', 'WPUFD411', '식료품', 2, True),
    ('WPSFD4111', 'WPUFD4111', '소비자 식료품', 3, False),
    ('WPS0221', 'WPU0221', '육류', 3, False),
    ('WPS0222', 'WPU0222', '가금류 가공', 3, False),
    ('WPS0223', 'WPU0223', '수산물', 3, False),
    (None, 'WPU023', '유제품', 3, False),
    (None, 'WPU017107', '계란', 3, False),
    ('WPS0113', 'WPU0113', '신선·건조 채소', 3, False),
    ('WPS0111', 'WPU0111', '신선 과일', 3, False),
    ('WPS012', 'WPU012', '곡물', 3, False),
    ('WPS026', 'WPU026', '음료·음료원료', 3, False),
    ('WPSFD412', 'WPUFD412', '에너지', 2, True),
    ('WPSFD4121', 'WPUFD4121', '소비자 에너지재', 3, False),
    ('WPS057', 'WPU057', '석유제품', 3, False),
    ('WPS0571', 'WPU0571', '휘발유', 4, False),
    ('WPS057303', 'WPU057303', '디젤', 4, False),
    ('WPS057302', 'WPU057302', '난방유', 4, False),
    (None, 'WPU0572', '항공유·등유', 4, False),
    ('WPS054', 'WPU054', '전력', 3, False),
    ('WPS0541', 'WPU0541', '가정용 전력', 4, False),
    ('WPS0543', 'WPU0543', '산업용 전력', 4, False),
    ('WPS055', 'WPU055', '도시가스', 3, False),
    ('WPS0551', 'WPU0551', '가정용 도시가스', 4, False),
    ('WPSFD413', 'WPUFD413', '근원재화', 2, True),
    ('WPSFD4131', 'WPUFD4131', '소비재', 3, False),
    ('WPSFD41312', 'WPUFD41312', '자본재', 3, False),
    ('WPSFD4132', 'WPUFD4132', '정부구매 재화', 3, False),
    ('WPSFD4133', 'WPUFD4133', '수출 재화', 3, False),
    ('WPS1411', 'WPU1411', '자동차', 3, False),
    ('WPS141101', 'WPU141101', '승용차', 4, False),
    ('WPS141105', 'WPU141105', '경트럭·SUV', 4, False),
    ('WPS063', 'WPU063', '의약품', 3, False),
    ('WPSFD42', 'WPUFD42', '서비스', 1, True),
    ('WPSFD423', 'WPUFD423', '유통 마진', 2, True),
    ('WPSFD4231', 'WPUFD4231', '완제품 유통', 3, False),
    (None, 'WPU57', '도매 마진', 3, False),
    (None, 'WPU58', '소매 마진', 3, False),
    (None, 'WPU581', '식품·주류 소매', 4, False),
    ('WPSFD422', 'WPUFD422', '운송·창고', 2, True),
    ('WPSFD4221', 'WPUFD4221', '여객 운송', 3, False),
    ('WPS3022', 'WPU3022', '항공요금', 4, False),
    ('WPSFD4222', 'WPUFD4222', '화물 운송·창고', 3, False),
    ('WPS301', 'WPU301', '화물 운송', 4, False),
    (None, 'WPU3012', '트럭 화물', 5, False),
    (None, 'PCU484121484121', '트럭 장거리 FTL', 6, False),
    (None, 'PCU4841224841221', '트럭 장거리 LTL', 6, False),
    (None, 'WPU3011', '철도 화물', 5, False),
    (None, 'WPU3013', '수상 화물', 5, False),
    (None, 'WPU3014', '항공 화물', 5, False),
    (None, 'WPU3016', '택배·우편', 5, False),
    (None, 'WPU321', '창고·보관', 4, False),
    ('WPSFD421', 'WPUFD421', '기타 서비스', 2, True),
    ('WPSFD4211', 'WPUFD4211', '소비자 서비스', 3, False),
    ('WPSFD4212', 'WPUFD4212', '정부구매 서비스', 3, False),
    ('WPSFD4213', 'WPUFD4213', '수출 서비스', 3, False),
    (None, 'WPU4011', '증권중개·투자자문', 3, False),
    (None, 'WPU402', '자산관리 수수료', 3, False),
    (None, 'WPU4511', '법률 서비스', 3, False),
    ('WPS512101', 'WPU512101', '병원 입원', 3, False),
    ('WPS511104', 'WPU511104', '병원 외래', 3, False),
    ('WPS511101', 'WPU511101', '의사 진료', 3, False),
    ('WPS512102', 'WPU512102', '요양시설', 3, False),
    ('WPS511103', 'WPU511103', '재택·호스피스 간호', 3, False),
    ('WPSFD43', 'WPUFD43', '건설', 1, False),
    ('WPSFD49104', 'WPUFD49104', '근원 PPI (식료품·에너지 제외)', 0, True),
    ('WPSFD49116', 'WPUFD49116', '근원 PPI (식료품·에너지·유통 제외)', 1, True),
]
NOSA = '(계절조정본 없음 · 원계열)'


def yaml_block(sa):
    out = []
    for s, n, nm, lv, _ in TREE:
        if sa and s is None:
            out.append(f'        {n}: {nm} {NOSA}')
        else:
            out.append(f'        {s if sa else n}: {nm}')
    return '\n'.join(out) + '\n'


def main():
    p = os.path.join(ROOT, 'indicators.yaml')
    y = open(p, encoding='utf-8').read()
    for ind, sa in (('us_ppi', True), ('us_ppi_nsa', False)):
        # '- id: <ind>' 블록의 'series:' 아래 들여쓰기 8칸 줄들을 통째로 갈아 끼운다
        pat = re.compile(r'(  - id: ' + ind + r'\n(?:(?!  - id: ).*\n)*?      series:\n)((?:        .*\n)+)')
        m = pat.search(y)
        assert m, ind
        y = y[:m.start(2)] + yaml_block(sa) + y[m.end(2):]
    open(p, 'w', encoding='utf-8', newline='\n').write(y)

    h = os.path.join(ROOT, 'docs', 'index.html')
    s = open(h, encoding='utf-8').read()
    rows = 'const US_PPI_ROWS = [\n' + ''.join(
        f"  ['{nm}', {lv}, {'true' if main_ else 'false'}],\n" for _, _, nm, lv, main_ in TREE) + '];'
    s2, k = re.subn(r'const US_PPI_ROWS = \[\n(?:.*\n)*?\];', lambda _: rows, s, count=1)
    assert k == 1
    nosa = ', '.join(f"'{nm}'" for sa_, _, nm, _, _ in TREE if sa_ is None)
    s2, k = re.subn(r'const US_PPI_NOSA = new Set\(\[[^\]]*\]\);', lambda _: f'const US_PPI_NOSA = new Set([{nosa}]);', s2, count=1)
    assert k == 1
    open(h, 'w', encoding='utf-8', newline='\n').write(s2)
    print(f'품목 {len(TREE)}개 · 원계열만 {nosa.count(",") + 1}개')


if __name__ == '__main__':
    main()
