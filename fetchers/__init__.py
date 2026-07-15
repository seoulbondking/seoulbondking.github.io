"""데이터 소스별 수집 모듈.

새 소스를 추가하려면 이 패키지에 모듈을 만들고
fetch(indicator: dict) -> list[dict] 형태의 함수를 구현한 뒤
fetch.py 의 SOURCES 에 등록하면 됩니다.
(예: ecos.py, fred.py, bls.py ...)
"""
