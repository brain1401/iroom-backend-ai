-- campus_25SW_FS_p3_4.admin definition

CREATE TABLE `admin` (
    `username` varchar(50) NOT NULL COMMENT '관리자 로그인 아이디 (예: admin)',
    `password` varchar(255) NOT NULL COMMENT '암호화된 비밀번호 (BCrypt로 암호화)',
    `academy_name` varchar(100) DEFAULT '이룸클래스' COMMENT '학원 이름',
    `id` binary(16) NOT NULL,
    `email` varchar(100) DEFAULT NULL,
    `name` varchar(50) DEFAULT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `username` (`username`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '관리자 정보 테이블';

-- campus_25SW_FS_p3_4.exam_sheet definition

CREATE TABLE `exam_sheet` (
    `exam_name` varchar(100) NOT NULL,
    `grade` int NOT NULL,
    `total_questions` int NOT NULL,
    `multiple_choice_count` int NOT NULL DEFAULT '0' COMMENT '객관식 문제 개수',
    `subjective_count` int NOT NULL DEFAULT '0' COMMENT '주관식 문제 개수',
    `created_at` datetime(6) NOT NULL,
    `updated_at` datetime(6) NOT NULL,
    `id` binary(16) NOT NULL,
    PRIMARY KEY (`id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '시험지';

-- campus_25SW_FS_p3_4.student definition

CREATE TABLE `student` (
    `id` binary(16) NOT NULL,
    `birth_date` date NOT NULL,
    `grade` int NOT NULL,
    `name` varchar(50) NOT NULL,
    `phone` varchar(20) DEFAULT NULL,
    PRIMARY KEY (`id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '학생';

-- campus_25SW_FS_p3_4.unit_category definition

CREATE TABLE `unit_category` (
    `category_name` varchar(50) NOT NULL COMMENT '대분류 이름 (예: 수와 연산, 문자와 식, 함수, 기하, 통계와 확률)',
    `display_order` int NOT NULL COMMENT '화면에 표시할 순서 (1, 2, 3, 4, 5)',
    `description` varchar(200) DEFAULT NULL COMMENT '대분류에 대한 설명',
    `id` binary(16) NOT NULL,
    PRIMARY KEY (`id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '단원 대분류 테이블';

-- campus_25SW_FS_p3_4.exam definition

CREATE TABLE `exam` (
    `exam_name` varchar(100) NOT NULL COMMENT '시험명 (시험지명과 동일)',
    `grade` int NOT NULL COMMENT '학년 (1, 2, 3학년)',
    `content` text COMMENT '시험 관련 메모/설명',
    `student_count` int NOT NULL COMMENT '학생 수 (시험 등록 시 입력)',
    `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '등록일시',
    `qr_code_url` longtext,
    `id` binary(16) NOT NULL,
    `exam_sheet_id` binary(16) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `fk_exam_exam_sheet` (`exam_sheet_id`),
    CONSTRAINT `fk_exam_exam_sheet` FOREIGN KEY (`exam_sheet_id`) REFERENCES `exam_sheet` (`id`) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '시험 정보 테이블';

-- campus_25SW_FS_p3_4.exam_document definition

CREATE TABLE `exam_document` (
    `document_type` enum(
        'STUDENT_ANSWER_SHEET',
        'EXAM_SHEET',
        'CORRECT_ANSWER_SHEET'
    ) NOT NULL,
    `document_content` longtext NOT NULL COMMENT '문서 내용 (HTML 형태)',
    `qr_code_url` longtext,
    `id` binary(16) NOT NULL,
    `exam_sheet_id` binary(16) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `fk_exam_document_exam_sheet` (`exam_sheet_id`),
    CONSTRAINT `fk_exam_document_exam_sheet` FOREIGN KEY (`exam_sheet_id`) REFERENCES `exam_sheet` (`id`) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '시험지 문서 테이블';

-- campus_25SW_FS_p3_4.exam_submission definition

CREATE TABLE `exam_submission` (
    `submitted_at` datetime NOT NULL COMMENT '제출일시',
    `user_id` binary(16) NOT NULL,
    `id` binary(16) NOT NULL,
    `exam_id` binary(16) NOT NULL,
    `total_score` int DEFAULT NULL,
    PRIMARY KEY (`id`),
    KEY `fk_exam_submission_exam` (`exam_id`),
    KEY `FKim21od386wva312nbhqver4av` (`user_id`),
    CONSTRAINT `fk_exam_submission_exam` FOREIGN KEY (`exam_id`) REFERENCES `exam` (`id`) ON DELETE CASCADE,
    CONSTRAINT `FKim21od386wva312nbhqver4av` FOREIGN KEY (`user_id`) REFERENCES `student` (`id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '시험 제출 기록 테이블 (순수 제출 정보만)';

-- campus_25SW_FS_p3_4.unit_subcategory definition

CREATE TABLE `unit_subcategory` (
    `subcategory_name` varchar(100) NOT NULL COMMENT '중분류 이름 (예: 정수와 유리수, 문자와 식, 방정식, 부등식)',
    `display_order` int NOT NULL COMMENT '같은 대분류 내에서 표시할 순서',
    `description` varchar(200) DEFAULT NULL COMMENT '중분류에 대한 설명',
    `id` binary(16) NOT NULL,
    `category_id` binary(16) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `idx_display_order` (`display_order`),
    KEY `fk_unit_subcategory_category` (`category_id`),
    CONSTRAINT `fk_unit_subcategory_category` FOREIGN KEY (`category_id`) REFERENCES `unit_category` (`id`) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '단원 중분류 테이블';

-- campus_25SW_FS_p3_4.exam_result definition

CREATE TABLE `exam_result` (
    `id` binary(16) NOT NULL,
    `submission_id` binary(16) NOT NULL,
    `graded_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `total_score` int DEFAULT NULL COMMENT '총점',
    `status` enum(
        'PENDING',
        'IN_PROGRESS',
        'COMPLETED',
        'REGRADED'
    ) NOT NULL DEFAULT 'PENDING',
    `grading_comment` text COMMENT '채점 코멘트',
    `version` int NOT NULL DEFAULT '1' COMMENT '재채점 버전 관리',
    `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    `exam_sheet_id` binary(16) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `idx_submission_version` (`submission_id`, `version`),
    KEY `idx_graded_at` (`graded_at`),
    KEY `idx_status` (`status`),
    KEY `FK1kxnkym7yfaed68mx1p9nujeb` (`exam_sheet_id`),
    CONSTRAINT `exam_result_ibfk_1` FOREIGN KEY (`submission_id`) REFERENCES `exam_submission` (`id`) ON DELETE CASCADE,
    CONSTRAINT `FK1kxnkym7yfaed68mx1p9nujeb` FOREIGN KEY (`exam_sheet_id`) REFERENCES `exam_sheet` (`id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '시험 결과 테이블 - 제출물에 대한 전체 채점 정보';

-- campus_25SW_FS_p3_4.unit definition

CREATE TABLE `unit` (
    `grade` int NOT NULL COMMENT '몇 학년인지 (1, 2, 3학년)',
    `unit_name` varchar(100) NOT NULL COMMENT '세부단원 이름 (예: 정수, 유리수, 일차방정식, 이차방정식)',
    `unit_code` varchar(30) NOT NULL COMMENT '단원을 구분하는 고유 코드 (예: MS1_NUM_INT, MS2_ALG_LINEAR)',
    `description` text COMMENT '단원 설명',
    `display_order` int NOT NULL COMMENT '같은 중분류 내에서 표시할 순서',
    `id` binary(16) NOT NULL,
    `subcategory_id` binary(16) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `unit_code` (`unit_code`),
    KEY `idx_grade` (`grade`),
    KEY `idx_unit_code` (`unit_code`),
    KEY `idx_display_order` (`display_order`),
    KEY `fk_unit_subcategory` (`subcategory_id`),
    CONSTRAINT `fk_unit_subcategory` FOREIGN KEY (`subcategory_id`) REFERENCES `unit_subcategory` (`id`) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '세부단원 테이블';

-- campus_25SW_FS_p3_4.exam_sheet_selected_unit definition

CREATE TABLE `exam_sheet_selected_unit` (
    `id` binary(16) NOT NULL,
    `exam_sheet_id` binary(16) NOT NULL,
    `unit_id` binary(16) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `fk_exam_sheet_selected_unit_exam_sheet` (`exam_sheet_id`),
    KEY `fk_exam_sheet_selected_unit_unit` (`unit_id`),
    CONSTRAINT `fk_exam_sheet_selected_unit_exam_sheet` FOREIGN KEY (`exam_sheet_id`) REFERENCES `exam_sheet` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_exam_sheet_selected_unit_unit` FOREIGN KEY (`unit_id`) REFERENCES `unit` (`id`) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '시험지에 선택된 단원들 테이블';

-- campus_25SW_FS_p3_4.question definition

CREATE TABLE `question` (
    `difficulty` enum('하', '중', '상') NOT NULL COMMENT '문제 난이도 (하: 쉬움, 중: 보통, 상: 어려움)',
    `question_text` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '문제의 텍스트',
    `answer_text` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '주관식 문제 답',
    `image` json DEFAULT(_utf8mb4 '{"images": []}') COMMENT '이미지 url을 담는 json 배열',
    `points` int NOT NULL COMMENT '배점',
    `choices` json DEFAULT NULL COMMENT '문제 객관식 선택지',
    `correct_choice` int DEFAULT NULL COMMENT '객관식 정답 id',
    `question_type` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL DEFAULT 'SUBJECTIVE' COMMENT '객관식, 주관식 정답 여부',
    `id` binary(16) NOT NULL COMMENT 'PK',
    `unit_id` binary(16) NOT NULL COMMENT '단원 id',
    `scoring_rubric` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '채점 기준 텍스트',
    PRIMARY KEY (`id`),
    KEY `fk_question_unit` (`unit_id`),
    CONSTRAINT `fk_question_unit` FOREIGN KEY (`unit_id`) REFERENCES `unit` (`id`) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '문제 정보 테이블';

-- campus_25SW_FS_p3_4.student_answer_sheet definition

CREATE TABLE `student_answer_sheet` (
    `answer_image_url` varchar(500) DEFAULT NULL,
    `answer_text` varchar(1000) DEFAULT NULL,
    `selected_choice` int DEFAULT NULL,
    `ai_solution_process` text COMMENT 'AI가 추출한 답안 풀이 과정 (주관식용)',
    `id` binary(16) NOT NULL,
    `submission_id` binary(16) NOT NULL,
    `question_id` binary(16) NOT NULL,
    `is_correct` bit(1) DEFAULT NULL,
    `score` int DEFAULT NULL,
    PRIMARY KEY (`id`),
    KEY `fk_exam_answer_submission` (`submission_id`),
    KEY `fk_exam_answer_question` (`question_id`),
    CONSTRAINT `fk_exam_answer_question` FOREIGN KEY (`question_id`) REFERENCES `question` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_exam_answer_submission` FOREIGN KEY (`submission_id`) REFERENCES `exam_submission` (`id`) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '시험 답안 테이블 (순수 답안 정보만)';

-- campus_25SW_FS_p3_4.exam_result_question definition

CREATE TABLE `exam_result_question` (
    `id` binary(16) NOT NULL,
    `confidence_score` decimal(3, 2) DEFAULT NULL,
    `created_at` datetime(6) NOT NULL,
    `grading_comment` text,
    `grading_method` enum(
        'AI_ASSISTED',
        'AUTO',
        'MANUAL'
    ) NOT NULL,
    `is_correct` bit(1) DEFAULT NULL,
    `max_score` int NOT NULL,
    `score` int DEFAULT NULL,
    `updated_at` datetime(6) NOT NULL,
    `answer_id` binary(16) NOT NULL,
    `exam_result_id` binary(16) NOT NULL,
    `question_id` binary(16) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `FK5aqnya5vgl4c2nwvpv0ornhdu` (`exam_result_id`),
    KEY `FKsbejvkmejga9gx8m6hdidiox5` (`question_id`),
    KEY `fk_exam_result_question_student_answer_sheet` (`answer_id`),
    CONSTRAINT `FK5aqnya5vgl4c2nwvpv0ornhdu` FOREIGN KEY (`exam_result_id`) REFERENCES `exam_result` (`id`),
    CONSTRAINT `fk_exam_result_question_student_answer_sheet` FOREIGN KEY (`answer_id`) REFERENCES `student_answer_sheet` (`id`),
    CONSTRAINT `FKsbejvkmejga9gx8m6hdidiox5` FOREIGN KEY (`question_id`) REFERENCES `question` (`id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '시험 결과의 각 문제';

-- campus_25SW_FS_p3_4.exam_sheet_question definition

CREATE TABLE `exam_sheet_question` (
    `points` int NOT NULL,
    `seq_no` int NOT NULL,
    `question_order` int NOT NULL DEFAULT '1' COMMENT '문제 출제 순서 (학생에게 보여지는 순서)',
    `selection_method` varchar(255) NOT NULL DEFAULT 'MANUAL' COMMENT '문제 선택 방식 (RANDOM/MANUAL)',
    `id` binary(16) NOT NULL,
    `exam_sheet_id` binary(16) NOT NULL,
    `question_id` binary(16) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `fk_exam_sheet_question_exam_sheet` (`exam_sheet_id`),
    KEY `fk_exam_sheet_question_question` (`question_id`),
    CONSTRAINT `fk_exam_sheet_question_exam_sheet` FOREIGN KEY (`exam_sheet_id`) REFERENCES `exam_sheet` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_exam_sheet_question_question` FOREIGN KEY (`question_id`) REFERENCES `question` (`id`) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '시험지 안의 문제';

-- campus_25SW_FS_p3_4.question_result definition

CREATE TABLE `question_result` (
    `id` binary(16) NOT NULL,
    `exam_result_id` binary(16) NOT NULL,
    `question_id` binary(16) NOT NULL,
    `answer_id` binary(16) NOT NULL COMMENT '해당 답안 ID',
    `is_correct` tinyint(1) DEFAULT NULL COMMENT '정답 여부',
    `score` int DEFAULT NULL COMMENT '획득 점수',
    `max_score` int NOT NULL COMMENT '문제 배점 (question.points에서 복사)',
    `grading_method` enum(
        'AUTO',
        'MANUAL',
        'AI_ASSISTED'
    ) NOT NULL DEFAULT 'AUTO',
    `grading_comment` text COMMENT '채점 코멘트/피드백',
    `confidence_score` decimal(3, 2) DEFAULT NULL COMMENT 'AI 채점 신뢰도 (0.00-1.00)',
    `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_exam_result_id` (`exam_result_id`),
    KEY `idx_question_id` (`question_id`),
    KEY `idx_answer_id` (`answer_id`),
    KEY `idx_grading_method` (`grading_method`),
    CONSTRAINT `fk_question_result_student_answer_sheet` FOREIGN KEY (`answer_id`) REFERENCES `student_answer_sheet` (`id`),
    CONSTRAINT `question_result_ibfk_1` FOREIGN KEY (`exam_result_id`) REFERENCES `exam_result` (`id`) ON DELETE CASCADE,
    CONSTRAINT `question_result_ibfk_2` FOREIGN KEY (`question_id`) REFERENCES `question` (`id`) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '문제별 채점 결과 테이블 - 각 문제에 대한 상세 채점 정보';