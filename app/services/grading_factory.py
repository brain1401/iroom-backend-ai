"""
채점 서비스 팩토리

의존성 주입을 위한 서비스 팩토리 및 설정 관리

주요 기능:
- Repository 구현체 선택 (MySQL vs 인메모리)
- 채점 서비스 인스턴스 생성
- 설정 기반 자동 초기화
"""

from typing import Tuple
from app.config.settings import Settings
from app.services.grading_service import GradingService
from app.repositories.interfaces import (
    ExamRepositoryInterface,
    QuestionRepositoryInterface,
    GradingRepositoryInterface
)


class GradingServiceFactory:
    """
    채점 서비스 팩토리
    
    설정에 따라 적절한 Repository 구현체를 선택하고
    채점 서비스들을 초기화하는 팩토리 클래스
    """
    
    @staticmethod
    def create_repositories(
        settings: Settings
    ) -> Tuple[ExamRepositoryInterface, QuestionRepositoryInterface, GradingRepositoryInterface]:
        """
        설정에 따른 Repository 구현체 생성
        
        Args:
            settings: 애플리케이션 설정
            
        Returns:
            Tuple: (ExamRepo, QuestionRepo, GradingRepo) 인스턴스들
        """
        if settings.database_enabled:
            # MySQL 구현체 사용
            from app.repositories.mysql_implementation import (
                MySQLConnection,
                MySQLExamRepository,
                MySQLQuestionRepository,
                MySQLGradingRepository
            )
            
            # DB 연결 URL 파싱
            db_url = settings.database_url
            if db_url.startswith("mysql://"):
                # mysql://user:password@host:port/database 형식 파싱
                import re
                pattern = r"mysql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)"
                match = re.match(pattern, db_url)
                
                if match:
                    user, password, host, port, database = match.groups()
                    connection = MySQLConnection(
                        host=host,
                        port=int(port),
                        user=user,
                        password=password,
                        database=database,
                        pool_size=settings.database_pool_size,
                        pool_timeout=settings.database_pool_timeout
                    )
                else:
                    # 기본값 사용
                    connection = MySQLConnection(
                        pool_size=settings.database_pool_size,
                        pool_timeout=settings.database_pool_timeout
                    )
            else:
                # 기본값 사용
                connection = MySQLConnection(
                    pool_size=settings.database_pool_size,
                    pool_timeout=settings.database_pool_timeout
                )
            
            exam_repo = MySQLExamRepository(connection)
            question_repo = MySQLQuestionRepository(connection)
            grading_repo = MySQLGradingRepository(connection)
            
        else:
            # 인메모리 구현체 사용
            from app.repositories.memory_implementation import (
                InMemoryExamRepository,
                InMemoryQuestionRepository,
                InMemoryGradingRepository
            )
            
            exam_repo = InMemoryExamRepository()
            question_repo = InMemoryQuestionRepository()
            grading_repo = InMemoryGradingRepository()
        
        return exam_repo, question_repo, grading_repo
    
    @staticmethod
    def create_grading_service(settings: Settings) -> GradingService:
        """
        채점 서비스 인스턴스 생성
        
        Args:
            settings: 애플리케이션 설정
            
        Returns:
            GradingService: 초기화된 채점 서비스
        """
        if not settings.gemini_api_key:
            raise ValueError("Gemini API key is required for grading service")
        
        return GradingService(
            gemini_api_key=settings.gemini_api_key,
            max_concurrent_subjective=settings.grading_max_concurrent_subjective
        )


# 전역 인스턴스들 (싱글톤 패턴)
_repositories: Tuple[
    ExamRepositoryInterface,
    QuestionRepositoryInterface, 
    GradingRepositoryInterface
] | None = None

_grading_service: GradingService | None = None


def get_repositories(settings: Settings) -> Tuple[
    ExamRepositoryInterface,
    QuestionRepositoryInterface,
    GradingRepositoryInterface
]:
    """
    Repository 인스턴스들 반환 (싱글톤)
    
    Args:
        settings: 애플리케이션 설정
        
    Returns:
        Tuple: (ExamRepo, QuestionRepo, GradingRepo) 인스턴스들
    """
    global _repositories
    
    if _repositories is None:
        _repositories = GradingServiceFactory.create_repositories(settings)
    
    return _repositories


def get_grading_service(settings: Settings) -> GradingService:
    """
    채점 서비스 인스턴스 반환 (싱글톤)
    
    Args:
        settings: 애플리케이션 설정
        
    Returns:
        GradingService: 채점 서비스 인스턴스
    """
    global _grading_service
    
    if _grading_service is None:
        _grading_service = GradingServiceFactory.create_grading_service(settings)
    
    return _grading_service


async def cleanup_resources():
    """
    리소스 정리 (애플리케이션 종료시 호출)
    
    DB 연결 등 외부 리소스를 안전하게 정리
    """
    global _repositories
    
    if _repositories:
        exam_repo, _, _ = _repositories
        
        # MySQL 연결 정리
        from app.repositories.mysql_implementation import MySQLExamRepository
        if isinstance(exam_repo, MySQLExamRepository):
            await exam_repo.connection.close()
    
    # 전역 인스턴스 초기화
    _repositories = None
    _grading_orchestrator = None