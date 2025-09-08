#!/usr/bin/env python3
"""
채점 시스템 테스트 데이터 생성 스크립트

examId: 2beeab06-8adb-11f0-80d3-0242c0a81002
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

# 프로젝트 경로 추가
sys.path.append(str(Path(__file__).parent.parent))

from app.models.grading import (
    QuestionData,
    QuestionType,
    StudentAnswerSheet,
    StudentAnswerSheetQuestion,
)
from app.repositories.memory_implementation import (
    InMemoryExamRepository,
    InMemoryQuestionRepository,
)


async def create_test_data():
    """테스트 데이터 생성 및 저장"""
    
    # Repository 인스턴스 생성
    exam_repo = InMemoryExamRepository()
    question_repo = InMemoryQuestionRepository()
    
    # 고정된 ID들
    exam_id = UUID("2beeab06-8adb-11f0-80d3-0242c0a81002")
    submission_id = uuid4()  # 새로운 submission ID 생성
    exam_sheet_id = uuid4()  # 시험지 ID
    student_answer_sheet_id = uuid4()  # 답안지 ID
    
    print(f"📝 테스트 데이터 생성 시작")
    print(f"exam_id: {exam_id}")
    print(f"submission_id: {submission_id}")
    print(f"exam_sheet_id: {exam_sheet_id}")
    print(f"student_answer_sheet_id: {student_answer_sheet_id}")
    
    # 1. 시험 제출 정보 생성
    submission = {
        "id": submission_id,
        "exam_id": exam_id,
        "student_id": 123456,  # bigint
        "submitted_at": datetime.now(),
    }
    exam_repo.storage.submissions[submission_id] = submission
    
    # 2. 시험지 매핑
    exam_repo.storage.submission_to_exam_sheet[submission_id] = exam_sheet_id
    
    # 3. 문제 데이터 생성
    questions = [
        QuestionData(
            question_id=uuid4(),
            question_type=QuestionType.MULTIPLE_CHOICE,
            question_text="Python에서 리스트 컴프리헨션의 올바른 문법은?",
            points=5,
            choices={
                "1": "[x for x in range(10)]",
                "2": "{x for x in range(10)}",
                "3": "(x for x in range(10))",
                "4": "x for x in range(10)"
            },
            correct_choice=1,
            difficulty="중",
        ),
        QuestionData(
            question_id=uuid4(),
            question_type=QuestionType.MULTIPLE_CHOICE,
            question_text="다음 중 REST API의 특징이 아닌 것은?",
            points=5,
            choices={
                "1": "Stateless",
                "2": "Client-Server 구조",
                "3": "Session 기반 인증 필수",
                "4": "Uniform Interface"
            },
            correct_choice=3,
            difficulty="하",
        ),
        QuestionData(
            question_id=uuid4(),
            question_type=QuestionType.SUBJECTIVE,
            question_text="데이터베이스 정규화의 목적과 1NF, 2NF, 3NF를 간단히 설명하시오.",
            points=10,
            answer_text="정규화 목적: 데이터 중복 제거, 이상 현상 방지\n1NF: 원자값\n2NF: 부분 함수 종속 제거\n3NF: 이행 함수 종속 제거",
            difficulty="상",
            scoring_rubric="각 정규형 설명당 2-3점",
        ),
        QuestionData(
            question_id=uuid4(),
            question_type=QuestionType.MULTIPLE_CHOICE,
            question_text="HTTP 상태 코드 404의 의미는?",
            points=5,
            choices={
                "1": "OK",
                "2": "Created",
                "3": "Not Found",
                "4": "Internal Server Error"
            },
            correct_choice=3,
            difficulty="하",
        ),
        QuestionData(
            question_id=uuid4(),
            question_type=QuestionType.SUBJECTIVE,
            question_text="마이크로서비스 아키텍처의 장단점을 각각 2가지씩 설명하시오.",
            points=10,
            answer_text="장점: 1. 독립적 배포 가능 2. 기술 스택 다양성\n단점: 1. 네트워크 복잡도 증가 2. 분산 트랜잭션 관리 어려움",
            difficulty="상",
            scoring_rubric="각 항목당 2.5점",
        ),
    ]
    
    # 문제 저장
    for question in questions:
        question_repo.storage.questions[question.question_id] = question
    
    # 시험지-문제 매핑
    question_repo.storage.exam_sheet_questions[exam_sheet_id] = [
        q.question_id for q in questions
    ]
    
    # 4. 학생 답안 생성
    answer_sheet = StudentAnswerSheet(
        id=student_answer_sheet_id,
        submission_id=submission_id,
        student_name="테스트학생"
    )
    exam_repo.storage.student_answer_sheets[answer_sheet.id] = answer_sheet
    
    # 답안 상세 생성
    student_answers = [
        StudentAnswerSheetQuestion(
            id=uuid4(),
            question_id=questions[0].question_id,
            student_answer_sheet_id=student_answer_sheet_id,
            selected_choice=1,  # 정답
        ),
        StudentAnswerSheetQuestion(
            id=uuid4(),
            question_id=questions[1].question_id,
            student_answer_sheet_id=student_answer_sheet_id,
            selected_choice=2,  # 오답 (정답은 3)
        ),
        StudentAnswerSheetQuestion(
            id=uuid4(),
            question_id=questions[2].question_id,
            student_answer_sheet_id=student_answer_sheet_id,
            answer_text="정규화는 데이터 중복을 줄이는 것입니다. 1NF는 원자값을 가져야 하고, 2NF는 완전 함수 종속입니다.",
        ),
        StudentAnswerSheetQuestion(
            id=uuid4(),
            question_id=questions[3].question_id,
            student_answer_sheet_id=student_answer_sheet_id,
            selected_choice=3,  # 정답
        ),
        StudentAnswerSheetQuestion(
            id=uuid4(),
            question_id=questions[4].question_id,
            student_answer_sheet_id=student_answer_sheet_id,
            answer_text="장점: 서비스별 독립 배포, 장애 격리\n단점: 네트워크 지연, 데이터 일관성 문제",
        ),
    ]
    
    # 답안 저장
    for answer in student_answers:
        exam_repo.storage.student_answers[answer.id] = answer
    
    print("\n✅ 테스트 데이터 생성 완료!")
    print(f"📋 문제 수: {len(questions)}개")
    print(f"   - 객관식: 3개")
    print(f"   - 주관식: 2개")
    print(f"📝 답안 수: {len(student_answers)}개")
    
    return {
        "submission_id": str(submission_id),
        "exam_id": str(exam_id),
        "exam_sheet_id": str(exam_sheet_id),
        "question_count": len(questions),
        "answer_count": len(student_answers),
        "student_name": "테스트학생",
        "student_id": 123456,
    }


if __name__ == "__main__":
    result = asyncio.run(create_test_data())
    
    print("\n🎯 채점 API 테스트를 위한 정보:")
    print(f"submission_id: {result['submission_id']}")
    print("\n📌 curl 명령어 예시:")
    print(f"""
curl -X POST "http://localhost:8000/grading/{result['submission_id']}" \\
  -H "Content-Type: application/json" \\
  -d '{{"force_regrade": false}}'
    """)