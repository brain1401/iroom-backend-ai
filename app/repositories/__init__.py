"""
데이터 접근 계층 (Repository 패턴)

DB 접근을 추상화하여 비즈니스 로직과 분리
테스트 용이성과 확장성 제공

주요 Repository:
- ExamRepository: 시험 및 제출 관련 데이터 접근
- QuestionRepository: 문제 관련 데이터 접근  
- GradingRepository: 채점 결과 관련 데이터 접근
"""

from .interfaces import (
    ExamRepositoryInterface,
    QuestionRepositoryInterface,  
    GradingRepositoryInterface
)

from .mysql_implementation import (
    MySQLExamRepository,
    MySQLQuestionRepository,
    MySQLGradingRepository
)

from .memory_implementation import (
    InMemoryExamRepository,
    InMemoryQuestionRepository,
    InMemoryGradingRepository
)

__all__ = [
    # 인터페이스
    "ExamRepositoryInterface",
    "QuestionRepositoryInterface",
    "GradingRepositoryInterface",
    # MySQL 구현체
    "MySQLExamRepository", 
    "MySQLQuestionRepository",
    "MySQLGradingRepository",
    # 인메모리 구현체
    "InMemoryExamRepository",
    "InMemoryQuestionRepository", 
    "InMemoryGradingRepository"
]