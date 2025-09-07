#!/usr/bin/env python3
"""
채점 로직 테스트 - 답안 개수 불일치 케이스
"""

import asyncio
import json
from uuid import UUID

# 테스트 데이터
test_data = {
    "exam_id": "2beeab06-8adb-11f0-80d3-0242c0a81002",
    "student_id": 17,  # 실제 존재하는 학생 ID
    "answers": [
        # 15문제 중 3문제만 답안 제출
        {
            "question_id": "cf6c42bc-8ada-11f0-80d3-0242c0a81002",
            "answer_text": "이쑤시개"
        },
        {
            "question_id": "cf6c40f3-8ada-11f0-80d3-0242c0a81002", 
            "answer_text": "교정"
        },
        {
            "question_id": "cf6b3552-8ada-11f0-80d3-0242c0a81002",
            "answer_text": "토론"
        }
    ]
}

async def test_partial_answers():
    """부분 답안 제출 테스트"""
    import httpx
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        print("=" * 60)
        print("채점 로직 테스트: 15문제 중 3문제만 답안 제출")
        print("=" * 60)
        
        # API 호출
        response = await client.post(
            "http://localhost:8004/grading/submit-and-grade",
            json=test_data
        )
        
        if response.status_code == 200:
            result = response.json()
            grading_result = result.get("grading_result", {})
            
            print(f"\n✅ 테스트 성공!")
            print(f"제출 ID: {result['submission_id']}")
            print(f"총점: {grading_result['total_score']}/{grading_result['max_total_score']}")
            
            # 문제별 결과 분석
            question_results = grading_result.get("question_results", [])
            print(f"\n채점된 문제 수: {len(question_results)}")
            
            answered = 0
            unanswered = 0
            
            for qr in question_results:
                if "미제출" in qr.get("scoring_comment", ""):
                    unanswered += 1
                else:
                    answered += 1
                    
            print(f"- 답안 제출: {answered}개")
            print(f"- 답안 미제출: {unanswered}개")
            
            # 메타데이터 확인
            metadata = grading_result.get("metadata", {})
            print(f"\n메타데이터:")
            print(f"- 전체 문제 수: {metadata.get('total_questions')}")
            print(f"- 객관식: {metadata.get('multiple_choice_count')}")
            print(f"- 주관식: {metadata.get('subjective_count')}")
            
            # 점수 계산 검증
            expected_unanswered = metadata.get('total_questions', 0) - len(test_data['answers'])
            print(f"\n검증:")
            print(f"- 예상 미답변 문제 수: {expected_unanswered}")
            print(f"- 실제 미답변 처리 수: {unanswered}")
            
            if unanswered == expected_unanswered:
                print("✅ 미답변 문제가 올바르게 처리됨!")
            else:
                print("❌ 미답변 문제 처리에 문제 있음!")
                
        else:
            print(f"❌ 테스트 실패: {response.status_code}")
            print(response.text)

if __name__ == "__main__":
    asyncio.run(test_partial_answers())