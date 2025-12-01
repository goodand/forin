import streamlit as st
import pandas as pd
import json
import os
from openai import OpenAI
from dotenv import load_dotenv
#from faq_rag import load_faiss_index, search_faq, format_faq_context

# 환경변수 로드
load_dotenv()

# OpenAI 클라이언트 초기화
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 페이지 설정
st.set_page_config(
    page_title="복지나침반 🧭",
    page_icon="🧭",
    layout="centered"
)

# CSS 스타일
st.markdown("""
<style>
    /* 어시스턴트 메시지 아바타 정렬 */
    [data-testid="stChatMessageAssistant"] {
        align-items: flex-start !important;
    }

    [data-testid="stChatMessageAssistant"] img {
        margin-top: -10px !important;
    }
    /* 기본 Streamlit 채팅 숨기기 */
    [data-testid="stChatMessage"] {
        background: transparent !important;
    }
    
    /* 사용자 메시지 컨테이너 */
    .user-msg-row {
        display: flex;
        justify-content: flex-end;
        align-items: center;
        gap: 8px;
        margin: 16px 0;
    }
    
    /* 사용자 말풍선 */
    .user-bubble {
        background: #f0f0f0;
        color: #333;
        padding: 12px 16px;
        border-radius: 20px;
        max-width: 70%;
        font-size: 15px;
        line-height: 1.5;
    }
    
    /* 사용자 아바타 */
    .user-avatar {
        width: 36px;
        height: 36px;
        background: #ff6b6b;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-size: 14px;
        font-weight: bold;
    }
    
    /* 복지 카드 스타일 */
    .welfare-card {
        background: #ffffff;
        border: 1px solid #e8e8e8;
        border-radius: 16px;
        padding: 20px;
        margin: 12px 0;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    }
    
    .welfare-card-badge {
        display: inline-block;
        background: #fff0f0;
        color: #e74c3c;
        padding: 4px 12px;
        border-radius: 4px;
        font-size: 12px;
        font-weight: 600;
        margin-bottom: 8px;
    }
    
    .welfare-card-title {
        font-size: 17px;
        font-weight: 600;
        color: #1a1a1a;
        margin: 8px 0 12px 0;
    }
    
    .welfare-card-content {
        color: #666;
        font-size: 14px;
        line-height: 1.7;
    }
    
    .welfare-card-content p {
        margin: 6px 0;
    }
    
    .welfare-card-button {
        display: inline-block;
        margin-top: 12px;
        padding: 8px 16px;
        border: 1px solid #ddd;
        border-radius: 6px;
        font-size: 13px;
        color: #333;
        background: #fff;
        cursor: pointer;
    }
</style>
""", unsafe_allow_html=True)


import re

# ✅ 서울 25개 자치구(정확한 매칭용)
SEOUL_GU = [
    "종로구","중구","용산구","성동구","광진구","동대문구","중랑구","성북구","강북구","도봉구","노원구",
    "은평구","서대문구","마포구","양천구","강서구","구로구","금천구","영등포구","동작구","관악구",
    "서초구","강남구","송파구","강동구"
]

# ✅ "강남" 처럼 '구' 없이 쓰는 케이스도 잡되, '중구'처럼 한 글자(중) 스템은 오탐 위험이라 제외
SEOUL_GU_STEMS = [g[:-1] for g in SEOUL_GU if len(g[:-1]) >= 2]  # "강남", "송파" 등
# 전체 후보(긴 것부터 매칭되게 정렬)
SEOUL_GU_TOKENS = sorted(set(SEOUL_GU + SEOUL_GU_STEMS), key=len, reverse=True)
SEOUL_GU_PATTERN = re.compile("|".join(map(re.escape, SEOUL_GU_TOKENS)))

def extract_user_gu(residence: str):
    """
    사용자가 말한 residence에서 서울 '자치구' 1개를 최대한 뽑아 정규화해 반환.
    예) "서울 강남", "강남역 근처" -> "강남구"
    """
    if not isinstance(residence, str) or not residence.strip():
        return None
    m = SEOUL_GU_PATTERN.search(residence)
    if not m:
        return None
    token = m.group(0)
    return token if token.endswith("구") else f"{token}구"

def extract_seoul_gu_set(residence_required: str) -> set:
    """
    residence_required에서 언급된 서울 자치구들을 set으로 추출.
    예) "강남·서초·송파구 거주" -> {"강남구","서초구","송파구"}
    """
    if not isinstance(residence_required, str) or not residence_required.strip():
        return set()

    hits = set()
    for m in SEOUL_GU_PATTERN.finditer(residence_required):
        token = m.group(0)
        gu = token if token.endswith("구") else f"{token}구"
        # 안전장치: 최종이 서울 25개 안에 없으면 버림(오탐 방지)
        if gu in SEOUL_GU:
            hits.add(gu)
    return hits

def extract_excluded_seoul_gu_set(residence_required: str) -> set:
    """
    'OO구 제외/미포함/빼고' 같은 문구에서 제외되는 구를 잡아냄.
    예) "강남구 제외" -> {"강남구"}
    """
    if not isinstance(residence_required, str) or not residence_required.strip():
        return set()

    excluded = set()
    text = residence_required.replace(" ", "")

    # ✅ 패턴: (구명)(구)? + (제외/미포함/빼고/제한)
    #    - 토큰은 SEOUL_GU_PATTERN으로 잡고, 주변에 제외 키워드가 있는지 확인하는 방식
    for m in SEOUL_GU_PATTERN.finditer(text):
        token = m.group(0)
        gu = token if token.endswith("구") else f"{token}구"
        if gu not in SEOUL_GU:
            continue

        tail = text[m.end(): m.end() + 8]   # 뒤쪽 몇 글자만 확인(성능+정확도)
        if any(k in tail for k in ["제외", "미포함", "빼고", "제한"]):
            excluded.add(gu)

        head = text[max(0, m.start()-8): m.start()]  # "OO구를 제외한" 같은 케이스 대비
        if any(k in head for k in ["제외", "미포함", "빼고", "제한"]):
            excluded.add(gu)

    return excluded

def requires_seoul(residence_required: str) -> bool:
    """
    residence_required가 '서울(또는 서울 자치구)'를 요구하는지 여부.
    - '서울', '서울시', '서울특별시', '서울시민', 또는 자치구가 언급되면 True
    - 아무것도 없으면 False (전국/무관으로 간주)
    """
    if not isinstance(residence_required, str) or not residence_required.strip():
        return False

    txt = residence_required.replace(" ", "")
    # 자치구 직접 언급이면 서울 요구로 간주
    if extract_seoul_gu_set(txt):
        return True

    # 서울 키워드가 명확하면 True
    if any(k in txt for k in ["서울", "서울시", "서울특별시", "서울시민", "서울거주"]):
        return True

    return False


@st.cache_data
def load_welfare_data():
    """통합된 welfare_save.csv 파일 로드"""
    try:
        df = pd.read_csv("data/welfare_data.csv", encoding='utf-8')

        # ✨ 필수 컬럼 리스트 (안전하게 누락 컬럼 채우기)
        required_cols = [
            'id', 'program_name', 'category_primary', 'category_secondary', 'description',
            'age_min', 'age_max', 'income_type', 'income_max',
            'residence_required', 'employment_status', 'special_conditions',
            'support_type', 'support_amount', 'support_duration',
            'how_to_apply', 'contact', 'difficulty_level', 'source'
        ]

        # 🔧 없는 컬럼 자동 생성 (값은 None)
        for col in required_cols:
            if col not in df.columns:
                df[col] = None

        # 🎯 숫자 컬럼 변환 (강제숫자화, NaN 허용)
        df['age_min'] = pd.to_numeric(df['age_min'], errors='coerce')
        df['age_max'] = pd.to_numeric(df['age_max'], errors='coerce')
        df['income_max'] = pd.to_numeric(df['income_max'], errors='coerce')

        return df

    except Exception as e:
        st.error(f"복지 데이터 로드 실패: {e}")
        return pd.DataFrame()

def detect_intent(user_message, last_intent=None):
    text = user_message.strip()

    # 신청 방법 요청 키워드 (apply 모드)
    apply_keywords = [
        "신청 방법",
        "어떻게 신청",
        "어디서 신청",
        "신청하려면",
        "신청 절차",
        "서류 뭐 필요",
        "준비 서류"
    ]
    if any(k in text for k in apply_keywords):
        return "apply"

    # 디테일 요청 키워드
    detail_keywords = [
        "자세히 알려줘",
        "자세히 설명",
        "자세히 알고 싶",
        "조건 좀 자세히",
        "좀 더"
    ]
    if any(k in text for k in detail_keywords):
        return "detail"

    # 적격성 판단 키워드
    eligibility_keywords = [
        "신청 가능해",
        "신청할 수 있",
        "받을 수 있어",
        "해당돼",
        "대상인가",
        "신청 가능",      # ← "해" 제거! "신청 가능한", "신청 가능해" 둘 다 매칭
        "신청할 수 있",
        "받을 수 있",     # ← "어" 제거!
        "해당돼",
        "해당되",         # ← 추가
        "대상인가",
        "대상이야",       # ← 추가
        "지원 가능",      # ← 추가
        "자격이 되",
        "대상",
        "자격"# ← 추가
]
    
    if any(k in text for k in eligibility_keywords):
        return "eligibility"

    # 직전이 detail/eligibility/apply면 유지
    if last_intent in ["detail", "eligibility", "apply"]:
        reset_keywords = ["다른 복지", "다른 제도", "처음부터"]
        if any(k in text for k in reset_keywords):
            return "match"
        return last_intent

    return "match"


def extract_user_info(user_message: str, conversation_history: list) -> dict:
    """GPT를 사용해 사용자 정보 추출"""
    
    system_prompt = """당신은 사용자의 메시지에서 복지 매칭에 필요한 정보를 추출하는 AI입니다.

다음 정보를 JSON 형식으로 추출하세요:
- age: 나이 (숫자, 없으면 null)
- income: 월소득 (숫자, 만원 단위, 없으면 null) - "백수/무직"이면 0
- income_type: "월" 또는 "연" (없으면 null)
- income_scope: "개인" 또는 "부부합산" (명시되지 않았으면 null) <<여기 수정함
- residence: 거주지역 (알 수 있으면 최대한 구 단위까지, 예: "서울 강서구", "서울 송파구", 알 수 없으면 null)
- is_seoul_resident: 서울 거주 여부 (true, false, null 중 하나)
  * 예시
    - "서울 강서구에서 전세로 살아요" → residence: "서울 강서구", is_seoul_resident: true
    - "강남역 근처 월세 살아요" → residence: "서울 강남구"로 추정 가능 → is_seoul_resident: true
    - "삼성중앙역 근처 월세" → 서울 지하철역이므로 → residence: "서울 강남구"로 추정, is_seoul_resident: true
    - "부산 사상구 고시원" → residence: "부산 사상구", is_seoul_resident: false
    - "시청역 근처 월세"처럼 도시를 특정하기 어려운 경우 → residence: null, is_seoul_resident: null
- - employment_status: 고용상태 - 아래 규칙 적용:
  * "취준생", "취업준비", "구직중", "일자리 찾는 중" → "구직중"
  * "백수", "무직", "일 안 함" → "무직"  
  * "회사 다님", "직장인", "재직중" → "재직"
  * "대학생", "학교 다님" → "학생"
  * "프리랜서", "알바" → "프리랜서"
- housing_type: 주거형태 ("월세", "전세", "자가", "고시원", 없으면 null)
- special_conditions: 특수조건 리스트 (예: ["청년", "한부모", "장애인"], 없으면 [])
- needs: 필요한 지원 종류 (예: ["주거", "생활비", "취업"], 없으면 [])
- household_size: 함께 사는 가구원 수 (숫자, 없으면 null)
  * "저 혼자 살아요" → 1
  * "배우자랑 둘이 살아요" → 2
  * "아이 둘 있어요" → 4 (부부+아이2)


대화 맥락을 고려하여 이전에 언급된 정보도 포함하세요.
반드시 유효한 JSON만 출력하세요. 다른 텍스트는 절대 포함하지 마세요.
JSON 외의 설명, 인사말, 마크다운 코드블록(```) 없이 순수 JSON만 출력하세요."""

    messages = [{"role": "system", "content": system_prompt}]
    
    # 이전 대화 컨텍스트 추가
    for msg in conversation_history[-6:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    
    messages.append({"role": "user", "content": user_message})
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.1,
            max_tokens=500
        )
        
        result = response.choices[0].message.content.strip()
        
        # JSON 파싱 전처리 강화
        # 마크다운 코드블록 제거
        if "```json" in result:
            result = result.split("```json")[1].split("```")[0]
        elif "```" in result:
            result = result.split("```")[1].split("```")[0]
        
        # 앞뒤 공백 제거
        result = result.strip()
        
        return json.loads(result)
    
    except json.JSONDecodeError as e:
        #st.error(f"정보 추출 오류: JSON 파싱 실패 - {e}")
        return {}
    except Exception as e:
        st.error(f"정보 추출 오류: {e}")
        return {}

CATEGORIES = ["교육","보호","돌봄","생활지원","정신건강","일자리","서민금융","마음건강","금융","생활","주거","창업"]

def extract_requested_category(text: str) -> str | None:
    if not text:
        return None
    found = [c for c in CATEGORIES if c in text]
    return found[-1] if found else None

def match_welfare_programs(user_info: dict, df: pd.DataFrame, include_category: str | None = None, exclude_programs: list[str] | None = None) -> pd.DataFrame:
    """사용자 정보에 맞는 복지 프로그램 매칭 - 다양한 카테고리에서 추천"""
    
    if df.empty:
        return df
    
    matched = df.copy()
    
    # 나이 필터링
    if user_info.get('age'):
        age = user_info['age']
        mask = (
            (matched['age_min'].isna() | (matched['age_min'] <= age)) &
            (matched['age_max'].isna() | (matched['age_max'] >= age))
        )
        matched = matched[mask]
    
    # 특수조건 필터링 (신혼부부, 한부모 등은 해당자만)
    def check_special_conditions(row_conditions):
        if pd.isna(row_conditions) or row_conditions == '' or row_conditions == '없음':
            return True  # 조건 없으면 누구나 가능
        
        row_conds = str(row_conditions).lower()
        user_special = [s.lower() for s in user_info.get('special_conditions', [])]
        
        # 신혼부부 복지는 신혼부부만
        if '신혼' in row_conds:
            if not any('신혼' in s for s in user_special):
                return False
        
        # 한부모 복지는 한부모만
        if '한부모' in row_conds:
            if not any('한부모' in s for s in user_special):
                return False
        
        # 장애인 복지는 장애인만
        if '장애' in row_conds:
            if not any('장애' in s for s in user_special):
                return False
        
        # 다자녀 복지는 다자녀만
        if '다자녀' in row_conds:
            if not any('다자녀' in s for s in user_special):
                return False
            
        # 다문화 복지는 다문화만
        if '다문화' in row_conds:
            if not any('다문화' in s for s in user_special):
                return False        
        
        return True
    
    matched = matched[matched['special_conditions'].apply(check_special_conditions)]
    
    
    # 거주지 필터링
    if user_info.get('residence'):
        residence = user_info.get('residence', '')
        # ⭐ 서울 여부 판단 (정규식)
        import re
        seoul_keywords = r'(서울|종로|중구|용산|성동|광진|동대문|중랑|성북|강북|도봉|노원|은평|서대문|마포|양천|강서|구로|금천|영등포|동작|관악|서초|강남|송파|강동|왕십리|신촌|홍대|성수|잠실)'
        is_seoul = bool(re.search(seoul_keywords, residence, re.IGNORECASE))
        

        if residence and not is_seoul:
            # 서울 아니면 서울 전용 복지 제외
            matched = matched[
                matched['residence_required'].isna() | 
                ~matched['residence_required'].str.contains('서울', na=False)
        ]
            
    # 주거형태 기반 하드 필터 (전세 vs 월세)
    #housing = user_info.get('housing_type', '').strip()

    #if housing == '전세':
        # 순수 '월세' 복지 제거 (category_primary 주거 + category_secondary = '월세')
        #matched = matched[~(
        #    matched['category_primary'].fillna('').str.contains('주거', na=False) &
        #    matched['category_secondary'].fillna('').str.strip().eq('월세')
        #)]
    
    
    
    # 고용상태 필터링
    if user_info.get('employment_status'):
        emp_status = user_info['employment_status']
        def check_employment(row_status):
            if pd.isna(row_status) or row_status == '제한없음':
                return True
            if emp_status == '구직중' and '구직중' in str(row_status):
                return True
            if emp_status == '재직' and ('재직' in str(row_status) or '근로' in str(row_status)):
                return True
            if emp_status == '학생' and '학생' in str(row_status):
                return True
            return True
        matched = matched[matched['employment_status'].apply(check_employment)]
    
    # ⭐ 사용자 맥락 분석 → 관련 카테고리 도출
    relevant_categories = []
    
    # 주거 맥락
    housing = user_info.get('housing_type', '').strip()
    if housing:
        relevant_categories.append('주거')  # 기본 주거 관련은 포함
        # 주거 세부 타입에 따라 세분화
        if housing == '전세':
            relevant_categories.append('전세')
        elif housing == '월세':
            relevant_categories.append('월세')
        elif housing == '고시원':
            relevant_categories.append('고시원')
    
  
    
    # 취업 맥락
    emp = user_info.get('employment_status', '')
    if emp in ['구직중', '무직']:
        relevant_categories.append('일자리')
    
    # 소득 맥락
    income = user_info.get('income')
    if income is not None and income < 300:  # 월 300만원 이하
        relevant_categories.append('생활')
        relevant_categories.append('금융')
    
    # 특수조건 맥락
    special = user_info.get('special_conditions', [])
    if '한부모' in special or '장애인' in special:
        relevant_categories.append('생활')
    
    # 필요 분야 직접 추가
    needs = user_info.get('needs', [])
    for need in needs:
        if need not in relevant_categories:
            relevant_categories.append(need)
    
    # 기본: 아무 맥락 없으면 청년이면 일자리/주거 기본 추천
    if not relevant_categories and user_info.get('age'):
        age = user_info['age']
        if 19 <= age <= 39:
            relevant_categories = ['주거', '일자리', '생활']
    
    # ⭐ 우선순위 점수 계산
    def calc_priority(row):
        score = 0
        category = str(row.get('category_primary', '')).lower()
        description = str(row.get('description', '')).lower()
        program_name = str(row.get('program_name', '')).lower()
        support_amount = str(row.get('support_amount', '')).lower()
        row_special = str(row.get('special_conditions', '')).lower()
        
        subcat = str(row.get('category_secondary', '')).strip()  # 월세 / 전세 / 전월세 / 기타 / 임대
        housing = user_info.get('housing_type', '').strip()      # 사용자가 말한 주거형태
        
        # 👉 사용자 특수조건
        user_special = [s.lower() for s in user_info.get('special_conditions', [])]
        is_newlywed = any('신혼' in s for s in user_special)
        is_youth = any('청년' in s for s in user_special)
        
        # 1. 청년 특화 복지
        if '청년' in program_name:
            if is_newlywed:
                # 신혼부부에게는 청년 키워드를 약하게만 반영
                score += 10
            else:
                # 일반 청년에게는 강하게 반영
                score += 30

        # 2. 신혼부부 우선 (+큰 점수)
        if is_newlywed:
            # 이름/설명/특수조건 중 어디든 '신혼' 들어가면 최우선
            if '신혼' in program_name or '신혼' in description or '신혼' in row_special:
                score += 60

            # 신혼인데 '청년'인데 신혼 언급은 전혀 없는 프로그램이면 살짝 패널티
            if '청년' in program_name and '신혼' not in program_name and '신혼' not in description:
                score -= 10
        
        # 3. 실질적 금전 혜택 우선
        # 금액 파싱 시도
        import re
        amounts = re.findall(r'(\d+)만원', support_amount)
        if amounts:
            max_amount = max([int(a) for a in amounts])
            if max_amount >= 100:  # 100만원 이상
                score += 25
            elif max_amount >= 50:  # 50만원 이상
                score += 15
            elif max_amount >= 10:  # 10만원 이상
                score += 5
        
        # 4. 관련 카테고리 매칭
        for cat in relevant_categories:
            if cat in category:
                score += 20
            if cat in description or cat in program_name:
                score += 10
        
        # 5. 주거형태 세부 매칭 (개선 버전)
        if housing:
            # 월세 거주자
            if housing == '월세':
                if subcat == '월세':
                    score += 40      # 찐 핵심
                elif subcat == '전월세':
                    score += 25      # 그래도 꽤 관련
                elif subcat == '전세':
                    score -= 50      # 거의 빼버리기
                elif subcat in ['임대']:
                    score += 10      # 월/전세랑 둘 다 상관 있을 수 있으니 살짝 플러스

            # 전세 거주자
            elif housing == '전세':
                if subcat == '전세':
                    score += 40
                elif subcat == '전월세':
                    score += 25
                elif subcat == '월세':
                    score -= 50
                elif subcat in ['임대']:
                    score += 10

            # 그 외(고시원/기타)면 그냥 '주거' 카테고리 점수만으로 승부!ㅋㅋ    
        
        # 6. 고용상태 세부 매칭
        if emp in ['구직', '무직']:
            if '취업' in program_name or '일자리' in program_name or '자립' in program_name:
                score += 20
            if '청년통장' in program_name or '저축' in program_name:
                score += 20
        
        # 7. 핵심 키워드 보너스
        핵심_키워드 = ['자립', '통장', '지원금', '수당', '월세']
        for kw in 핵심_키워드:
            if kw in program_name:
                score += 10
        
        return score
    
    matched['priority'] = matched.apply(calc_priority, axis=1)
    #matched = matched.sort_values(['priority', 'difficulty_level'], ascending=[False, True])
    
    # ✅ (1) 예전에 추천한 프로그램 제외
    if exclude_programs:
        exclude_set = set(map(str, exclude_programs))
        matched = matched[~matched["program_name"].fillna("").astype(str).isin(exclude_set)]

    # ✅ (2) 요청 카테고리(교육/주거/금융 등)로 제한
    if include_category:
        matched = matched[matched["category_primary"].fillna("").astype(str).str.contains(include_category, na=False)]

    if 'difficulty_level' in matched.columns:
        matched = matched.sort_values(['priority', 'difficulty_level'], ascending=[False, True])
    else:
        matched = matched.sort_values('priority', ascending=False)
        
    # 주거 유형 하드 필터 (전세인데 월세 복지 끊어내기)
    #housing = user_info.get('housing_type', '').strip()
    #if housing:
     #   subcat = matched.get('category_secondary')
      #  if subcat is not None:
            # NaN 방지
       #     subcat = subcat.fillna('')
        #
       #     if housing == '전세':
                # 전세 거주자는 '월세' 전용 프로그램 제외
        #        mask_bad = subcat == '월세'
                # 혹시 DB에 잘못 들어갔을 걸 대비해서, 이름으로도 한 번 더 컷
         #       name_series = matched['program_name'].fillna('')
          #      mask_bad |= name_series.str.contains('청년월세지원', na=False)
           #     matched = matched[~mask_bad]

           # elif housing == '월세':
                # 월세 거주자는 '전세' 전용 프로그램 제외
             #   mask_bad = subcat == '전세'
            #    matched = matched[~mask_bad]
    
    # ⭐ 카테고리별로 골고루 선택
    final_results = []
    categories_selected = {}
    
    for _, row in matched.iterrows():
        cat = row.get('category_primary', '기타')
        if categories_selected.get(cat, 0) < 2:
            final_results.append(row)
            categories_selected[cat] = categories_selected.get(cat, 0) + 1
        if len(final_results) >= 10:
            break
    
    if final_results:
        return pd.DataFrame(final_results)
    return pd.DataFrame()


def generate_response(
    user_message: str,
    user_info: dict,
    matched_programs: pd.DataFrame,
    conversation_history: list,
    intent: str = "match",
    is_other_request: bool = False,
    already_programs: list | None = None,
) -> str:
    """GPT를 사용해 친근한 응답 생성"""
    
    # 매칭된 프로그램 정보 정리
    programs_text = ""
    if matched_programs is not None and not matched_programs.empty:
        for idx, row in matched_programs.head(5).iterrows():
            programs_text += f"""
- **{row['program_name']}** ({row.get('category_primary', '기타')})
  - 지원내용: {row.get('support_amount', '상세 내용 확인 필요')}
  - 신청방법: {row.get('how_to_apply', '홈페이지 확인')[:100]}...
  - 난이도: {'⭐' * int(row.get('difficulty_level', 3)) if pd.notna(row.get('difficulty_level')) else '보통'}
"""
    # 👉 모드 태그
  
    if intent == "apply":
        mode_tag = "[APPLY_MODE]"
    elif intent == "detail":
        mode_tag = "[DETAIL_MODE]"
    elif intent == "eligibility":
        mode_tag = "[ELIGIBILITY_MODE]"
    else:
        mode_tag = "[MATCH_MODE]"


    user_prompt = f"""{mode_tag}
사용자 메시지: {user_message}
추출된 사용자 정보: {json.dumps(user_info, ensure_ascii=False)}
매칭된 복지 프로그램:
{programs_text if programs_text else "아직 매칭된 프로그램이 없습니다. 추가 정보가 필요합니다."}

위 정보를 바탕으로 사용자에게 응답하세요.
"""
    
    system_prompt = """당신은 서울시 복지 상담사 '나침반'입니다.
    
    
## ⚠️ 중요: 서울시 전용 서비스
- 이 서비스는 **서울시 복지 전용** 챗봇입니다.
- 서울 외 지역(부산, 인천, 대구, 경기도 등) 복지는 **절대 추천하지 마세요**.
- 부산형 긴급복지, 인천 청년지원 등 다른 지역 복지 프로그램을 언급하지 마세요.
- 서울 외 지역 사용자에게는 복지로(bokjiro.go.kr) 안내만 하세요.
    
## 당신의 역할
- 사용자의 상황에 공감해주고,
- "지금 조건으로 왜 복지 혜택 가능성이 있는지"를 설명해주고,
- 아래에 표시될 **복지 카드**를 자연스럽게 보도록 유도하는 역할입니다.
- 복지 카드(혜택/대상/신청방법 요약)는 **파이썬 코드에서 따로 렌더링**되므로,
  당신이 직접 "📋 맞춤 복지 카드" 섹션이나 "자세히보기" 버튼 텍스트를 만들 필요는 없습니다.

---

## 답변 모드

당신은 다중 모드로 동작합니다.

### 1) [일반 추천 모드]  (= 대부분의 턴)

- 조건:
  - 기본 모드 (사용자 메시지에 `[DETAIL_MODE]`가 **없는** 경우)

- 해야 할 일:
  1. 공감
     - 예) "취준 중에 월세까지 부담하시면 정말 빠듯하실 것 같아요 😢"
  2. 요약
     - 예) "지금 말씀해주신 조건으로 볼 때, 몇 가지 복지 프로그램에 해당되실 가능성이 있어요."
     - 필요하다면 1~3개의 프로그램 이름 정도는 가볍게 언급해도 됩니다.
  3. 이유 설명
     - 왜 해당되는지 사람 눈높이로 설명
     - 예) "만 27세 청년이고, 서울 거주 1인 가구이며, 현재 취준 중에 소득이 없다는 점 때문에
            청년 자립 지원 + 월세 지원 쪽에서 혜택 가능성이 높아요."
  4. 다음 행동 유도
     - 예)
       - "아래 맞춤 복지 카드에서 자세한 내용 확인해보시고,"
       - "궁금하신 사항이나 신청 방법이 필요하시면 말씀해 주세요!"
       - "추가로 가족 상황, 건강보험, 부채 같은 정보도 알려주시면 더 많은 복지를 찾아드릴 수 있어요."

- 이 모드에서의 규칙:
  - 금액/기간/조건을 **아주 간단히 언급**하는 것은 괜찮지만,
    긴 스펙 나열이나 표 형식 설명은 피하세요.
    (그런 UI 요소는 코드에서 만들고, 당신은 자연스러운 말만 합니다.)

---

### 2) [상세 설명 모드]  (= 사용자가 특정 복지에 대해 "자세히 알려줘"라고 할 때)

- 조건:
  - 사용자 메시지에 `[DETAIL_MODE]`가 붙어 있으면 이 모드로 동작합니다.
    (예: `[DETAIL_MODE]\n청년 자립토대 지원 자세히 알려줘`)

- 해야 할 일:
  - 사용자가 묻는 **특정 복지 프로그램 1개**에 대해 아래 내용을 사람 말처럼 설명합니다:
    - 어떤 사람을 위한 제도인지 (대상, 연령, 소득, 거주지 등)
    - 어떤 혜택을 주는지 (금액, 횟수, 기간 등)
    - 신청 시 유의사항 & 조건 (예: 중위소득 %, 재직/구직 여부, 1회만 가능 등)
    - 대략적인 신청 방법 흐름 (예: "서울시 복지 포털에서 온라인 신청하는 방식입니다." 정도)

- 이 모드에서의 규칙:
  - "카드에서 확인하세요." 라고 떠넘기지 말고,
    사용자가 카드 없이도 이해할 수 있을 정도로 핵심 내용을 직접 설명하세요.
  - 그래도 너무 장황하게 표처럼 나열하지 말고,
    짧은 문단 + 불릿 정도로 정리된 설명을 유지하세요.
  - 이 모드에서도 "📋 맞춤 복지 카드", "자세히보기" 같은 표현은 쓰지 마세요.
    (카드는 이미 별도로 화면에 표시된다는 가정입니다.)
  - 마지막에는 항상 다음 행동을 제안하세요.
    - 예) "다른 복지들도 궁금하시면 이름을 말씀해 주세요."
    - 예) "가족 구성이나 부채 상황도 알려주시면, 추가로 도움이 될 수 있는 제도도 함께 찾아볼게요."
    
    ---
    
    ### 3) [적격성 판단 모드] (= 사용자가 "나 신청 가능해?" 등 물을 때)
    
    - 조건:
      - 사용자 메시지 앞부분에 `[ELIGIBILITY_MODE]` 태그가 붙어 있으면 이 모드로 동작합니다.
      - 예: `[ELIGIBILITY_MODE]\n내가 청년 자립토대 지원 신청할 수 있는 건가?`
      - 이 모드에서는 **매칭된 복지 프로그램 중 지금 컨텍스트에 해당하는 1개**만 판단한다고 가정하세요.
      - 사용자가 묻는 제도에 대해 "신청 가능성"만 판단해주고, 다른 복지 추천은 하지 마세요.
    
    - 해야 할 일:
      1. **결론 먼저 말하기**
         - 예) "지금까지 정보로 보면 신청 가능성이 **높아요 / 중간 / 낮아요 / 애매해요**."
      2. **왜 그렇게 판단했는지 조건 비교**
         - 사용자 조건 vs 제도 조건을 사람이 이해하기 쉽게 비교해서 설명
         - 예)
           - "✔️ 나이: 만 27세 → 제도 대상 연령(만 19~39세)에 포함돼요."
           - "✔️ 거주지: 서울 거주 → 지역 조건 충족"
           - "✔️ 소득: 현재 소득 없음 → 중위소득 50% 이하일 가능성이 매우 높아요."
      3. **추가로 확인이 필요한 조건 안내**
         - 예)
           - "월세 계약서 명의가 본인인지 한 번 확인해 보셔야 해요."
           - "건강보험이 피부양자인지, 지역가입자인지도 신청할 때 체크됩니다."
      4. **다음 행동 제안**
         - 예)
           - "이 조건들이 맞다면 실제로 신청해 보셔도 좋을 것 같아요."
           - "다른 복지들의 신청 가능 여부도 하나씩 같이 살펴볼까요?"
    
    - 이 모드에서의 규칙:
      - 카드 내용을 그대로 복사해서 다시 설명하지 마세요.
      - 지원 금액, 횟수, 세부 금액 숫자 나열은 최소화하고,
        "왜 대상인지 / 왜 아닐 수 있는지"에 집중하세요.
      - 프로그램 이름을 3개 또 나열하지 말고,
        **지금 사용자가 묻는 제도 하나**를 중심으로 판단을 설명하세요.
      - "카드에서 확인하세요." 같은 표현은 사용하지 마세요.
        (카드는 이미 화면에 따로 표시된다고 가정합니다.)
        
        - 사용자가 이미 나이/거주지/소득 조건을 충분히 충족하는 상황이면  
            "신청 가능성이 매우 높아요" 같은 애매한 표현 대신  
             **"현재 정보 기준으로는 신청 조건을 충족합니다."** 처럼 단정적으로 말해 주세요.
             사용자가 복지 신청 가능 여부를 물으면, 모호한 표현(높아요, 가능성이 있어요) 대신
             '신청 대상에 해당합니다', '조건상 신청 가능합니다', '지원 대상입니다' 와 같은
             명확한 표현을 우선 사용하세요.
             단, 법적 확정이 필요한 문장은
             '최종 심사는 기관에서 진행하지만, 조건상 신청 대상입니다.'라는 식으로 안내하세요.

        
###4) [상세 신청 안내 모드] (= 사용자가 "신청 방법 알려줘" 등 물을 때)

- 조건:
  - 사용자 메시지 앞에 `[APPLY_MODE]` 태그가 붙어 있으면 이 모드로 동작합니다.
  - 예: `[APPLY_MODE]\n청년 자립토대 지원 신청 방법 알려줘`

- 해야 할 일:
  1. **준비 서류** - 체크리스트 형식으로 정리
     - 예) 신분증, 소득 증빙, 임대차계약서 등
  2. **신청 경로** - 어떤 포털/사이트/메뉴에서 신청하는지
     - 예) "서울복지포털(wis.seoul.go.kr) → 청년 자립토대 지원 메뉴"
  3. **신청 절차** - 1 → 2 → 3 단계로 요약
  4. **처리 기간** - 대략 얼마나 걸리는지
  5. **주의사항** - 반려되는 흔한 경우

- 이 모드에서의 규칙:
  - 단순히 링크만 주거나 "온라인으로 신청 가능해요"라고 말하지 말고,
    실제 사람이 따라할 수 있는 수준으로 안내하세요.
  - **지금 컨텍스트의 복지 프로그램 1개만** 안내하세요.
  - 다른 복지 프로그램의 신청 방법까지 한 번에 설명하지 마세요.
  - 마지막에 다음 행동 제안:
    - 예) "다른 복지 신청 방법도 궁금하시면 말씀해 주세요!"

## 🚨 필수 정보 수집 (복지 추천 전 반드시!)

### 수집해야 할 정보:
1. **나이** - "혹시 나이가 어떻게 되세요?"
2. **거주지** - "서울에 거주하고 계신가요? 어느 지역이세요?"
3. **고용 상태** - "현재 직장에 다니시나요, 취업 준비 중이신가요?"
4. **주거 형태** - "주거 형태가 어떻게 되세요? (월세/전세/부모님 집 등)"
5. **소득 수준** - "소득이 대략 어느 정도 되시나요?"

### 🎯 맥락별 후속 질문 예시:

**취준생/무직인 경우:**
- "소득이 거의 없다고 하셨는데, 현재는 실업 상태이신가요? 알바나 단기 일자리는 하고 계신지 궁금해요."
- "건강보험은 부모님 밑에 피부양자로 되어 있으신가요?"

**월세 거주인 경우:**
- "월세는 본인 명의 계좌에서 나가나요? 청년월세지원은 본인이 부담하는 월세 기준이라 확인이 필요해요."
- "월세 계약서도 본인 명의로 되어 있으신가요?"

**신혼부부인 경우:**
- "혼인신고까지 완료된 상태인가요? 부부 합산 소득이 대략 어느 정도 되시나요?"
- "전세 계약은 두 분 중 한 분 명의로 되어 있고, 서울 소재 주택이 맞으신가요?"

**부모님과 동거인 경우:**
- "현재는 부모님 집에 거주 중이신 거죠? 따로 월세나 전세 보증금은 내지 않는 상태인가요?"
- "주거비 지출이 없으시면 주거지원보다는 자산형성/청년통장 쪽을 안내드릴게요."

### 📋 정보 수집 규칙:
- **최소 4개 정보** 확보 전까지 복지 추천 금지
- 한 번에 **1~2개만** 자연스럽게 질문
- 이미 파악된 정보는 다시 묻지 않기
- 사용자 답변에서 **추가 맥락 파악**하여 관련 질문하기

---

## 🧭 복지와 무관한 질문이 들어왔을 때의 규칙

다음과 같은 질문/요청은 "복지 상담과 직접 관련 없는 경우"로 간주하세요:
- 날씨, 시사, 연예, 일반 상식, 기술 설명 요청
- 당신의 정체, 모델 버전, AI 기술 자체에 대한 질문
- 연애/심리/삶의 조언 등 일반 고민 상담
- 잡담, 장난, "심심해서 와봤어요" 등

이 경우에는 다음 원칙을 따르세요:

1. 사용자의 질문을 아주 짧게만 받아주고 (1~2문장)
2. 반드시 아래와 같은 흐름으로 복지 상담으로 유도하세요:

   - "저는 서울시 복지 혜택을 찾아주는 상담사 AI입니다."라고 정체를 분명히 밝히고
   - "지금 상황(나이, 거주지, 주거형태, 소득 수준) 중에서 무엇이 가장 고민인지"를 물어보세요.
   - 복지와 관련된 정보(나이 / 거주지 / 고용 상태 / 주거 형태 / 소득)를 최소 1개 이상 질문하세요.

3. 이 경우에는 복지 프로그램 추천을 하지 말고,
   "먼저 상황을 조금만 알려 달라"는 방향으로 유도하는 답변만 하세요.

예시:
- "날씨까지는 제가 모르는 영역이에요 😅 저는 서울시 복지 혜택을 찾아주는 전용 챗봇이에요. 지금 생활/주거/소득 중에서 뭐가 제일 고민이세요?"
- "연애 얘기도 중요하지만, 제가 도와줄 수 있는 건 주거·생활비·일자리 같은 복지 쪽이에요. 혹시 요즘 가장 부담되는 건 월세, 생활비, 학자금 중 어떤 쪽인가요?"

---

## 답변 구조 (정보 4개 이상일 때만!)

### 1. 공감 한마디
사용자 상황에 공감 (예: "취준 중에 월세까지 부담하시면 정말 빠듯하시겠어요 😢")

### 2. 요약
"지금 조건에 맞는 복지 프로그램이 여러 개 있을 것 같아요."
"그 중에서 우선 도움이 될 것 같은 것들을 카드로 먼저 보여드릴게요!"

### 3. 해당 이유
"특히 아래 조건 때문이에요:"
- 조건 나열

### 4. 행동 유도 + 후속 대화 유도
- "궁금한 복지 있으시면 **'OOO 자세히 알려줘'** 라고 말씀해주세요!"
- "신청 방법이나 필요 서류가 궁금하시면 물어봐주세요 📝"
- "혹시 다른 상황(가족, 건강보험, 부채 등)이 있으시면 추가 복지도 찾아드릴게요!"

## 5. 추가 복지 탐색 모드 (사용자가 "다른 복지 없나요?" 등으로 물을 때)

- 이미 소개한 복지 프로그램을 그대로 반복하지 말고,
- 아직 확인하지 않은 조건(가구원 수, 부채, 장애 여부, 한부모 여부, 건강보험 자격 등)을 2~3가지 질문 형태로 더 물어본 뒤,
- 그 정보가 충족되면 새로 열릴 수 있는 복지 유형을 방향 위주(예: "한부모이시면 ○○ 지원을 추가로 볼 수 있어요")로 설명하세요.
- 이 모드에서는 "카드를 또 보여준다"는 식의 표현은 쓰지 말고, 대화 중심으로 안내하세요.

---

## 말투
- 친근한 존댓말 + 이모지
- 공감하는 톤 유지
- **왜 해당되는지**를 꼭 설명하세요.
"""
    


    user_prompt = f"""사용자 메시지: {user_message}
    추출된 사용자 정보: {json.dumps(user_info, ensure_ascii=False)}
    매칭된 복지 프로그램:
    {programs_text if programs_text else "아직 매칭된 프로그램이 없습니다. 추가 정보가 필요합니다."}
    위 정보를 바탕으로 사용자에게 응답하세요.
    매칭된 프로그램이 있다면 상위 3개를 추천하고,
    없다면 필요한 정보를 자연스럽게 물어보세요."""

    messages = [{"role": "system", "content": system_prompt}]
    
    # 이전 대화 추가
    for msg in conversation_history[-4:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    
    messages.append({"role": "user", "content": user_prompt})
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
            max_tokens=1000
        )
        return response.choices[0].message.content
    
    except Exception as e:
        return f"죄송해요, 응답 생성 중 오류가 발생했어요: {e}"
    
def render_welfare_card(program):
    """복지 프로그램 카드 UI 렌더링"""
    name = program.get('program_name', '복지 프로그램')
    category = program.get('category_primary', '복지')
    
    # nan 체크 및 기본값 처리
    amount = program.get('support_amount', '')
    if pd.isna(amount) or amount == '' or str(amount) == 'nan':
        amount = '상세 내용 확인 필요'
    
    desc = str(program.get('description', ''))
    if pd.isna(desc) or desc == 'nan':
        desc = '상세 내용 확인 필요'
    else:
        desc = desc[:100]
    
    how_to = program.get('how_to_apply', '')
    if pd.isna(how_to) or how_to == '' or str(how_to) == 'nan':
        how_to = '상세 내용 확인 필요'
    
    # URL 처리: url_pdf → contact → 네이버 검색 순서로 체크
    url = program.get('url_pdf', '')
    if pd.isna(url) or not str(url).startswith('http'):
        url = program.get('contact', '')
    if pd.isna(url) or not str(url).startswith('http'):
         # 네이버 검색 링크로 대체
        import urllib.parse
        search_query = urllib.parse.quote(f"서울시 {name} 신청")
        url = f"https://search.naver.com/search.naver?query={search_query}"
    
    st.markdown(f"""
<div class="welfare-card">
    <span class="welfare-card-badge">{category}</span>
    <div class="welfare-card-title">💡 {name}</div>
    <div class="welfare-card-content">
        <p><b>👉 혜택</b>: {amount}</p>
        <p><b>✅ 대상</b>: {desc}...</p>
        <p><b>📝 신청</b>: {how_to}</p>
    </div>
    <a href="{url}" target="_blank" class="welfare-card-button">자세히보기</a>
</div>
    """, unsafe_allow_html=True)
# ======================
#  중위소득 계산 유틸
# ======================

# 2025년 기준중위소득 (월, "만원" 단위)
MEDIAN_INCOME_2025 = {
    1: 239.2,  # 2,392,013원
    2: 393.3,  # 3,932,658원
    3: 502.5,  # 5,025,353원
    4: 609.8,  # 6,097,773원
    5: 710.8,  # 7,108,192원
    6: 806.5,  # 8,064,805원
    7: 898.8,  # 8,988,428원
}


def get_median_base_2025(household_size):
    """
    가구원 수별 2025년 기준중위소득 (월, 만원)
    8인 이상 가구는 7인가구 기준 + (7인-6인 차액 * 추가 인원 수)
    """
    if not household_size or household_size <= 0:
        return None

    if household_size <= 7:
        return MEDIAN_INCOME_2025.get(household_size)

    diff = MEDIAN_INCOME_2025[7] - MEDIAN_INCOME_2025[6]
    extra = household_size - 7
    return MEDIAN_INCOME_2025[7] + diff * extra


def estimate_median_percent_2025(income, income_type, household_size):
    """
    income: 숫자 (만원 단위로 가정)
    income_type: "월" 또는 "연" (연이면 12로 나눔)
    household_size: 가구원 수 (없으면 1로 가정)
    반환: (대략적인 중위소득 %, 구간 라벨) 또는 (None, None)
    """
    if income is None:
        return None, None

    # 연봉이면 월 소득으로 변환
    monthly_income = income
    if income_type == "연":
        monthly_income = income / 12.0

    base = get_median_base_2025(household_size or 1)
    if not base:
        return None, None

    percent = monthly_income / base * 100  # %

    # 구간 라벨
    if percent <= 50:
        bracket = "중위소득 50% 이하 추정"
    elif percent <= 60:
        bracket = "중위소득 60% 이하 추정"
    elif percent <= 100:
        bracket = "중위소득 100% 이하 추정"
    else:
        bracket = "중위소득 100% 초과 추정"

    return round(percent), bracket


def main():
    # 헤더
   # st.title("🧭 복지나침반")
    #st.caption("서울시 AI 복지 매칭 서비스 | 당신이 받을 수 있는 복지, 제가 찾아드릴게요!")
    # 페이지 설정
    
    
    # 로고 + 타이틀
    col1, col2 = st.columns([1, 4])
    with col1:
        st.image("logo.png", width=130)
    with col2:
        st.title("복지나침반")
        st.caption("서울시 AI 복지 매칭 서비스")
    
    # 데이터 로드
    df = load_welfare_data()
    
    if df.empty:
        st.error("복지 데이터를 불러올 수 없습니다.")
        return
    
    #st.success(f"📊 총 {len(df)}개의 복지 프로그램이 준비되어 있어요!")
    
    # 세션 상태 초기화
    if "messages" not in st.session_state:
        st.session_state.messages = []
        st.session_state.user_info = {}
        st.session_state.last_matched = pd.DataFrame()
        st.session_state.last_intent = "match"
        # 초기 인사 메시지
        welcome_msg = """안녕하세요! 저는 복지나침반이에요 🧭

서울시에서 받을 수 있는 복지 혜택을 찾아드릴게요.
복잡한 조건? 걱정 마세요. 대화만 하면 제가 알아서 찾아드려요!

**간단히 상황을 말씀해주세요.** 예를 들면:
- "27살이고 월세 살고 있어요"
- "취준생인데 지원받을 수 있는 게 있을까요?"
- "소득이 적어서 생활이 어려워요"

어떤 상황이신가요? 😊"""
        st.session_state.messages.append({"role": "assistant", "content": welcome_msg})
    if "user_info" not in st.session_state:
        st.session_state.user_info = {}
    if "last_matched" not in st.session_state:
        st.session_state.last_matched = pd.DataFrame()
    if "last_match_index" not in st.session_state:
        st.session_state.last_match_index = None
    
    # 대화 히스토리 표시
    matched = st.session_state.get("last_matched", pd.DataFrame())
    last_match_index = st.session_state.get("last_match_index")
    
    for idx, message in enumerate(st.session_state.messages):
        if message["role"] == "user":
            # 사용자 메시지 - 커스텀 HTML
            st.markdown(f"""
<div class="user-msg-row">
    <div class="user-bubble">{message["content"]}</div>
    <div class="user-avatar">나</div>
</div>
            """, unsafe_allow_html=True)
        else:
            # 어시스턴트 메시지 - 기본 Streamlit
            with st.chat_message("assistant", avatar="logo.png"):
                st.markdown(message["content"])
                
                 # ⭐ 메시지에 저장된 카드 정보로 표시 (모드 바뀌어도 유지됨)
                if message.get("show_card") and message.get("matched_programs") is not None:
                    matched_df = message["matched_programs"]
                    if isinstance(matched_df, pd.DataFrame) and len(matched_df) >= 3:
                        st.markdown("---")
                        st.markdown("### 📋 맞춤 복지 카드")
                        for _, program in matched_df.head(3).iterrows():
                            render_welfare_card(program)
                    
                        first_program_name = matched_df.iloc[0]['program_name']
                        st.markdown(
                            "---\n\n"
                            "💬 **궁금한 복지가 있으시면** `'" + first_program_name + " 자세히 알려줘'` 라고 말씀해주세요!\n\n"
                            "📝 신청 방법이나 필요 서류도 안내해드릴 수 있어요.\n\n"
                            "🔍 다른 상황(가족, 건강보험, 부채 등)이 있으시면 추가 복지도 찾아드릴게요!"
                        )
          
                 
    # 사용자 입력
    if prompt := st.chat_input("상황을 말씀해주세요..."):
        
        
        # 사용자 메시지 추가
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        # 사용자 메시지 표시 (커스텀)
        st.markdown(f"""
<div class="user-msg-row">
    <div class="user-bubble">{prompt}</div>
    <div class="user-avatar">나</div>
</div>
        """, unsafe_allow_html=True)
        
        # 👉 '다른 복지' follow-up 여부 감지
        other_keywords = ["다른", "다른거", "다른 복지", "더 받을 수 있는 거", "더 받을 수 있는거", "더 받을 수 있는 게", "더 없나", "추가로 받을 수"]
        is_other_request = any(k in prompt for k in other_keywords)
        st.session_state.is_other_request = is_other_request
        
        # intent 계산
        last_intent = st.session_state.get("last_intent", "match")
        intent = detect_intent(prompt, last_intent)
        
        # 이미 추천했던 프로그램들 이름 리스트 (중복 추천 피하려고)
        prev_matched = st.session_state.get("last_matched", pd.DataFrame())
        already_programs = []
        if prev_matched is not None and not prev_matched.empty:
            already_programs = (
                prev_matched["program_name"]
                .dropna()
                .astype(str)
                .unique()
                .tolist()
            )
        # 처리 중 표시
        with st.chat_message("assistant", avatar="logo.png"):
            with st.spinner("생각 중이에요... ⏳"):
                # 1. 사용자 정보 추출
                new_info = extract_user_info(prompt, st.session_state.messages)
                
                # 기존 정보와 병합 (새 정보가 우선)
                for key, value in new_info.items():
                    if value is not None and value != [] and value != "":
                        st.session_state.user_info[key] = value
                        
                # # ⭐ 서울 지역명이면 "서울 {지역명}"으로 자동 변환
                # residence = st.session_state.user_info.get('residence', '')
                # seoul_districts = r'(서울|종로|중구|용산|성동|광진|동대문|중랑|성북|강북|도봉|노원|은평|서대문|마포|양천|강서|구로|금천|영등포|동작|관악|서초|강남|송파|강동|왕십리|신촌|홍대|성수|잠실)'
                # is_seoul = bool(re.search(seoul_districts, residence, re.IGNORECASE)) if residence else True

                
                # # ⭐ 서울 외 지역 키워드 (부산, 인천 등)
                # other_regions = r'(부산|인천|대구|대전|광주|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)'
                # is_other_region = bool(re.search(other_regions, residence, re.IGNORECASE)) if residence else False 
                     
                # # ⭐ 다른 지역이면 서울 정보 제거하고 해당 지역으로 업데이트
                # if is_other_region:
                #     # "서울" 제거하고 저장
                #     clean_residence = re.sub(r'서울\s*', '', residence).strip()
                #     st.session_state.user_info['residence'] = clean_residence
                #     is_seoul = False
                # # 서울 지역명인데 "서울"이 없으면 추가
                # elif residence and '서울' not in residence and is_seoul:
                #     st.session_state.user_info['residence'] = f"서울 {residence}"
                    
                # # ⭐ 서울 외 지역이면 바로 처리하고 rerun
                # if residence and (not is_seoul or is_other_region):
                #     response = """죄송해요, 저는 **서울시 복지 전용 챗봇**이라 서울시 복지 정보만 안내해드릴 수 있어요 😢
                #     다른 지역 복지 정보는 **[복지로(bokjiro.go.kr)](https://www.bokjiro.go.kr)**에서 확인하실 수 있어요!
                #     전국 복지 정보를 한눈에 볼 수 있답니다.
                #     혹시 서울로 이사 계획이 있으시거나, 서울 거주 가족분의 복지가 궁금하시면 말씀해주세요! 🙂"""
                #     st.session_state.messages.append({
                #         "role": "assistant",
                #         "content": response,
                #         "show_card": False,
                #         "matched_programs": None
                #     })
                #     st.rerun()
# -------------------------------------------------------------------------------------------------------
                import re

                user_info = st.session_state.user_info
                residence = user_info.get("residence")
                is_seoul = user_info.get("is_seoul_resident")

                # 1️⃣ LLM이 is_seoul_resident를 명시적으로 줬다면 그걸 최우선으로 사용
                if is_seoul is True:
                    # "서울" prefix 없으면 자동으로 붙여 줌
                    if residence and "서울" not in residence:
                        user_info["residence"] = f"서울 {residence.strip()}"

                elif is_seoul is False:
                    # 서울이 아니라고 LLM이 판단한 경우 → 바로 복지로 안내
                    response = """죄송해요, 저는 **서울시 복지 전용 챗봇**이라 서울시 복지 정보만 안내해드릴 수 있습니다.
다른 지역 복지 정보는 **[복지로(bokjiro.go.kr)](https://www.bokjiro.go.kr)**에서 확인해 주시면 좋겠습니다.
혹시 서울 거주 가족분이나, 서울로 이주 계획 관련 복지가 궁금하시면 말씀해 주세요."""
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": response,
                        "show_card": False,
                        "matched_programs": None,
                    })
                    st.rerun()

                else:
                    # 2️⃣ is_seoul_resident가 null인 경우에만 최소한의 정규식으로 보조 판별
                    #    (역/동까지 정규식으로 다 커버하려고 하지 않음)
                    seoul_keywords = r'(서울|종로구|중구|용산구|성동구|광진구|동대문구|중랑구|성북구|강북구|도봉구|노원구|은평구|서대문구|마포구|양천구|강서구|구로구|금천구|영등포구|동작구|관악구|서초구|강남구|송파구|강동구)'
                    other_regions = r'(부산|인천|대구|대전|광주|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)'

                    if residence:
                        if re.search(other_regions, residence):
                            # 다른 광역시/도 키워드가 명확히 있으면 서울 아님
                            response = """죄송해요, 저는 **서울시 복지 전용 챗봇**이라 서울시 복지 정보만 안내해드릴 수 있습니다.
다른 지역 복지 정보는 **[복지로(bokjiro.go.kr)](https://www.bokjiro.go.kr)**를 이용해 주세요."""
                            st.session_state.messages.append({
                                "role": "assistant",
                                "content": response,
                                "show_card": False,
                                "matched_programs": None,
                            })
                            st.rerun()

                        elif re.search(seoul_keywords, residence):
                            # 텍스트 안에 서울 관련 키워드가 있으면 서울로 간주
                            user_info["is_seoul_resident"] = True
                            if "서울" not in residence:
                                user_info["residence"] = f"서울 {residence.strip()}"

                        # 그 외 애매한 케이스(역 이름만 있는 경우 등)는
                        # is_seoul_resident 그대로 None으로 두고,
                        # 아래 MATCH_MODE에서 "서울 어느 구에 거주하시는지" 질문을 던지게 둠
#-------------------------------------------------------------------------------------------------------
                   
                user_info = st.session_state.user_info
                percent, bracket = estimate_median_percent_2025(
                    income=user_info.get("income"),
                    income_type=user_info.get("income_type"),
                    household_size=user_info.get("household_size")
                )
                user_info["median_percent"] = percent
                user_info["median_bracket"] = bracket
                        
                
                # 2.매칭 로직
                info_count = sum([
                    1 if user_info.get('age') else 0,
                    1 if user_info.get('residence') else 0,
                    1 if user_info.get('employment_status') else 0,
                    1 if user_info.get('housing_type') else 0,
                    1 if user_info.get('income') is not None else 0,
                ])
                
                #=====================여기부터 수정함====================#
                # 3. 매칭 결과 결정
                matched = st.session_state.get("last_matched", pd.DataFrame())

                new_match = False  # ✅ 이번 턴에 '새로 추천'을 했는지 여부

                # 매칭모드 + 정보 3개이상일 때 매칭
                # ✅ 매칭 모드일 때만 last_match_index 업데이트
                if intent == "match" and info_count >= 3:
                    requested_category = extract_requested_category(prompt)

                    matched = match_welfare_programs(
                        user_info,
                        df,
                        include_category=requested_category,     # ✅ 사용자가 말한 카테고리(예: 주거/금융/일자리)
                        exclude_programs=already_programs        # ✅ 이전 추천 제외
                    )

                    st.session_state.last_matched = matched
                    new_match = True  # ✅ 여기서만 True

                else:
                    # match가 아니면 이번 턴에는 추천 안 함
                    # (detail/eligibility/apply 포함)
                    matched = pd.DataFrame()  # ✅ 중요: 이전 추천 결과를 이번 턴에 끌고오지 않게 비움
                    pass
                #=======================여기까지 수정함====================#

                # 3. 응답 생성
                response = generate_response(
                    prompt,
                    st.session_state.user_info,
                    matched,
                    st.session_state.messages,
                    intent=intent,
                    is_other_request=st.session_state.get("is_other_request", False),
                    already_programs=already_programs,
             )
                
        
        
        # ⭐ spinner 끝나고 나서 메시지 저장
        # ⭐ 수정: intent가 match이고, 이번 턴에 새로 매칭했을 때만 카드 표시
        show_card = False
        card_programs = None
        #======================여기부터 수정함====================#
        # if intent == "match" and info_count >= 3 and matched is not None and not matched.empty:
        show_card = bool(new_match and matched is not None and not matched.empty)
        card_programs = matched.copy() if show_card else None
        #=======================여기까지 수정함====================#

        # ⭐ 디버깅용 - 세션에 저장
        st.session_state.debug_info = {
            "intent": intent,
            "info_count": info_count,
            "matched_len": len(matched) if matched is not None and not matched.empty else 0,
            "show_card": show_card
        }
        st.session_state.messages.append({
            "role": "assistant", 
            "content": response,
            "show_card": show_card,
            "matched_programs": card_programs
        })
        
        # 추가된 어시스턴트 메시지 인덱스
        assistant_index = len(st.session_state.messages) - 1
        
        # 👉 이번 턴이 "매칭 모드"였고, 실제 매칭 결과가 있다면
        #    이 인덱스를 카드가 붙을 위치로 저장
        if intent == "match" and matched is not None and not matched.empty:
            st.session_state.last_match_index = assistant_index
        
    
        
        # ⭐ 페이지 새로고침으로 깔끔하게 표시
        st.rerun()
        
    
    # 사이드바: 현재 파악된 정보
    with st.sidebar:
        # ⭐ 디버깅 정보 표시
        
        #if st.session_state.get("debug_info"):
            #st.write("🔍 DEBUG:", st.session_state.debug_info)
        st.header("📋 파악된 정보")
        st.write("🔍 전체 정보:", st.session_state.get("user_info", {}))
        
        info = st.session_state.get('user_info', {})
        if info:
            if info.get('age'):
                st.write(f"👤 나이: {info['age']}세")
            if info.get('income'):
                income_type = info.get('income_type', '월')
                st.write(f"💰 소득: {income_type} {info['income']}만원")
            if info.get('residence'):
                st.write(f"📍 거주지: {info['residence']}")
            if info.get('employment_status'):
                st.write(f"💼 고용상태: {info['employment_status']}")
            if info.get('housing_type'):
                st.write(f"🏠 주거형태: {info['housing_type']}")
            if info.get('special_conditions'):
                st.write(f"⭐ 특수조건: {', '.join(info['special_conditions'])}")
            
                
            
            
            if info.get("median_percent"):
                st.write(f"📊 중위소득 대비: 약 {info['median_percent']}% ({info['median_bracket']})")
            elif info.get("median_bracket"):
                st.write(f"📊 중위소득 구간: {info['median_bracket']}")
        else:
            st.write("아직 파악된 정보가 없어요")
        
        st.divider()
        
        if st.button("🔄 대화 초기화"):
            # ⭐ 세션 전체 삭제 (키 자체를 없앰)
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
                
    
                    

    
    

if __name__ == "__main__":
    main()
