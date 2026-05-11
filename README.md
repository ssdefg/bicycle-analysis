# bicycle-analysis
-------------------------------------------------------------------------------------------------------
ai link
https://gemini.google.com/share/cbefbeaef392
https://aistudio.google.com/app/prompts?state=%7B%22ids%22:%5B%221fmudQd1ecyMKp4H7Fu0LGMHHqpJORQgk%22%5D,%22action%22:%22open%22,%22userId%22:%22117175326847036375301%22,%22resourceKeys%22:%7B%7D%7D&usp=sharing

데이터
원본데이터: 행정구, 도서관명, 도서관구분, 장서수, 사서수, 대출권수, 자료구입비 등이 한 테이블에 포함
행정구역, 시군구 중복데이터 처리
1) table_region: 중복되는 행정구역, 시군구 분리
2) table_library: 도서관코드 기본키, region_id 외래키
3) table_stats: 수치데이터 / stats_id 기본키, 도서관코드 외래키
-------------------------------------------------------------------------------------------------------
1. 어느 행정구역에 공공도서관이 가장 집중되어 있는가
SELECT 
    R.행정구역, 
    COUNT(L.도서관코드) AS 도서관수
FROM table_region R
JOIN table_library L ON R.region_id = L.region_id
GROUP BY R.행정구역
ORDER BY 도서관수 DESC;
시각화 방법: 막대 차트

2. 지역별로 사서 한 명 당 담당 책 수
SELECT 
    R.행정구역, 
    SUM(S.`장서수(인쇄)`) AS 총장서수,
    SUM(S.사서수) AS 총사서수,
    CAST(SUM(S.`장서수(인쇄)`) AS FLOAT) / NULLIF(SUM(S.사서수), 0) AS 사서1인당장서수
FROM table_region R
JOIN table_library L ON R.region_id = L.region_id
JOIN table_stats S ON L.도서관코드 = S.도서관코드
GROUP BY R.행정구역
ORDER BY 사서1인당장서수 DESC;
시각화 방법: 트리맵 (Treemap)
3. 도서관 책 구입 예산 대비 매출 실적
SELECT 
    R.행정구역, 
    AVG(S.`자료구입비(천원)`) AS 평균자료구입비, 
    SUM(S.대출권수) AS 총대출권수
FROM table_region R
JOIN table_library L ON R.region_id = L.region_id
JOIN table_stats S ON L.도서관코드 = S.도서관코드
GROUP BY R.행정구역;
시각화: 버블차트
