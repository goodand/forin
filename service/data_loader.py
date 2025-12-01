from pathlib import Path

import pandas as pd
import streamlit as st

@st.cache_data
def load_welfare_data():
    """통합된 welfare CSV 파일 로드 (여러 경로 시도)"""
    base_dir = Path(__file__).resolve().parent.parent
    candidates = [
        base_dir / "welfare_data.csv",
        base_dir / "data" / "welfare_data.csv",
        base_dir / "data" / "welfare_save.csv",  # 구버전 호환
    ]

    last_error = None
    for csv_path in candidates:
        if not csv_path.exists():
            continue
        try:
            df = pd.read_csv(csv_path, encoding='utf-8')

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
            last_error = e

    error_msg = "복지 데이터 파일을 찾을 수 없습니다."
    if last_error:
        error_msg += f" (마지막 오류: {last_error})"
    st.error(error_msg)

    return pd.DataFrame()
