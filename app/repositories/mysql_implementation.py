"""
MySQL Database Repository 구현체

aiomysql을 사용한 실제 DB 접근 구현체들
트랜잭션 관리 및 연결 풀링 지원

의존성 추가 필요:
- aiomysql >= 0.1.1

주요 구현체:
- MySQLExamRepository: 시험 제출 및 답안 DB 접근
- MySQLQuestionRepository: 문제 정보 DB 접근
- MySQLGradingRepository: 채점 결과 DB 저장/조회
"""

import aiomysql  # type: ignore[reportMissingImports]
import json
from datetime import datetime
from decimal import Decimal
from uuid import UUID
import structlog  # type: ignore[reportMissingImports]

from app.models.grading import (
    QuestionData,
    StudentAnswerSheetQuestion,
    ExamGradingResult,
    QuestionGradingResult,
    QuestionType,
    Difficulty,
    GradingMethod,
    GradingStatus,
)
from .interfaces import (
    ExamRepositoryInterface,
    QuestionRepositoryInterface,
    GradingRepositoryInterface,
)

logger = structlog.get_logger("mysql_repository")


def _normalize_choices(choices_raw):
    """DB에서 읽은 choices를 QuestionData가 기대하는 dict 형태로 정규화.

    허용 입력 예:
    - dict (이미 올바른 형태): {"1": "A", "2": "B"} 또는 {1: "A", 2: "B"}
    - list[dict]: [{"id": 1, "text": "A"}, ...]
    - list[str]: ["A", "B", "C", "D"] → 1부터 번호 매김
    - 기타: None 반환
    """
    try:
        # 이미 dict인 경우 그대로 사용
        if isinstance(choices_raw, dict):
            return choices_raw

        # 문자열이면 JSON 디코딩 시도
        if isinstance(choices_raw, str):
            try:
                parsed = json.loads(choices_raw)
            except Exception:
                return None
        else:
            parsed = choices_raw

        # list[dict] 패턴: {id, text}
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            normalized: dict[int | str, str] = {}
            for item in parsed:
                choice_id = item.get("id")
                text = item.get("text") or item.get("label") or item.get("value")
                if text is None:
                    continue
                # 키는 정수 또는 문자열 모두 허용 (소비 측에서 둘 다 조회 시도)
                if isinstance(choice_id, int):
                    normalized[choice_id] = str(text)
                elif isinstance(choice_id, str) and choice_id.isdigit():
                    normalized[int(choice_id)] = str(text)
                else:
                    # id가 없으면 1부터 순번 재부여
                    idx = len(normalized) + 1
                    normalized[idx] = str(text)
            return normalized or None

        # list[str] 패턴
        if isinstance(parsed, list) and (not parsed or isinstance(parsed[0], str)):
            return {i + 1: v for i, v in enumerate(parsed)}
    except Exception:
        return None

    return None


class MySQLConnection:
    """
    MySQL 연결 관리자

    기능:
    - 연결 풀 관리
    - 트랜잭션 지원
    - 자동 재연결
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 3306,
        user: str = "root",
        password: str = "password",
        database: str = "iroom_db",
        pool_size: int = 10,
        pool_timeout: int = 30,
    ):
        """
        MySQL 연결 설정 초기화

        Args:
            host: DB 호스트
            port: DB 포트
            user: DB 사용자명
            password: DB 비밀번호
            database: DB 이름
            pool_size: 연결 풀 크기
            pool_timeout: 연결 타임아웃 (초)
        """
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.pool_size = pool_size
        self.pool_timeout = pool_timeout
        self._pool: aiomysql.Pool | None = None

    async def get_pool(self) -> aiomysql.Pool:
        """연결 풀 반환 (필요시 생성)"""
        if self._pool is None or self._pool.closed:
            self._pool = await aiomysql.create_pool(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                db=self.database,
                minsize=1,
                maxsize=self.pool_size,
                pool_recycle=3600,  # 1시간 후 연결 재활용
                autocommit=False,
                charset="utf8mb4",
            )
        assert self._pool is not None, "Pool should be created"
        return self._pool

    async def close(self):
        """연결 풀 종료"""
        if self._pool and not self._pool.closed:
            self._pool.close()
            await self._pool.wait_closed()

    def _uuid_to_binary(self, uuid_val: UUID) -> bytes:
        """UUID를 MySQL BINARY(16) 형식으로 변환"""
        return uuid_val.bytes

    def _binary_to_uuid(self, binary_val: bytes) -> UUID:
        """MySQL BINARY(16)을 UUID로 변환"""
        return UUID(bytes=binary_val)


class MySQLExamRepository(ExamRepositoryInterface):
    """
    MySQL 기반 시험 제출 및 답안 데이터 접근 구현체

    연결하는 테이블:
    - exam_submission: 시험 제출 정보
    - student_answer_sheet: 학생 답안
    - exam: 시험 정보 (시험지 ID 조회용)
    """

    def __init__(self, connection: MySQLConnection):
        """
        MySQL 시험 Repository 초기화

        Args:
            connection: MySQL 연결 관리자
        """
        self.connection = connection

    async def get_submission_by_id(self, submission_id: UUID) -> dict | None:
        """
        제출 ID로 시험 제출 정보 조회

        Args:
            submission_id: 제출 고유 ID

        Returns:
            dict | None: 제출 정보 또는 None
        """
        pool = await self.connection.get_pool()

        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                query = """
                SELECT 
                    BIN_TO_UUID(id) as id,
                    student_id,  
                    BIN_TO_UUID(exam_id) as exam_id,
                    submitted_at
                FROM exam_submission 
                WHERE id = UUID_TO_BIN(%s)
                """
                await cursor.execute(query, (str(submission_id),))
                result = await cursor.fetchone()

                if result:
                    logger.info(
                        "시험 제출 정보 조회 성공",
                        submission_id=str(submission_id),
                        exam_id=result.get("exam_id"),
                    )
                else:
                    logger.warning(
                        "시험 제출 정보 없음", submission_id=str(submission_id)
                    )

                return result

    async def get_answers_by_submission_id(
        self, submission_id: UUID
    ) -> list[StudentAnswerSheetQuestion]:
        """
        제출 ID로 해당 제출의 모든 답안 조회

        수정: student_answer_sheet → student_answer_sheet_question 조인

        Args:
            submission_id: 제출 고유 ID

        Returns:
            list[StudentAnswerSheetQuestion]: 학생 답안 목록
        """
        pool = await self.connection.get_pool()

        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                query = """
                SELECT
                    BIN_TO_UUID(sasq.id) as id,
                    BIN_TO_UUID(sasq.question_id) as question_id,
                    BIN_TO_UUID(sasq.student_answer_sheet_id) as student_answer_sheet_id,
                    sasq.answer_text,
                    sasq.selected_choice
                FROM student_answer_sheet sas
                INNER JOIN student_answer_sheet_question sasq 
                    ON sas.id = sasq.student_answer_sheet_id
                WHERE sas.submission_id = UUID_TO_BIN(%s)
                ORDER BY sasq.question_id
                """
                await cursor.execute(query, (str(submission_id),))
                rows = await cursor.fetchall()

                answers: list[StudentAnswerSheetQuestion] = []
                for row in rows:
                    answer = StudentAnswerSheetQuestion(
                        id=UUID(row["id"]),
                        question_id=UUID(row["question_id"]),
                        student_answer_sheet_id=UUID(row["student_answer_sheet_id"]),
                        answer_text=row["answer_text"],
                        selected_choice=row["selected_choice"],
                    )
                    answers.append(answer)

                logger.info(
                    "학생 답안 조회 완료",
                    submission_id=str(submission_id),
                    answer_count=len(answers),
                )

                return answers

    async def get_exam_sheet_id_by_submission_id(
        self, submission_id: UUID
    ) -> UUID | None:
        """
        제출 ID로 시험지 ID 조회

        Args:
            submission_id: 제출 고유 ID

        Returns:
            UUID | None: 시험지 ID 또는 None
        """
        pool = await self.connection.get_pool()

        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                query = """
                SELECT BIN_TO_UUID(e.exam_sheet_id) as exam_sheet_id
                FROM exam_submission es
                JOIN exam e ON es.exam_id = e.id
                WHERE es.id = UUID_TO_BIN(%s)
                """
                await cursor.execute(query, (str(submission_id),))
                result = await cursor.fetchone()

                if result:
                    exam_sheet_id = UUID(result["exam_sheet_id"])
                    logger.info(
                        "시험지 ID 조회 성공",
                        submission_id=str(submission_id),
                        exam_sheet_id=str(exam_sheet_id),
                    )
                    return exam_sheet_id

                logger.warning("시험지 ID 조회 실패", submission_id=str(submission_id))
                return None

    async def create_submission(
        self,
        exam_id: UUID,
        student_id: int,
        submission_id: UUID | None = None,
        student_name: str | None = None,
        student_phone: str | None = None,
    ) -> UUID:
        """
        새로운 제출 생성

        Args:
            exam_id: 시험 ID
            student_id: 학생 ID
            submission_id: 제출 ID (없으면 자동 생성)

        Returns:
            UUID: 생성된 제출 ID
        """
        from app.utils.uuid_utils import generate_uuidv7, uuid_to_binary
        import structlog
        
        logger = structlog.get_logger()

        submission_id = submission_id or generate_uuidv7()
        
        logger.info(
            "MySQL create_submission 시작",
            exam_id=str(exam_id),
            student_id=student_id,
            submission_id=str(submission_id)
        )

        try:
            pool = await self.connection.get_pool()
            logger.info("MySQL 커넥션 풀 획득 성공")
            
            async with pool.acquire() as conn:
                logger.info("MySQL 커넥션 획득 성공")
                
                async with conn.cursor() as cursor:
                    # submitted_at 지정, total_score는 NULL 기본값 사용
                    sql = """
                    INSERT INTO exam_submission (id, exam_id, student_id, submitted_at)
                    VALUES (%s, %s, %s, NOW())
                    """
                    
                    params = (
                        uuid_to_binary(submission_id),
                        uuid_to_binary(exam_id),
                        student_id,
                    )
                    
                    logger.info(
                        "MySQL INSERT 쿼리 실행 시도",
                        sql=sql,
                        exam_id=str(exam_id),
                        student_id=student_id,
                        submission_id=str(submission_id)
                    )
                    
                    await cursor.execute(sql, params)
                    
                    logger.info("MySQL INSERT 성공, 커밋 시도")
                    await conn.commit()
                    logger.info("MySQL 커밋 성공")

        except Exception as e:
            logger.error(
                "MySQL create_submission 실패",
                exam_id=str(exam_id),
                student_id=student_id,
                submission_id=str(submission_id),
                error=str(e),
                error_type=type(e).__name__
            )
            raise

        logger.info(
            "MySQL create_submission 완료",
            submission_id=str(submission_id)
        )
        return submission_id

    async def create_answer_sheet(
        self,
        submission_id: UUID,
        student_name: str,
        answer_sheet_id: UUID | None = None,
    ) -> UUID:
        """
        학생 답안지 헤더 생성 (student_answer_sheet)
        """
        from app.utils.uuid_utils import generate_uuidv7, uuid_to_binary
        
        logger.info("MySQL create_answer_sheet 시작", submission_id=str(submission_id))
        answer_sheet_id = answer_sheet_id or generate_uuidv7()
        logger.info("answer_sheet_id 생성", answer_sheet_id=str(answer_sheet_id))

        pool = await self.connection.get_pool()
        logger.info("MySQL 커넥션 풀 획득")
        
        async with pool.acquire() as conn:
            logger.info("MySQL 커넥션 획득 성공")
            async with conn.cursor() as cursor:
                logger.info("MySQL 커서 생성 성공")
                
                sql = """
                    INSERT INTO student_answer_sheet (id, submission_id, student_name)
                    VALUES (%s, %s, %s)
                    """
                params = (
                    uuid_to_binary(answer_sheet_id),
                    uuid_to_binary(submission_id),
                    student_name,
                )
                logger.info("SQL 실행 준비", sql=sql, student_name=student_name)
                
                await cursor.execute(sql, params)
                logger.info("SQL 실행 성공")
                
                await conn.commit()
                logger.info("MySQL 커밋 성공")

        logger.info("MySQL create_answer_sheet 완료", answer_sheet_id=str(answer_sheet_id))
        return answer_sheet_id

    async def create_answer_sheet_questions(
        self, answer_sheet_id: UUID, answers: list[dict]
    ) -> list[UUID]:
        """
        학생 답안지 문제별 답안 생성
        
        Args:
            answer_sheet_id: 답안지 ID
            answers: 문제별 답안 목록
            
        Returns:
            list[UUID]: 생성된 답안 ID 리스트
        """
        from app.utils.uuid_utils import generate_uuidv7
        
        pool = await self.connection.get_pool()
        answer_ids: list[UUID] = []
        
        try:
            logger.info(
                "create_answer_sheet_questions 시작",
                answer_sheet_id=str(answer_sheet_id),
                answer_count=len(answers)
            )
            
            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # 각 답안을 개별적으로 삽입 (과거 작동하던 패턴)
                    for answer in answers:
                        # ID가 없으면 새로 생성
                        answer_id = answer.get("id")
                        if not answer_id:
                            answer_id = generate_uuidv7()
                        answer_ids.append(answer_id)
                        
                        question_id = answer.get("question_id")
                        
                        query = """
                        INSERT INTO student_answer_sheet_question 
                        (id, student_answer_sheet_id, question_id, answer_text, selected_choice)
                        VALUES (UUID_TO_BIN(%s), UUID_TO_BIN(%s), UUID_TO_BIN(%s), %s, %s)
                        """
                        
                        await cursor.execute(
                            query,
                            (
                                str(answer_id),
                                str(answer_sheet_id),
                                str(question_id),
                                answer.get('answer_text'),
                                answer.get('selected_choice'),
                            ),
                        )
                        
                        logger.debug(
                            "답안 삽입 완료",
                            answer_id=str(answer_id),
                            question_id=str(question_id)
                        )
                    
                    # 모든 삽입 후 한 번만 커밋
                    await conn.commit()
                    
                    logger.info(
                        "student_answer_sheet_question 생성 성공",
                        answer_sheet_id=str(answer_sheet_id),
                        answer_count=len(answer_ids)
                    )
                    return answer_ids
                    
        except Exception as e:
            logger.error(
                "student_answer_sheet_question 생성 실패",
                answer_sheet_id=str(answer_sheet_id),
                error=str(e),
                error_type=type(e).__name__
            )
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return []

    async def get_exam_sheet_id_by_exam_id(self, exam_id: UUID) -> UUID | None:
        """
        시험 ID로 시험지 ID 조회

        Args:
            exam_id: 시험 ID

        Returns:
            UUID | None: 시험지 ID 또는 None
        """
        pool = await self.connection.get_pool()

        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                query = """
                SELECT BIN_TO_UUID(exam_sheet_id) as exam_sheet_id
                FROM exam
                WHERE id = UUID_TO_BIN(%s)
                """
                await cursor.execute(query, (str(exam_id),))
                result = await cursor.fetchone()

                if result:
                    exam_sheet_id = UUID(result["exam_sheet_id"])
                    logger.info(
                        "시험지 ID 조회 성공",
                        exam_id=str(exam_id),
                        exam_sheet_id=str(exam_sheet_id),
                    )
                    return exam_sheet_id

                logger.warning("시험지 ID 조회 실패", exam_id=str(exam_id))
                return None


class MySQLQuestionRepository(QuestionRepositoryInterface):
    """
    MySQL 기반 문제 정보 데이터 접근 구현체

    연결하는 테이블:
    - question: 문제 정보
    - exam_sheet_question: 시험지별 문제 매핑
    """

    def __init__(self, connection: MySQLConnection):
        """
        MySQL 문제 Repository 초기화

        Args:
            connection: MySQL 연결 관리자
        """
        self.connection = connection

    async def get_questions_by_exam_sheet_id(
        self, exam_sheet_id: UUID
    ) -> list[QuestionData]:
        """
        시험지 ID로 해당 시험지의 모든 문제 조회

        Args:
            exam_sheet_id: 시험지 고유 ID

        Returns:
            list[QuestionData]: 문제 정보 목록
        """
        pool = await self.connection.get_pool()

        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                query = """
                SELECT
                    BIN_TO_UUID(q.id) as id,
                    q.question_text,
                    q.question_type,
                    q.difficulty,
                    esq.points,
                    q.answer_text,
                    q.choices,
                    q.correct_choice,
                    q.scoring_rubric
                FROM question q
                JOIN exam_sheet_question esq ON q.id = esq.question_id
                WHERE esq.exam_sheet_id = UUID_TO_BIN(%s)
                ORDER BY esq.seq_no
                """
                await cursor.execute(query, (str(exam_sheet_id),))
                rows = await cursor.fetchall()

                questions = []
                for row in rows:
                    # choices 정규화 (list 형태를 dict로 변환)
                    choices = (
                        _normalize_choices(row.get("choices"))
                        if row.get("choices") is not None
                        else None
                    )

                    question = QuestionData(
                        question_id=UUID(row["id"]),
                        question_text=row["question_text"],
                        question_type=QuestionType(row["question_type"]),
                        difficulty=Difficulty(row["difficulty"]),
                        points=row["points"],
                        answer_text=row["answer_text"],
                        choices=choices,
                        correct_choice=row["correct_choice"],
                        scoring_rubric=row["scoring_rubric"],
                    )
                    questions.append(question)

                logger.info(
                    "시험지 문제 조회 완료",
                    exam_sheet_id=str(exam_sheet_id),
                    question_count=len(questions),
                    multiple_choice_count=sum(
                        1
                        for q in questions
                        if q.question_type == QuestionType.MULTIPLE_CHOICE
                    ),
                    subjective_count=sum(
                        1
                        for q in questions
                        if q.question_type == QuestionType.SUBJECTIVE
                    ),
                )

                return questions

    async def get_question_by_id(self, question_id: UUID) -> QuestionData | None:
        """
        문제 ID로 개별 문제 정보 조회

        Args:
            question_id: 문제 고유 ID

        Returns:
            QuestionData | None: 문제 정보 또는 None
        """
        pool = await self.connection.get_pool()

        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                query = """
                SELECT
                    BIN_TO_UUID(id) as id,
                    question_text,
                    question_type,
                    difficulty,
                    points,
                    answer_text,
                    choices,
                    correct_choice,
                    scoring_rubric
                FROM question
                WHERE id = UUID_TO_BIN(%s)
                """
                await cursor.execute(query, (str(question_id),))
                row = await cursor.fetchone()

                if not row:
                    logger.warning("문제 정보 없음", question_id=str(question_id))
                    return None

                # choices 정규화 (list 형태를 dict로 변환)
                choices = (
                    _normalize_choices(row.get("choices"))
                    if row.get("choices") is not None
                    else None
                )

                question = QuestionData(
                    question_id=UUID(row["id"]),
                    question_text=row["question_text"],
                    question_type=QuestionType(row["question_type"]),
                    difficulty=Difficulty(row["difficulty"]),
                    points=row["points"],
                    answer_text=row["answer_text"],
                    choices=choices,
                    correct_choice=row["correct_choice"],
                    scoring_rubric=row["scoring_rubric"],
                )

                logger.info("문제 정보 조회 성공", question_id=str(question_id))
                return question


class MySQLGradingRepository(GradingRepositoryInterface):
    """
    MySQL 기반 채점 결과 데이터 저장/조회 구현체

    연결하는 테이블:
    - exam_result: 전체 시험 채점 결과
    - exam_result_question: 문제별 채점 결과
    """

    def __init__(self, connection: MySQLConnection):
        """
        MySQL 채점 Repository 초기화

        Args:
            connection: MySQL 연결 관리자
        """
        self.connection = connection

    async def save_grading_result(self, grading_result: ExamGradingResult) -> bool:
        """
        전체 시험 채점 결과 저장 (트랜잭션)

        exam_result 및 exam_result_question 테이블에 저장

        Args:
            grading_result: 저장할 채점 결과

        Returns:
            bool: 저장 성공 여부
        """
        pool = await self.connection.get_pool()

        async with pool.acquire() as conn:
            await conn.begin()  # 트랜잭션 시작
            try:
                # 1. exam_result 테이블에 전체 결과 저장
                async with conn.cursor() as cursor:
                        exam_result_query = """
                        INSERT INTO exam_result (
                            id, submission_id, exam_sheet_id,
                            graded_at, total_score, status,
                            scoring_comment, version, created_at, updated_at
                        ) VALUES (
                            UUID_TO_BIN(%s), UUID_TO_BIN(%s), UUID_TO_BIN(%s),
                            %s, %s, %s, %s, %s, %s, %s
                        )
                        """

                        await cursor.execute(
                            exam_result_query,
                            (
                                str(grading_result.result_id),
                                str(grading_result.submission_id),
                                str(grading_result.exam_sheet_id),
                                grading_result.graded_at or datetime.now(),
                                grading_result.total_score,
                                grading_result.status.value,
                                grading_result.grading_comment,
                                grading_result.version,
                                datetime.now(),  # created_at
                                datetime.now(),  # updated_at
                            ),
                        )

                # 2. exam_result_question 테이블에 문제별 결과 저장
                if grading_result.question_results:
                    async with conn.cursor() as cursor:
                        question_result_query = """
                        INSERT INTO exam_result_question (
                            id, exam_result_id, question_id, answer_id,
                            is_correct, score,
                            scoring_method, scoring_comment, confidence_score,
                            created_at, updated_at
                        ) VALUES (
                            UUID_TO_BIN(%s), UUID_TO_BIN(%s), UUID_TO_BIN(%s), UUID_TO_BIN(%s),
                            %s, %s, %s, %s, %s,
                            %s, %s
                        )
                        """
                        
                        from app.utils.uuid_utils import generate_uuidv7

                        for question_result in grading_result.question_results:
                            question_result_id = generate_uuidv7()
                            await cursor.execute(
                                question_result_query,
                                (
                                    str(question_result_id),
                                    str(grading_result.result_id),
                                    str(question_result.question_id),
                                    str(question_result.answer_id),
                                    question_result.is_correct,
                                    question_result.score,
                                    question_result.grading_method.value,
                                    question_result.scoring_comment,
                                    question_result.confidence_score,
                                    question_result.created_at or datetime.now(),
                                    question_result.created_at or datetime.now(),  # updated_at도 동일하게 설정
                                ),
                            )

                await conn.commit()  # 트랜잭션 커밋
                
                logger.info(
                    "채점 결과 저장 성공",
                    result_id=str(grading_result.result_id),
                    submission_id=str(grading_result.submission_id),
                    total_score=grading_result.total_score,
                    question_count=len(grading_result.question_results),
                )

                return True

            except Exception as e:
                await conn.rollback()  # 트랜잭션 롤백
                logger.error(
                    "채점 결과 저장 실패",
                    result_id=str(grading_result.result_id),
                    submission_id=str(grading_result.submission_id),
                    error=str(e),
                )
                return False

    async def get_grading_result_by_submission_id(
        self, submission_id: UUID
    ) -> ExamGradingResult | None:
        """
        제출 ID로 채점 결과 조회

        Args:
            submission_id: 제출 고유 ID

        Returns:
            ExamGradingResult | None: 채점 결과 또는 None
        """
        pool = await self.connection.get_pool()

        async with pool.acquire() as conn:
            # 1. exam_result 조회
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                exam_result_query = """
                SELECT
                    BIN_TO_UUID(id) as id,
                    BIN_TO_UUID(submission_id) as submission_id,
                    BIN_TO_UUID(exam_sheet_id) as exam_sheet_id,
                    graded_at,
                    total_score,
                    status,
                    grading_comment,
                    version
                FROM exam_result
                WHERE submission_id = UUID_TO_BIN(%s)
                ORDER BY version DESC
                LIMIT 1
                """
                await cursor.execute(exam_result_query, (str(submission_id),))
                exam_row = await cursor.fetchone()

                if not exam_row:
                    logger.warning("채점 결과 없음", submission_id=str(submission_id))
                    return None

                result_id = UUID(exam_row["id"])

                # 2. exam_result_question 조회
                question_results_query = """
                SELECT
                    BIN_TO_UUID(question_id) as question_id,
                    BIN_TO_UUID(answer_id) as answer_id,
                    is_correct,
                    score,
                    max_score,
                    grading_method,
                    grading_comment,
                    confidence_score,
                    created_at
                FROM exam_result_question
                WHERE exam_result_id = UUID_TO_BIN(%s)
                ORDER BY created_at
                """
                await cursor.execute(question_results_query, (str(result_id),))
                question_rows = await cursor.fetchall()

                # QuestionGradingResult 객체 생성
                question_results = []
                for row in question_rows:
                    question_result = QuestionGradingResult(
                        question_id=UUID(row["question_id"]),
                        answer_id=UUID(row["answer_id"]),
                        is_correct=(
                            bool(row["is_correct"])
                            if row["is_correct"] is not None
                            else None
                        ),
                        score=row["score"],
                        max_score=row["max_score"],
                        grading_method=GradingMethod(row["grading_method"]),
                        confidence_score=(
                            Decimal(str(row["confidence_score"]))
                            if row["confidence_score"]
                            else None
                        ),
                        scoring_comment=row["grading_comment"],
                        created_at=row["created_at"],
                    )
                    question_results.append(question_result)

                # ExamGradingResult 객체 생성
                grading_result = ExamGradingResult(
                    result_id=result_id,
                    submission_id=UUID(exam_row["submission_id"]),
                    exam_sheet_id=UUID(exam_row["exam_sheet_id"]),
                    status=GradingStatus(exam_row["status"]),
                    total_score=exam_row["total_score"],
                    max_total_score=(
                        sum(qr.max_score for qr in question_results)
                        if question_results
                        else None
                    ),
                    question_results=question_results,
                    grading_comment=exam_row["grading_comment"],
                    graded_at=exam_row["graded_at"],
                    version=exam_row["version"],
                )

                logger.info(
                    "채점 결과 조회 성공",
                    submission_id=str(submission_id),
                    result_id=str(result_id),
                    question_count=len(question_results),
                )

                return grading_result

    async def update_grading_status(self, result_id: UUID, status: str) -> bool:
        """
        채점 상태 업데이트

        Args:
            result_id: 채점 결과 ID
            status: 새로운 상태

        Returns:
            bool: 업데이트 성공 여부
        """
        pool = await self.connection.get_pool()

        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                query = """
                UPDATE exam_result 
                SET status = %s, updated_at = %s
                WHERE id = UUID_TO_BIN(%s)
                """

                rows_affected = await cursor.execute(
                    query, (status, datetime.now(), str(result_id))
                )

                await conn.commit()

                success = rows_affected > 0
                if success:
                    logger.info(
                        "채점 상태 업데이트 성공",
                        result_id=str(result_id),
                        status=status,
                    )
                else:
                    logger.warning(
                        "채점 상태 업데이트 실패",
                        result_id=str(result_id),
                        status=status,
                    )

                return success

    async def get_grading_results_by_exam_id(
        self, exam_id: UUID
    ) -> list[ExamGradingResult]:
        """
        시험 ID로 모든 채점 결과 조회 (배치 채점용)

        Args:
            exam_id: 시험 고유 ID

        Returns:
            list[ExamGradingResult]: 채점 결과 목록
        """
        pool = await self.connection.get_pool()

        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                query = """
                SELECT BIN_TO_UUID(er.submission_id) as submission_id
                FROM exam_result er
                JOIN exam_submission es ON er.submission_id = es.id
                WHERE es.exam_id = UUID_TO_BIN(%s)
                """
                await cursor.execute(query, (str(exam_id),))
                rows = await cursor.fetchall()

                results = []
                for row in rows:
                    submission_id = UUID(row["submission_id"])
                    result = await self.get_grading_result_by_submission_id(
                        submission_id
                    )
                    if result:
                        results.append(result)

                logger.info(
                    "시험별 채점 결과 조회 완료",
                    exam_id=str(exam_id),
                    result_count=len(results),
                )

                return results

    async def save_question_grading_result(
        self, result_id: UUID, question_result: QuestionGradingResult
    ) -> bool:
        """
        개별 문제 채점 결과 저장/업데이트

        Args:
            result_id: 전체 채점 결과 ID
            question_result: 문제별 채점 결과

        Returns:
            bool: 저장 성공 여부
        """
        pool = await self.connection.get_pool()

        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # UPSERT (ON DUPLICATE KEY UPDATE) 사용
                query = """
                INSERT INTO exam_result_question (
                    id, exam_result_id, question_id, answer_id,
                    is_correct, score, max_score,
                    grading_method, grading_comment, confidence_score,
                    created_at, updated_at
                ) VALUES (
                    UUID_TO_BIN(UUID()), UUID_TO_BIN(%s), UUID_TO_BIN(%s), UUID_TO_BIN(%s),
                    %s, %s, %s, %s, %s, %s, %s, %s
                ) ON DUPLICATE KEY UPDATE
                    is_correct = VALUES(is_correct),
                    score = VALUES(score),
                    grading_method = VALUES(grading_method),
                    grading_comment = VALUES(grading_comment),
                    confidence_score = VALUES(confidence_score),
                    updated_at = VALUES(updated_at)
                """

                try:
                    await cursor.execute(
                        query,
                        (
                            str(result_id),
                            str(question_result.question_id),
                            str(question_result.answer_id),
                            question_result.is_correct,
                            question_result.score,
                            question_result.max_score,
                            question_result.grading_method.value,
                            question_result.scoring_comment,
                            question_result.confidence_score,
                            question_result.created_at,
                            datetime.now(),
                        ),
                    )

                    await conn.commit()

                    logger.info(
                        "문제별 채점 결과 저장 성공",
                        result_id=str(result_id),
                        question_id=str(question_result.question_id),
                    )
                    return True

                except Exception as e:
                    logger.error(
                        "문제별 채점 결과 저장 실패",
                        result_id=str(result_id),
                        question_id=str(question_result.question_id),
                        error=str(e),
                    )
                    await conn.rollback()
                    return False

    async def create_exam_result(
        self, submission_id: UUID, exam_sheet_id: UUID, status: str = "PENDING"
    ) -> UUID:
        """
        시험 결과 레코드 생성 (채점 전 상태)

        Args:
            submission_id: 제출 ID
            exam_sheet_id: 시험지 ID
            status: 초기 상태 (기본값: PENDING)

        Returns:
            UUID: 생성된 exam_result ID
        """
        from app.utils.uuid_utils import generate_uuidv7

        result_id = generate_uuidv7()
        pool = await self.connection.get_pool()

        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                query = """
                INSERT INTO exam_result 
                (id, submission_id, exam_sheet_id, graded_at, total_score, status, version)
                VALUES (UUID_TO_BIN(%s), UUID_TO_BIN(%s), UUID_TO_BIN(%s), NOW(), 0, %s, 1)
                """

                await cursor.execute(
                    query,
                    (str(result_id), str(submission_id), str(exam_sheet_id), status),
                )
                await conn.commit()

                logger.info(
                    "시험 결과 레코드 생성 완료",
                    result_id=str(result_id),
                    submission_id=str(submission_id),
                    status=status,
                )

                return result_id
