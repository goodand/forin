import streamlit as st
import pandas as pd
import re

from service.data_loader import load_welfare_data
from service.llm import extract_user_info, generate_response
from service.matching import (
    detect_intent,
    match_welfare_programs,
    estimate_median_percent_2025,
)
from ui.style import apply_global_style, render_header
from ui.cards import render_welfare_card


def main():
    # 페이지 설정
    st.set_page_config(
        page_title="복지나침반 🧭",
        page_icon="🧭",
        layout="centered"
    )
    
    # CSS 적용 + 상단 헤더
    apply_global_style()
    render_header()
    
    # 데이터 로드
    df = load_welfare_data()
    
    if df.empty:
        st.error("복지 데이터를 불러올 수 없습니다.")
        return
    
    # 세션 상태 초기화
    if "messages" not in st.session_state:
        st.session_state.messages = []
        st.session_state.user_info = {}
        st.session_state.last_matched = pd.DataFrame()
        st.session_state.last_intent = "match"
        # 초기 인사 메시지
        welcome_msg = """
            안녕하세요! 저는 복지나침반이에요 🧭

            서울시에서 받을 수 있는 복지 혜택을 찾아드릴게요.
            복잡한 조건? 걱정 마세요. 대화만 하면 제가 알아서 찾아드려요!

            **간단히 상황을 말씀해주세요.** 예를 들면:
            - "27살이고 월세 살고 있어요"
            - "취준생인데 지원받을 수 있는 게 있을까요?"
            - "소득이 적어서 생활이 어려워요"

            어떤 상황이신가요? 😊
            """
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
                        
                # ⭐ 서울 지역명이면 "서울 {지역명}"으로 자동 변환
                residence = st.session_state.user_info.get('residence', '')
                seoul_districts = r'(서울|종로|중구|용산|성동|광진|동대문|중랑|성북|강북|도봉|노원|은평|서대문|마포|양천|강서|구로|금천|영등포|동작|관악|서초|강남|송파|강동|왕십리|신촌|홍대|성수|잠실)'
                is_seoul = bool(re.search(seoul_districts, residence, re.IGNORECASE)) if residence else True

                
                # ⭐ 서울 외 지역 키워드 (부산, 인천 등)
                other_regions = r'(부산|인천|대구|대전|광주|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)'
                is_other_region = bool(re.search(other_regions, residence, re.IGNORECASE)) if residence else False 
                     
                # ⭐ 다른 지역이면 서울 정보 제거하고 해당 지역으로 업데이트
                if is_other_region:
                    # "서울" 제거하고 저장
                    clean_residence = re.sub(r'서울\s*', '', residence).strip()
                    st.session_state.user_info['residence'] = clean_residence
                    is_seoul = False
                # 서울 지역명인데 "서울"이 없으면 추가
                elif residence and '서울' not in residence and is_seoul:
                    st.session_state.user_info['residence'] = f"서울 {residence}"
                    
                # ⭐ 서울 외 지역이면 바로 처리하고 rerun
                if residence and (not is_seoul or is_other_region):
                    response = """죄송해요, 저는 **서울시 복지 전용 챗봇**이라 서울시 복지 정보만 안내해드릴 수 있어요 😢
                    다른 지역 복지 정보는 **[복지로(bokjiro.go.kr)](https://www.bokjiro.go.kr)**에서 확인하실 수 있어요!
                    전국 복지 정보를 한눈에 볼 수 있답니다.
                    혹시 서울로 이사 계획이 있으시거나, 서울 거주 가족분의 복지가 궁금하시면 말씀해주세요! 🙂"""
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": response,
                        "show_card": False,
                        "matched_programs": None
                    })
                    st.rerun()
                   


                user_info = st.session_state.user_info
                percent, bracket = estimate_median_percent_2025(
                    income=user_info.get("income"),
                    income_type=user_info.get("income_type"),
                    household_size=user_info.get("household_size")
                )
                user_info["median_percent"] = percent
                user_info["median_bracket"] = bracket
                # 여기 라인부터 수정

                # 🔍 신혼부부인데 소득이 있는데, 이게 개인인지 부부합산인지 불명확한 경우
                special = user_info.get("special_conditions", []) or []
                is_newlywed = any("신혼" in s for s in special)

                income = user_info.get("income")
                income_scope = user_info.get("income_scope")  # extract_user_info에서 채움

                # "부부 합산", "둘이 합쳐" 같은 표현이 들어 있었으면 scope를 강제로 부부합산으로 설정
                # (혹시 LLM이 못 잡았을 경우 대비)
                raw_text = prompt  # 이번 턴 사용자 입력만 간단히 사용
                if income_scope is None:
                    if any(kw in raw_text for kw in ["부부 합산", "둘이 합쳐", "두 명 합쳐", "둘 다 합쳐"]):
                        user_info["income_scope"] = "부부합산"
                        income_scope = "부부합산"

                must_ask_couple_income = False
                if is_newlywed and income is not None and not income_scope:
                    must_ask_couple_income = True
                    
                # 여기라인까지 수정함
                        
                
                # 2.매칭 로직
                info_count = sum([
                    1 if user_info.get('age') else 0,
                    1 if user_info.get('residence') else 0,
                    1 if user_info.get('employment_status') else 0,
                    1 if user_info.get('housing_type') else 0,
                    1 if user_info.get('income') is not None else 0,
                ])
                
                # 3. 매칭 결과 결정
                matched = st.session_state.get("last_matched", pd.DataFrame())

                # 매칭모드 + 정보 3개이상일 때 매칭
                # ✅ 매칭 모드일 때만 last_match_index 업데이트
                if intent == "match" and info_count >= 3:
                    matched = match_welfare_programs(user_info, df)
                    st.session_state.last_matched = matched
                    st.session_state.last_match_index = len(st.session_state.messages)

                # ✅ apply / detail 모드에서는 last_match_index 건드리지 않기
                elif intent in ("detail", "eligibility"):
                    # 매칭은 다시 안 돌리고, last_match_index도 그대로 둔다
                    pass

                # 3. 응답 생성
                response = generate_response(
                    prompt,
                    st.session_state.user_info,
                    matched,
                    st.session_state.messages,
                    intent=intent,
                    is_other_request=st.session_state.get("is_other_request", False),
                    already_programs=already_programs,
                    must_ask_couple_income=must_ask_couple_income,  # ← 추가
             )

                
        
        
        # ⭐ spinner 끝나고 나서 메시지 저장
        # ⭐ 수정: intent가 match이고, 이번 턴에 새로 매칭했을 때만 카드 표시
        show_card = False
        card_programs = None
        if intent == "match" and info_count >= 3 and matched is not None and not matched.empty:
            show_card = True
            card_programs = matched.copy()
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