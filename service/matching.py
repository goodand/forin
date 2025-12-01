import pandas as pd
import re


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
        "자격"            # ← 추가
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


def match_welfare_programs(user_info: dict, df: pd.DataFrame) -> pd.DataFrame:
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
                
        return True
    
    matched = matched[matched['special_conditions'].apply(check_special_conditions)]
    
    
    # 거주지 필터링
    if user_info.get('residence'):
        residence = user_info.get('residence', '')
        # ⭐ 서울 여부 판단 (정규식)
        seoul_keywords = r'(서울|종로|중구|용산|성동|광진|동대문|중랑|성북|강북|도봉|노원|은평|서대문|마포|양천|강서|구로|금천|영등포|동작|관악|서초|강남|송파|강동|왕십리|신촌|홍대|성수|잠실)'
        is_seoul = bool(re.search(seoul_keywords, residence, re.IGNORECASE))
        

        if residence and not is_seoul:
            # 서울 아니면 서울 전용 복지 제외
            matched = matched[
                matched['residence_required'].isna() | 
                ~matched['residence_required'].str.contains('서울', na=False)
        ]
            
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
    
    if 'difficulty_level' in matched.columns:
        matched = matched.sort_values(['priority', 'difficulty_level'], ascending=[False, True])
    else:
        matched = matched.sort_values('priority', ascending=False)
    
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