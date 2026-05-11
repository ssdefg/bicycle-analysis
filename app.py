import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
import os
import numpy as np

# --------------------------------------------------
# 1. 환경 설정 및 상수 정의
# --------------------------------------------------
st.set_page_config(
    page_title="전국 공공도서관 분석 대시보드 (SQL 기반)",
    page_icon="📚",
    layout="wide"
)

DATA_FILE = 'library.csv'

# [개선안 반영] 유연한 컬럼 매핑 정의
# 여러 가지 가능한 컬럼명들을 리스트로 관리하여 파일 호환성 높임
COLUMN_CANDIDATES = {
    'library_code': ['도서관코드', '도서관ID', 'LIBRARY_CD'],
    'library_name': ['도서관명', '도서관이름', 'LIBRARY_NM'],
    'region_main': ['행정구역', '시도명', 'CTPRVN_NM'],
    'region_sub': ['시군구', '시군구명', 'SIGNGU_NM'],
    'library_type': ['도서관구분', '도서관유형', 'LBRRY_SE'],
    'book_count': ['장서수(인쇄)', '인쇄도서수', '장서수', 'BOOK_CO'],
    'librarian_count': ['사서수', '사서인원', 'LIBRARIAN_CO'],
    'loan_count': ['대출권수', '총대출권수', 'LOAN_CO'],
    'budget_buying': ['자료구입비(천원)', '자료구입비', 'BUDGET_ACQS']
}

NUMERIC_COLS = ['book_count', 'librarian_count', 'loan_count', 'budget_buying']

# --------------------------------------------------
# 2. 데이터 로드, 전처리 및 DB 정규화 함수 (캐싱 적용)
# --------------------------------------------------
def find_actual_column(df_cols, candidates):
    """데이터프레임 컬럼시 후보군 중 실제 존재하는 컬럼명을 찾음"""
    for candidate in candidates:
        if candidate in df_cols:
            return candidate
    return None

@st.cache_resource
def load_and_normalize_data(csv_path):
    """CSV 로드 -> 전처리 -> 3NF 정규화 -> SQLite DB 구축"""
    # 1. 파일 존재 확인
    if not os.path.exists(csv_path):
        st.error(f"❌ 데이터 파일('{csv_path}')이 없습니다. 앱과 같은 폴더에 위치시켜주세요.")
        st.stop()

    # 2. 유연한 인코딩으로 파일 읽기
    try:
        df_raw = pd.read_csv(csv_path, encoding='utf-8-sig', thousands=',')
    except UnicodeDecodeError:
        try:
            df_raw = pd.read_csv(csv_path, encoding='cp949', thousands=',')
        except Exception as e:
             st.error(f"인코딩 오류: {e}")
             st.stop()

    # 3. [개선안 반영] 유연한 컬럼 매핑 적용
    final_mapping = {}
    missing_targets = []
    
    for target_col, candidates in COLUMN_CANDIDATES.items():
        actual = find_actual_column(df_raw.columns, candidates)
        if actual:
            final_mapping[actual] = target_col
        else:
            missing_targets.append(target_col)
            
    if missing_targets:
        st.error(f"필수 데이터를 찾을 수 없습니다. 다음 정보가 포함된 파일을 사용해주세요: {missing_targets}")
        st.stop()
        
    df_selected = df_raw[final_mapping.keys()].rename(columns=final_mapping)

    # 4. 숫자형 데이터 안전한 변환 (결측치/오류 -> 0 처리)
    for col in NUMERIC_COLS:
        # 이미 thousands=','로 읽었지만, 혹시 모를 문자열 혼입 대비
        df_selected[col] = pd.to_numeric(df_selected[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)

    # --- 데이터베이스 정규화 (Normalization) ---
    conn = sqlite3.connect(':memory:', check_same_thread=False)

    # Table 1: table_region (지역 마스터)
    # 행정구역과 시군구의 고유 조합에 ID 부여
    df_region = df_selected[['region_main', 'region_sub']].drop_duplicates().sort_values(['region_main', 'region_sub']).reset_index(drop=True)
    df_region['region_id'] = df_region.index + 1
    df_region = df_region[['region_id', 'region_main', 'region_sub']]
    df_region.to_sql('table_region', conn, index=False, if_exists='replace', dtype={'region_id': 'INTEGER PRIMARY KEY'})

    # Table 2: table_library (도서관 정보 - region_id FK 연결)
    df_lib_merged = pd.merge(df_selected, df_region, on=['region_main', 'region_sub'], how='left')
    df_library = df_lib_merged[['library_code', 'region_id', 'library_name', 'library_type']].drop_duplicates(subset='library_code')
    df_library.to_sql('table_library', conn, index=False, if_exists='replace', dtype={'library_code': 'TEXT PRIMARY KEY'})

    # Table 3: table_stats (통계 팩트 - 한글 컬럼명 사용)
    df_stats = df_selected[['library_code', 'book_count', 'librarian_count', 'loan_count', 'budget_buying']].drop_duplicates(subset='library_code')
    df_stats.columns = ['도서관코드', '장서수', '사서수', '대출권수', '자료구입비_천원'] # 컬럼명 직관적으로 변경
    df_stats.to_sql('table_stats', conn, index=False, if_exists='replace', dtype={'도서관코드': 'TEXT PRIMARY KEY'})

    return conn, sorted(df_region['region_main'].unique())

def run_query(query, db_connection):
    return pd.read_sql(query, db_connection)

# --------------------------------------------------
# 3. 메인 애플리케이션 UI
# --------------------------------------------------
try:
    db_conn, all_regions = load_and_normalize_data(DATA_FILE)
except Exception as e:
    st.error(f"DB 초기화 실패: {e}")
    st.stop()

# 사이드바 설정
with st.sidebar:
    st.header("🔎 분석 필터")
    selected_regions = st.multiselect("행정구역(광역) 선택", all_regions, default=all_regions)
    
    st.markdown("---")
    st.header("⚙️ 차트 옵션")
    # [개선안 반영] 로그 스케일 옵션 추가
    use_log_scale = st.checkbox("버블 차트 로그 스케일 적용", value=True, help="데이터 간 격차가 클 때 활성화하세요.")

    if not selected_regions:
        st.warning("최소 하나 이상의 행정구역을 선택해주세요.")
        st.stop()
        
    # SQL WHERE 절 조건 생성용 문자열
    region_filter_str = "'" + "','".join(selected_regions) + "'"


# 메인 컨텐츠
st.title("📚 전국 공공도서관 운영 분석 (SQL 기반)")
st.markdown("""
CSV 데이터를 **SQLite 인메모리 DB (3NF 정규화)**로 구축하여 분석합니다. 
사이드바에서 지역을 선택하면 모든 SQL 쿼리가 동적으로 변경되어 실행됩니다.
""")

with st.expander("참고: DB 스키마 및 관계도 보기"):
    col1, col2, col3 = st.columns(3)
    col1.markdown("#### 1. table_region (지역)\n- `region_id` (PK)\n- `region_main`\n- `region_sub`")
    col2.markdown("#### 2. table_library (도서관)\n- `library_code` (PK)\n- `region_id` (FK)\n- `library_name`...")
    col3.markdown("#### 3. table_stats (통계)\n- `도서관코드` (PK, FK)\n- `장서수`, `사서수`\n- `대출권수`, `자료구입비_천원`")
st.divider()


# ==============================================================================
# [분석 1] 행정구역별 공공도서관 집중도 (인프라 분포)
# ==============================================================================
st.header("1. 행정구역별 공공도서관 집중도")

sql_q1 = f"""
SELECT 
    T1.region_main as 행정구역,
    COUNT(T2.library_code) as 도서관수
FROM table_region AS T1
JOIN table_library AS T2 ON T1.region_id = T2.region_id
WHERE T1.region_main IN ({region_filter_str}) -- 동적 필터 적용
GROUP BY T1.region_main
ORDER BY 도서관수 ASC; -- 가로 막대 차트를 위해 오름차순 정렬
"""
df_q1 = run_query(sql_q1, db_conn)

# [개선안 반영] 동적 인사이트 생성
if not df_q1.empty:
    top_region = df_q1.iloc[-1]
    avg_libs = df_q1['도서관수'].mean()
    insight_q1 = f"""
    ✅ **핵심 인사이트:** 
    선택된 지역 중 **{top_region['행정구역']}**의 도서관 수가 **{top_region['도서관수']:,}개**로 가장 많습니다. 
    이는 선택 지역 평균({avg_libs:,.1f}개) 대비 약 **{top_region['도서관수']/avg_libs*100 - 100:.1f}% 많은** 수치입니다.
    """
else:
    insight_q1 = "데이터가 없습니다."

# 시각화 및 출력
col_chart, col_sql = st.columns([3, 2])
with col_chart:
    fig_q1 = px.bar(df_q1, x='도서관수', y='행정구역', orientation='h', 
                    text_auto=True, title="지역별 도서관 수 현황")
    st.plotly_chart(fig_q1, use_container_width=True)
    st.info(insight_q1)
with col_sql:
    with st.expander("📜 실행된 SQL 쿼리 (JOIN & GROUP BY)", expanded=True):
        st.code(sql_q1, language='sql')

st.divider()


# ==============================================================================
# [분석 2] 지역별 사서 1명당 담당 장서 수 (인력 부하량)
# ==============================================================================
st.header("2. 지역별 사서 인력 부하량 (시군구 단위)")

# [개선안 반영] NULLIF를 사용한 0 나누기 방지 및 사서 0명 지역 필터링
sql_q2 = f"""
SELECT 
    T1.region_main as 행정구역,
    T1.region_sub as 시군구,
    SUM(T3.장서수) as 총장서수,
    SUM(T3.사서수) as 총사서수,
    -- 사서 합계가 0이면 결과는 NULL이 됨 (SQLite에서 inf 방지)
    CAST(SUM(T3.장서수) AS FLOAT) / NULLIF(SUM(T3.사서수), 0) as 사서1인당장서수
FROM table_region AS T1
JOIN table_library AS T2 ON T1.region_id = T2.region_id
JOIN table_stats AS T3 ON T2.library_code = T3.도서관코드
WHERE T1.region_main IN ({region_filter_str})
GROUP BY T1.region_main, T1.region_sub
HAVING 총사서수 > 0 -- 사서가 배치된 지역만 분석 대상에 포함
ORDER BY 사서1인당장서수 DESC;
"""
df_q2 = run_query(sql_q2, db_conn)

# [개선안 반영] 동적 인사이트 및 전국 평균 비교
if not df_q2.empty:
    # 전국 평균 계산 (별도 쿼리 없이 대략적 계산)
    national_avg_load = df_q2['총장서수'].sum() / df_q2['총사서수'].sum()
    most_burdened = df_q2.iloc[0]
    insight_q2 = f"""
    ✅ **핵심 인사이트:** 
    분석 대상 중 사서 1인당 업무 부하가 가장 높은 곳은 **{most_burdened['행정구역']} {most_burdened['시군구']}**입니다. 
    사서 한 명이 약 **{most_burdened['사서1인당장서수']:,.0f}권**을 담당하고 있으며, 이는 전체 평균(약 {national_avg_load:,.0f}권)보다 높습니다.
    (트리맵에서 붉은색이 진하고 타일 크기가 클수록 인력 충원이 시급한 지역입니다.)
    """
else:
    insight_q2 = "해당 조건에 맞는 데이터가 없습니다."

fig_q2 = px.treemap(
    df_q2,
    path=[px.Constant("전체(선택지역)"), '행정구역', '시군구'],
    values='총장서수',          # 타일 크기
    color='사서1인당장서수',    # 타일 색상
    color_continuous_scale='RdBu_r', # 빨간색=높음(부하), 파란색=낮음(여유)
    # [개선안 반영] 툴팁에 상세 정보 표시
    hover_data={'총사서수':':,', '사서1인당장서수':':,.0f', '총장서수':':,'},
    title="계층형 트리맵: 장서 규모 대비 사서 부하량"
)
fig_q2.update_traces(root_color="lightgrey")

st.plotly_chart(fig_q2, use_container_width=True)
col_ins, col_sql2 = st.columns([3, 2])
with col_ins:
    st.info(insight_q2)
with col_sql2:
    with st.expander("📜 실행된 SQL 쿼리 (3-Way JOIN & NULLIF)", expanded=False):
        st.code(sql_q2, language='sql')

st.divider()


# ==============================================================================
# [분석 3] 예산 대비 대출 실적 효율성 (가성비 분석)
# ==============================================================================
st.header("3. 예산 투입 대비 대출 실적 효율성")

# [개선안 반영] 효율성 지표(예산 1천원당 대출권수) SQL 내 계산 추가
sql_q3 = f"""
SELECT 
    T1.region_main as 행정구역,
    COUNT(T2.library_code) as 도서관수,
    AVG(T3.자료구입비_천원) as 평균자료구입비,
    SUM(T3.대출권수) as 총대출권수,
    -- 효율성: 총 대출권수 / 총 자료구입비(천원)
    SUM(T3.대출권수) / NULLIF(SUM(T3.자료구입비_천원), 0) as 예산효율성_비율
FROM table_region AS T1
JOIN table_library AS T2 ON T1.region_id = T2.region_id
JOIN table_stats AS T3 ON T2.library_code = T3.도서관코드
WHERE T1.region_main IN ({region_filter_str})
GROUP BY T1.region_main
HAVING 평균자료구입비 > 0 AND 총대출권수 > 0 -- 유의미한 데이터만 표시
ORDER BY 평균자료구입비 DESC;
"""
df_q3 = run_query(sql_q3, db_conn)

# [개선안 반영] 동적 인사이트
if not df_q3.empty:
    most_efficient = df_q3.sort_values('예산효율성_비율', ascending=False).iloc[0]
    insight_q3 = f"""
    ✅ **핵심 인사이트:** 
    자료구입비 투입 대비 대출 실적(가성비)이 가장 우수한 지역은 **{most_efficient['행정구역']}**입니다.
    (자료구입비 1천원당 약 {most_efficient['예산효율성_비율']:.1f}권 대출)
    전반적으로 예산 투입이 많을수록 대출 실적도 증가하는 우상향 경향을 보입니다.
    """
else:
    insight_q3 = "표시할 데이터가 충분하지 않습니다."

# [개선안 반영] 로그 스케일 적용 여부에 따른 축 설정
chart_log_setting = True if use_log_scale else False

fig_q3 = px.scatter(
    df_q3,
    x='평균자료구입비',
    y='총대출권수',
    size='도서관수',
    color='행정구역',
    # [개선안 반영] 로그 스케일 적용
    log_x=chart_log_setting, 
    log_y=chart_log_setting,
    # [개선안 반영] 툴팁에 효율성 지표 추가
    hover_data={'예산효율성_비율':':.2f', '도서관수':True},
    text='행정구역',
    title=f"평균 자료구입비 vs 총 대출권수 (Log Scale: {'On' if chart_log_setting else 'Off'})",
    labels={'평균자료구입비': '평균 자료구입비(천원)', '총대출권수': '총 대출권수'},
    size_max=60
)
fig_q3.update_traces(textposition='top center')

col_chart3, col_sql3 = st.columns([3, 2])
with col_chart3:
    st.plotly_chart(fig_q3, use_container_width=True)
    st.info(insight_q3)
with col_sql3:
    st.markdown("<br>", unsafe_allow_html=True) # 간격 조정용
    with st.expander("📜 실행된 SQL 쿼리 (집계 & 효율성 계산)", expanded=True):
        st.code(sql_q3, language='sql')
