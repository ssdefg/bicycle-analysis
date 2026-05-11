import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
import os

# --------------------------------------------------
# 1. 환경 설정 및 파일 경로 지정
# --------------------------------------------------
st.set_page_config(
    page_title="전국 공공도서관 데이터 분석 DB",
    page_icon="📚",
    layout="wide"
)

# [핵심 요구사항 1 & 4] 배포 최적화를 위한 상대 경로 설정
# 사용자가 파일을 업로드하지 않고, 앱과 동일한 위치의 'library.csv'를 자동으로 읽습니다.
DATA_FILE = 'library.csv'

# --------------------------------------------------
# 2. 데이터 로드 및 DB 구축 함수 (캐싱 적용)
# --------------------------------------------------
@st.cache_resource
def load_and_normalize_data(csv_path):
    """
    지정된 경로(상대 경로)의 CSV 파일을 읽어 인코딩을 처리하고,
    3개의 정규화된 테이블로 나누어 SQLite 인메모리 DB에 저장한 후 연결 객체를 반환합니다.
    """
    # [핵심 요구사항 2] 파일 존재 여부 확인
    if not os.path.exists(csv_path):
        st.error(f"❌ 데이터 파일('{csv_path}')을 찾을 수 없습니다.")
        st.markdown("""
        **[해결 방법]**
        이 스트림릿 앱(`app.py`)이 있는 동일한 폴더에 
        **`library.csv`** 파일이 존재하는지 확인해주세요.
        """)
        st.stop()

    # [핵심 요구사항 2] 인코딩 예외 처리 (순차적 시도)
    try:
        # 1. 우선 UTF-8-SIG (BOM 포함 UTF-8, 공공데이터 표준) 시도
        df_raw = pd.read_csv(csv_path, encoding='utf-8-sig')
    except UnicodeDecodeError:
        try:
            # 2. 실패 시 CP949 (EUC-KR 확장, 구형 엑셀 파일) 시도
            df_raw = pd.read_csv(csv_path, encoding='cp949')
        except Exception as e_cp949:
             st.error(f"인코딩 오류 발생: 파일을 읽을 수 없습니다.\n(UTF-8-SIG 및 CP949 시도 실패)\n상세 에러: {e_cp949}")
             st.stop()
    except Exception as e:
         st.error(f"파일 읽기 중 알 수 없는 오류 발생: {e}")
         st.stop()

    # --- 데이터 전처리 및 컬럼 매핑 ---
    try:
        # 실제 CSV 컬럼명과 내부 변수명 매핑
        column_mapping = {
            '도서관코드': 'library_code',
            '도서관명': 'library_name',
            '행정구역': 'region_main',
            '시군구': 'region_sub',
            '도서관구분': 'library_type',
            '장서수(인쇄)': 'book_count',       
            '사서수': 'librarian_count',
            '대출권수': 'loan_count',
            '자료구입비(천원)': 'budget_buying'
        }
        
        # 필수 컬럼 존재 여부 확인
        missing_cols = [col for col in column_mapping.keys() if col not in df_raw.columns]
        if missing_cols:
             st.error(f"CSV 파일에 다음 필수 컬럼이 없습니다: {missing_cols}.\n올바른 데이터 파일을 준비해주세요.")
             st.stop()

        # 필요한 컬럼만 선택 및 영문명으로 변경
        df_selected = df_raw[column_mapping.keys()].rename(columns=column_mapping)

        # 숫자형 컬럼 결측치 및 오류 처리 (문자열 혼입 대비)
        numeric_cols = ['book_count', 'librarian_count', 'loan_count', 'budget_buying']
        for col in numeric_cols:
             df_selected[col] = pd.to_numeric(df_selected[col], errors='coerce').fillna(0)

    except Exception as e:
        st.error(f"데이터 전처리 중 오류 발생: {e}")
        st.stop()

    # [핵심 요구사항 3] SQLite 인메모리 DB 정규화 및 구축
    conn = sqlite3.connect(':memory:', check_same_thread=False)
    
    # --- Normalization Process ---
    
    # Table 1: table_region (지역 마스터)
    # 행정구역과 시군구의 고유한 조합으로 region_id 생성
    df_region = df_selected[['region_main', 'region_sub']].drop_duplicates().reset_index(drop=True)
    df_region['region_id'] = df_region.index + 1 # PK 생성
    df_region = df_region[['region_id', 'region_main', 'region_sub']]
    
    df_region.to_sql('table_region', conn, index=False, if_exists='replace',
                     dtype={'region_id': 'INTEGER PRIMARY KEY'})

    # Table 2: table_library (도서관 기본 정보) - region_id FK 추가
    df_lib_merged = pd.merge(
        df_selected[['library_code', 'library_name', 'library_type', 'region_main', 'region_sub']],
        df_region,
        on=['region_main', 'region_sub'],
        how='left'
    )
    df_library = df_lib_merged[['library_code', 'region_id', 'library_name', 'library_type']]
    df_library.to_sql('table_library', conn, index=False, if_exists='replace',
                      dtype={'library_code': 'TEXT PRIMARY KEY', 'region_id': 'INTEGER'})
    
    # Table 3: table_stats (도서관별 통계 수치)
    df_stats = df_selected[['library_code', 'book_count', 'librarian_count', 'loan_count', 'budget_buying']]
    # SQL 가독성을 위해 한글 컬럼명 사용 (요구사항 반영)
    df_stats.columns = ['도서관코드', '장서수', '사서수', '대출권수', '자료구입비']
    df_stats.to_sql('table_stats', conn, index=False, if_exists='replace',
                    dtype={'도서관코드': 'TEXT PRIMARY KEY'})

    return conn

def run_query(query, db_connection):
    """SQL 쿼리를 실행하고 결과를 DataFrame으로 반환하는 헬퍼 함수"""
    return pd.read_sql(query, db_connection)

# --------------------------------------------------
# 3. 메인 대시보드 실행 로직 (즉시 실행)
# --------------------------------------------------

# 3.1 데이터 자동 로드 시도
try:
    # 앱 시작 시 자동으로 로컬 파일 로드
    db_conn = load_and_normalize_data(DATA_FILE)
    # st.toast(f"파일 로드 완료: {DATA_FILE}", icon="✅") # (선택사항) 로드 알림
except Exception as e:
    # load_and_normalize_data 내부에서 처리되지 않은 예상치 못한 오류 대비
    st.error(f"시스템 오류: 데이터베이스 초기화 실패\n{e}")
    st.stop()


# 3.2 대시보드 헤더 및 스키마 정보
st.title("📚 전국 공공도서관 데이터 분석 (SQL 기반)")
st.markdown(f"""
로컬 파일(`{DATA_FILE}`)을 자동으로 읽어 **SQLite 인메모리 DB**로 정규화했습니다.
아래의 모든 차트는 실제 **SQL JOIN 쿼리**를 수행하여 산출된 결과입니다.
""")

with st.expander("참고: DB 스키마 설계 보기"):
    st.markdown("""
    - **`table_region` (지역 마스터)**: region_id(PK), 행정구역(시도), 시군구
    - **`table_library` (도서관 정보)**: library_code(PK), region_id(FK), 도서관명, 도서관구분
    - **`table_stats` (통계 수치)**: 도서관코드(FK), 장서수, 사서수, 대출권수, 자료구입비
    """)
st.divider()


# ==============================================================================
# [분석 1] 행정구역별 도서관 인프라 집중도
# ==============================================================================
st.header("1. 행정구역별 도서관 수 (인프라 집중도)")
st.markdown("### ❓ 질문: 어느 광역 행정구역에 공공도서관이 가장 많이 분포하는가?")

# SQL 작성
sql_q1 = """
SELECT 
    T1.region_main as 행정구역,
    COUNT(T2.library_code) as 도서관수
FROM table_region AS T1
JOIN table_library AS T2 ON T1.region_id = T2.region_id
GROUP BY T1.region_main
ORDER BY 도서관수 DESC;
"""
with st.expander("SQL 쿼리 보기"):
    st.code(sql_q1, language='sql')

# 쿼리 실행
df_q1 = run_query(sql_q1, db_conn)

# 시각화
tab1, tab2 = st.tabs(["📊 차트 보기", "📄 데이터 보기"])
with tab1:
    fig_q1 = px.bar(df_q1, x='행정구역', y='도서관수',
                    text_auto=True, color='도서관수', color_continuous_scale='Blues')
    st.plotly_chart(fig_q1, use_container_width=True)
with tab2:
    st.dataframe(df_q1, hide_index=True, use_container_width=True)

st.divider()


# ==============================================================================
# [분석 2] 사서 1인당 관리 장서 수 (업무 효율성/과부하)
# ==============================================================================
st.header("2. 사서 1인당 관리 장서 수 (업무 부하 분석)")
st.markdown("### ❓ 질문: 지역별 사서 한 명이 감당해야 하는 평균 장서 수는 얼마인가?")

# SQL 작성 (3중 JOIN, NULLIF로 0 나누기 방지)
sql_q2 = """
SELECT 
    T1.region_main as 행정구역,
    T1.region_sub as 시군구,
    SUM(T3.장서수) as 총장서수,
    SUM(T3.사서수) as 총사서수,
    -- 사서수가 0이면 NULL을 반환하여 나누기 오류 방지
    ROUND(CAST(SUM(T3.장서수) AS FLOAT) / NULLIF(SUM(T3.사서수), 0), 0) as 사서1인당장서수
FROM table_region AS T1
JOIN table_library AS T2 ON T1.region_id = T2.region_id
JOIN table_stats AS T3 ON T2.library_code = T3.도서관코드
GROUP BY T1.region_main, T1.region_sub
HAVING 총사서수 > 0 -- 사서가 배치된 지역만 분석
ORDER BY 사서1인당장서수 DESC;
"""
with st.expander("SQL 쿼리 보기"):
    st.code(sql_q2, language='sql')

# 쿼리 실행
df_q2 = run_query(sql_q2, db_conn)

# 시각화 (Treemap)
st.markdown("**시각화: 계층형 트리맵 (붉은색일수록 사서 1인당 부담이 높음)**")
fig_q2 = px.treemap(df_q2, 
                    path=[px.Constant("전국"), '행정구역', '시군구'], 
                    values='총장서수',         # 타일 크기: 전체 장서 규모
                    color='사서1인당장서수',   # 타일 색상: 업무 부하 지표
                    color_continuous_scale='RdBu_r', # Red=높음(부하大), Blue=낮음(여유)
                    hover_data=['총사서수', '사서1인당장서수'])
fig_q2.update_traces(root_color="lightgrey")
st.plotly_chart(fig_q2, use_container_width=True)

st.divider()


# ==============================================================================
# [분석 3] 자료 구입비 예산 대비 대출 실적 (가성비)
# ==============================================================================
st.header("3. 자료 구입비 예산 투입 대비 대출 실적")
st.markdown("### ❓ 질문: 자료구입비를 많이 쓰는 지역이 실제로 대출 실적도 높은가? (예산 효율성)")

# SQL 작성
sql_q3 = """
SELECT 
    T1.region_main as 행정구역,
    COUNT(T2.library_code) as 도서관수,
    ROUND(AVG(T3.자료구입비), 0) as 평균자료구입비_천원,
    SUM(T3.대출권수) as 총대출권수,
    -- (총대출권수 / 총자료구입비_원) 계산. 자료구입비가 0이면 NULL 처리.
    ROUND(CAST(SUM(T3.대출권수) AS FLOAT) / NULLIF(SUM(T3.자료구입비) * 1000, 0), 5) as 예산1원당대출실적
FROM table_region AS T1
JOIN table_library AS T2 ON T1.region_id = T2.region_id
JOIN table_stats AS T3 ON T2.library_code = T3.도서관코드
GROUP BY T1.region_main
HAVING 평균자료구입비_천원 > 0 -- 예산이 있는 지역만
ORDER BY 평균자료구입비_천원 DESC;
"""
with st.expander("SQL 쿼리 보기"):
    st.code(sql_q3, language='sql')

# 쿼리 실행
df_q3 = run_query(sql_q3, db_conn)

# 시각화 (Bubble Chart)
fig_q3 = px.scatter(df_q3, 
                    x='평균자료구입비_천원', 
                    y='총대출권수', 
                    size='도서관수',   # 버블 크기
                    color='행정구역',     # 버블 색상 구분
                    hover_name='행정구역',
                    text='행정구역',
                    title='평균 자료구입비 vs 총 대출권수 상관관계 (버블크기: 도서관 수)')
fig_q3.update_traces(textposition='top center')
st.plotly_chart(fig_q3, use_container_width=True)

st.divider()


# ==============================================================================
# [분석 4] 도서관 유형별 운영 성과 비교
# ==============================================================================
st.header("4. 도서관 유형별 평균 실적 비교")
st.markdown("### ❓ 질문: 도서관 운영 주체(유형)에 따라 평균 대출 실적에 차이가 있는가?")

# SQL 작성
sql_q4 = """
SELECT 
    T2.library_type as 도서관구분,
    COUNT(T2.library_code) as 도서관수,
    ROUND(AVG(T3.대출권수), 0) as 평균대출권수,
    ROUND(AVG(T3.장서수), 0) as 평균장서수
FROM table_library AS T2
JOIN table_stats AS T3 ON T2.library_code = T3.도서관코드
GROUP BY T2.library_type
HAVING 도서관수 >= 5 -- 유의미한 비교를 위해 5개 미만 유형 제외
ORDER BY 평균대출권수 DESC;
"""
with st.expander("SQL 쿼리 보기"):
    st.code(sql_q4, language='sql')

# 쿼리 실행
df_q4 = run_query(sql_q4, db_conn)

# 시각화 (복합 차트)
col1, col2 = st.columns([1, 2])
with col1:
    st.markdown("##### 도서관 유형 비율")
    fig_q4_pie = px.pie(df_q4, values='도서관수', names='도서관구분', hole=0.4)
    fig_q4_pie.update_layout(margin=dict(t=0, b=0, l=0, r=0), height=300)
    st.plotly_chart(fig_q4_pie, use_container_width=True)

with col2:
    st.markdown("##### 유형별 평균 대출 및 장서 수")
    # 이중축 Bar Chart를 위해 데이터 형태 변환 (Melt)
    df_melted = df_q4.melt(id_vars=['도서관구분'], value_vars=['평균대출권수', '평균장서수'], var_name='지표', value_name='권수')
    fig_q4_bar = px.bar(df_melted, x='도서관구분', y='권수', color='지표', barmode='group')
    fig_q4_bar.update_layout(margin=dict(t=20, b=0, l=0, r=0), height=350, legend_title_text='')
    st.plotly_chart(fig_q4_bar, use_container_width=True)