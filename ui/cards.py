import streamlit as st
import pandas as pd
import urllib.parse


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