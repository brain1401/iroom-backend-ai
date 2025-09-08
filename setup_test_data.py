"""테스트 데이터 설정"""
from uuid import UUID
from app.repositories.memory_implementation import InMemoryStorage
from app.models.grading import QuestionData, QuestionType, Difficulty

# 저장소 초기화
storage = InMemoryStorage()
storage.clear_all()

# 시험 ID와 시험지 ID
exam_id = UUID("2beeab06-8adb-11f0-80d3-0242c0a81002")
exam_sheet_id = UUID("f3f1bca5-8ada-11f0-80d3-0242c0a81002")

# exam -> exam_sheet 매핑
storage.exam_to_exam_sheet[exam_id] = exam_sheet_id

# 문제 데이터 추가
questions = [
    QuestionData(
        question_id=UUID("cf6c42bc-8ada-11f0-80d3-0242c0a81002"),
        question_text="고기 먹을 때마다 따라오는 개는?",
        question_type=QuestionType.SUBJECTIVE,
        difficulty=Difficulty.MEDIUM,
        points=5,
        answer_text="이쑤시개"
    ),
    QuestionData(
        question_id=UUID("cf6c40f3-8ada-11f0-80d3-0242c0a81002"),
        question_text="다리가 기울어져 있으면?",
        question_type=QuestionType.SUBJECTIVE,
        difficulty=Difficulty.MEDIUM,
        points=5,
        answer_text="경사로"
    ),
    QuestionData(
        question_id=UUID("cf6c46eb-8ada-11f0-80d3-0242c0a81002"),
        question_text="달에서 돌고 있으면?",
        question_type=QuestionType.SUBJECTIVE,
        difficulty=Difficulty.MEDIUM,
        points=5,
        answer_text="월석"
    ),
    QuestionData(
        question_id=UUID("cf6c47b5-8ada-11f0-80d3-0242c0a81002"),
        question_text="돼지가 헷갈리면?",
        question_type=QuestionType.SUBJECTIVE,
        difficulty=Difficulty.MEDIUM,
        points=5,
        answer_text="피그말리온"
    ),
    QuestionData(
        question_id=UUID("cf6b3552-8ada-11f0-80d3-0242c0a81002"),
        question_text="땅에서 대화를 하면?",
        question_type=QuestionType.SUBJECTIVE,
        difficulty=Difficulty.MEDIUM,
        points=5,
        answer_text="그라운드톡"
    )
]

# 문제 저장
for q in questions:
    storage.questions[q.question_id] = q

# 시험지-문제 매핑
storage.exam_sheet_questions[exam_sheet_id] = [q.question_id for q in questions]

print(f"테스트 데이터 설정 완료:")
print(f"- Exam ID: {exam_id}")
print(f"- Exam Sheet ID: {exam_sheet_id}")
print(f"- 문제 수: {len(questions)}")
print(f"- 저장소 상태: {storage.get_stats()}")
