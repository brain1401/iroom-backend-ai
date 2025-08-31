"""
Repository 인터페이스 정의

데이터 접근 추상화를 위한 인터페이스들
구현체는 MySQL, PostgreSQL, 인메모리 등 다양하게 제공 가능

주요 인터페이스:
- ExamRepositoryInterface: 시험 제출 및 답안 데이터 접근
- QuestionRepositoryInterface: 문제 정보 데이터 접근
- GradingRepositoryInterface: 채점 결과 데이터 저장/조회
"""

from abc import ABC, abstractmethod
from uuid import UUID
from app.models.grading import (
    QuestionData, 
    StudentAnswer,
    ExamGradingResult,
    QuestionGradingResult
)


class ExamRepositoryInterface(ABC):
    """
    시험 제출 및 답안 데이터 접근 인터페이스
    
    책임:
    - 시험 제출 정보 조회
    - 학생 답안 조회
    - 시험지 정보 조회
    """
    
    @abstractmethod
    async def get_submission_by_id(self, submission_id: UUID) -> dict | None:
        """
        제출 ID로 시험 제출 정보 조회
        
        Args:
            submission_id: 제출 고유 ID
            
        Returns:
            dict | None: 제출 정보 (exam_submission 테이블 데이터) 또는 None
        """
        pass
    
    @abstractmethod 
    async def get_answers_by_submission_id(self, submission_id: UUID) -> list[StudentAnswer]:
        """
        제출 ID로 해당 제출의 모든 답안 조회
        
        Args:
            submission_id: 제출 고유 ID
            
        Returns:
            list[StudentAnswer]: 학생 답안 목록
        """
        pass
    
    @abstractmethod
    async def get_exam_sheet_id_by_submission_id(self, submission_id: UUID) -> UUID | None:
        """
        제출 ID로 시험지 ID 조회
        
        Args:
            submission_id: 제출 고유 ID
            
        Returns:
            UUID | None: 시험지 ID 또는 None
        """
        pass


class QuestionRepositoryInterface(ABC):
    """
    문제 정보 데이터 접근 인터페이스
    
    책임:
    - 시험지별 문제 목록 조회  
    - 개별 문제 정보 조회
    - 문제 유형별 필터링
    """
    
    @abstractmethod
    async def get_questions_by_exam_sheet_id(self, exam_sheet_id: UUID) -> list[QuestionData]:
        """
        시험지 ID로 해당 시험지의 모든 문제 조회
        
        Args:
            exam_sheet_id: 시험지 고유 ID
            
        Returns:
            list[QuestionData]: 문제 정보 목록
        """
        pass
    
    @abstractmethod
    async def get_question_by_id(self, question_id: UUID) -> QuestionData | None:
        """
        문제 ID로 개별 문제 정보 조회
        
        Args:
            question_id: 문제 고유 ID
            
        Returns:
            QuestionData | None: 문제 정보 또는 None
        """
        pass


class GradingRepositoryInterface(ABC):
    """
    채점 결과 데이터 저장/조회 인터페이스
    
    책임:
    - 채점 결과 저장 (exam_result, exam_result_question)
    - 채점 결과 조회
    - 채점 상태 업데이트
    - 재채점 이력 관리
    """
    
    @abstractmethod
    async def save_grading_result(self, grading_result: ExamGradingResult) -> bool:
        """
        전체 시험 채점 결과 저장
        
        exam_result 및 exam_result_question 테이블에 트랜잭션으로 저장
        
        Args:
            grading_result: 저장할 채점 결과
            
        Returns:
            bool: 저장 성공 여부
        """
        pass
    
    @abstractmethod
    async def get_grading_result_by_submission_id(
        self, 
        submission_id: UUID
    ) -> ExamGradingResult | None:
        """
        제출 ID로 채점 결과 조회
        
        Args:
            submission_id: 제출 고유 ID
            
        Returns:
            ExamGradingResult | None: 채점 결과 또는 None
        """
        pass
    
    @abstractmethod
    async def update_grading_status(
        self,
        result_id: UUID,
        status: str
    ) -> bool:
        """
        채점 상태 업데이트
        
        Args:
            result_id: 채점 결과 ID
            status: 새로운 상태
            
        Returns:
            bool: 업데이트 성공 여부
        """
        pass
    
    @abstractmethod
    async def get_grading_results_by_exam_id(
        self,
        exam_id: UUID
    ) -> list[ExamGradingResult]:
        """
        시험 ID로 모든 채점 결과 조회 (배치 채점용)
        
        Args:
            exam_id: 시험 고유 ID
            
        Returns:
            list[ExamGradingResult]: 채점 결과 목록
        """
        pass
    
    @abstractmethod
    async def save_question_grading_result(
        self,
        result_id: UUID,
        question_result: QuestionGradingResult
    ) -> bool:
        """
        개별 문제 채점 결과 저장/업데이트
        
        Args:
            result_id: 전체 채점 결과 ID
            question_result: 문제별 채점 결과
            
        Returns:
            bool: 저장 성공 여부
        """
        pass