#!/usr/bin/env python3
"""
Test the selenium_required value normalization logic
"""
import pandas as pd

def normalize_selenium_value(val):
    """Test function matching the fixed logic"""
    if pd.isna(val) or val == '' or val == 'nan':
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None

def test_normalization():
    """Test cases for the normalization logic"""
    test_cases = [
        ('', None, "빈 문자열"),
        (None, None, "None 값"),
        (pd.NA, None, "pandas NA"),
        ('nan', None, "문자열 nan"),
        (0, 0, "정수 0"),
        (1, 1, "정수 1"),
        (-1, -1, "정수 -1"),
        ('0', 0, "문자열 0"),
        ('1', 1, "문자열 1"),
        ('-1', -1, "문자열 -1"),
        ('0.0', 0, "float 문자열 0.0"),
        ('1.0', 1, "float 문자열 1.0"),
        ('invalid', None, "유효하지 않은 문자열"),
        (2.5, 2, "float 2.5"),
    ]

    print("=== selenium_required 값 정규화 테스트 ===\n")

    all_passed = True
    for input_val, expected, description in test_cases:
        result = normalize_selenium_value(input_val)
        passed = result == expected
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} {description}: {input_val} -> {result} (예상: {expected})")
        if not passed:
            all_passed = False

    print(f"\n{'=' * 50}")
    if all_passed:
        print("✅ 모든 테스트 통과!")
    else:
        print("❌ 일부 테스트 실패")

    # 변경사항 감지 로직 테스트
    print(f"\n=== 변경사항 감지 테스트 ===")
    change_test_cases = [
        ('', 0, True, "빈 문자열 -> 0"),
        ('', 1, True, "빈 문자열 -> 1"),
        ('', -1, True, "빈 문자열 -> -1"),
        (None, 1, True, "None -> 1"),
        (0, 0, False, "0 -> 0 (변경 없음)"),
        (1, 1, False, "1 -> 1 (변경 없음)"),
        (-1, -1, False, "-1 -> -1 (변경 없음)"),
        ('0', 1, True, "문자열 0 -> 1"),
        ('1', 0, True, "문자열 1 -> 0"),
    ]

    for old_val, new_val, expected_change, description in change_test_cases:
        old_normalized = normalize_selenium_value(old_val)
        new_normalized = normalize_selenium_value(new_val)

        # 변경사항 감지 로직
        change_detected = (old_normalized is None and new_normalized in [0, 1, -1]) or (old_normalized != new_normalized)

        passed = change_detected == expected_change
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} {description}: {old_val}({old_normalized}) -> {new_val}({new_normalized}) = {change_detected}")

if __name__ == "__main__":
    test_normalization()