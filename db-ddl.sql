-- campus_25SW_FS_p3_4.exam_sheet definition

CREATE TABLE `exam_sheet` (
    `exam_name` varchar(100) NOT NULL,
    `grade` int NOT NULL,
    `total_questions` int DEFAULT '0',
    `multiple_choice_count` int NOT NULL DEFAULT '0' COMMENT '객관식 문제 개수',
    `subjective_count` int NOT NULL DEFAULT '0' COMMENT '주관식 문제 개수',
    `created_at` datetime(6) NOT NULL,
    `updated_at` datetime(6) NOT NULL,
    `id` binary(16) NOT NULL,
    PRIMARY KEY (`id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '시험지';

-- campus_25SW_FS_p3_4.student definition

CREATE TABLE `student` (
    `id` bigint NOT NULL AUTO_INCREMENT,
    `birth_date` date DEFAULT '2010-01-01',
    `created_at` datetime(6) DEFAULT NULL,
    `name` varchar(50) NOT NULL,
    `phone` varchar(20) NOT NULL,
    `updated_at` datetime(6) DEFAULT NULL,
    PRIMARY KEY (`id`)
) ENGINE = InnoDB AUTO_INCREMENT = 127 DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '학생';

-- campus_25SW_FS_p3_4.teacher definition

CREATE TABLE `teacher` (
    `created_at` datetime(6) DEFAULT NULL,
    `id` bigint NOT NULL AUTO_INCREMENT,
    `updated_at` datetime(6) DEFAULT NULL,
    `username` varchar(50) NOT NULL,
    `password` varchar(100) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `UK977gims1kvtfisrbhq4e3g23j` (`username`)
) ENGINE = InnoDB AUTO_INCREMENT = 11 DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

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
    `student_count` int DEFAULT '0',
    `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '등록일시',
    `qr_code_url` longtext,
    `id` binary(16) NOT NULL,
    `exam_sheet_id` binary(16) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `FKslua7xmmjqpru9m6c0krepsbv` (`exam_sheet_id`),
    CONSTRAINT `fk_exam_exam_sheet` FOREIGN KEY (`exam_sheet_id`) REFERENCES `exam_sheet` (`id`) ON DELETE CASCADE,
    CONSTRAINT `FKslua7xmmjqpru9m6c0krepsbv` FOREIGN KEY (`exam_sheet_id`) REFERENCES `exam_sheet` (`id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '시험 정보 테이블';

-- campus_25SW_FS_p3_4.exam_document definition

CREATE TABLE `exam_document` (
    `exam_sheet_id` binary(16) NOT NULL,
    `id` binary(16) NOT NULL,
    `document_content` longtext NOT NULL,
    `qr_code_url` longtext,
    `document_type` enum(
        'CORRECT_ANSWER_SHEET',
        'EXAM_SHEET',
        'STUDENT_ANSWER_SHEET'
    ) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `FKnx1cqh8l78dxanvxg0bef7ga6` (`exam_sheet_id`),
    CONSTRAINT `FKnx1cqh8l78dxanvxg0bef7ga6` FOREIGN KEY (`exam_sheet_id`) REFERENCES `exam_sheet` (`id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- campus_25SW_FS_p3_4.exam_submission definition

CREATE TABLE `exam_submission` (
    `submitted_at` datetime DEFAULT CURRENT_TIMESTAMP,
    `id` binary(16) NOT NULL,
    `exam_id` binary(16) NOT NULL,
    `student_id` bigint NOT NULL,
    PRIMARY KEY (`id`),
    KEY `FKhpbxc166py57lqe75pkrbw4b5` (`exam_id`),
    KEY `FKbt7lphrrlltk67qk87j2sldlw` (`student_id`),
    CONSTRAINT `fk_exam_submission_exam` FOREIGN KEY (`exam_id`) REFERENCES `exam` (`id`) ON DELETE CASCADE,
    CONSTRAINT `FK_exam_submission_student` FOREIGN KEY (`student_id`) REFERENCES `student` (`id`),
    CONSTRAINT `FKbt7lphrrlltk67qk87j2sldlw` FOREIGN KEY (`student_id`) REFERENCES `student` (`id`),
    CONSTRAINT `FKhpbxc166py57lqe75pkrbw4b5` FOREIGN KEY (`exam_id`) REFERENCES `exam` (`id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '시험 제출 기록 테이블 (순수 제출 정보만)';

-- campus_25SW_FS_p3_4.student_answer_sheet definition

CREATE TABLE `student_answer_sheet` (
    `id` binary(16) NOT NULL,
    `submission_id` binary(16) NOT NULL,
    `student_name` varchar(100) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `FK63r296id7mv5ydnla6anonx3b` (`submission_id`),
    CONSTRAINT `FK63r296id7mv5ydnla6anonx3b` FOREIGN KEY (`submission_id`) REFERENCES `exam_submission` (`id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- campus_25SW_FS_p3_4.unit_subcategory definition

CREATE TABLE `unit_subcategory` (
    `subcategory_name` varchar(100) NOT NULL COMMENT '중분류 이름 (예: 정수와 유리수, 문자와 식, 방정식, 부등식)',
    `display_order` int NOT NULL COMMENT '같은 대분류 내에서 표시할 순서',
    `description` varchar(200) DEFAULT NULL COMMENT '중분류에 대한 설명',
    `id` binary(16) NOT NULL,
    `category_id` binary(16) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `idx_display_order` (`display_order`),
    KEY `FKjjsoskeu940jdm1ahqgg7tmhn` (`category_id`),
    CONSTRAINT `fk_unit_subcategory_category` FOREIGN KEY (`category_id`) REFERENCES `unit_category` (`id`) ON DELETE CASCADE,
    CONSTRAINT `FKjjsoskeu940jdm1ahqgg7tmhn` FOREIGN KEY (`category_id`) REFERENCES `unit_category` (`id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '단원 중분류 테이블';

-- campus_25SW_FS_p3_4.exam_result definition

CREATE TABLE `exam_result` (
    `total_score` int DEFAULT NULL,
    `version` int NOT NULL,
    `created_at` datetime(6) NOT NULL,
    `graded_at` datetime(6) NOT NULL,
    `updated_at` datetime(6) NOT NULL,
    `exam_sheet_id` binary(16) NOT NULL,
    `id` binary(16) NOT NULL,
    `submission_id` binary(16) NOT NULL,
    `scoring_comment` text,
    `status` enum(
        'COMPLETED',
        'IN_PROGRESS',
        'PENDING',
        'REGRADED'
    ) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `FK1kxnkym7yfaed68mx1p9nujeb` (`exam_sheet_id`),
    KEY `FK5h2e7spb12bowlcpn9ni2iccg` (`submission_id`),
    CONSTRAINT `FK1kxnkym7yfaed68mx1p9nujeb` FOREIGN KEY (`exam_sheet_id`) REFERENCES `exam_sheet` (`id`),
    CONSTRAINT `FK5h2e7spb12bowlcpn9ni2iccg` FOREIGN KEY (`submission_id`) REFERENCES `exam_submission` (`id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

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
    UNIQUE KEY `UKucmfm6lhgvfm2hje0oy5w8hu` (`unit_code`),
    KEY `idx_grade` (`grade`),
    KEY `idx_unit_code` (`unit_code`),
    KEY `idx_display_order` (`display_order`),
    KEY `FKjkc14skpio53pwkriddt28c27` (`subcategory_id`),
    CONSTRAINT `fk_unit_subcategory` FOREIGN KEY (`subcategory_id`) REFERENCES `unit_subcategory` (`id`) ON DELETE CASCADE,
    CONSTRAINT `FKjkc14skpio53pwkriddt28c27` FOREIGN KEY (`subcategory_id`) REFERENCES `unit_subcategory` (`id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '세부단원 테이블';

-- campus_25SW_FS_p3_4.exam_sheet_selected_unit definition

CREATE TABLE `exam_sheet_selected_unit` (
    `exam_sheet_id` binary(16) NOT NULL,
    `id` binary(16) NOT NULL,
    `unit_id` binary(16) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `FK2xbjk8ujtgcok7pm4ddrmn0ak` (`exam_sheet_id`),
    KEY `FK42oxhmr6y5rnn12m7gf4cqcwf` (`unit_id`),
    CONSTRAINT `FK2xbjk8ujtgcok7pm4ddrmn0ak` FOREIGN KEY (`exam_sheet_id`) REFERENCES `exam_sheet` (`id`),
    CONSTRAINT `FK42oxhmr6y5rnn12m7gf4cqcwf` FOREIGN KEY (`unit_id`) REFERENCES `unit` (`id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- campus_25SW_FS_p3_4.question definition

CREATE TABLE `question` (
    `difficulty` enum('하', '중', '상') NOT NULL COMMENT '문제 난이도 (하: 쉬움, 중: 보통, 상: 어려움)',
    `question_text` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '문제의 텍스트',
    `answer_text` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '주관식 문제 답',
    `image` json DEFAULT(_utf8mb4 '{"images": []}') COMMENT '이미지 url을 담는 json 배열',
    `points` int NOT NULL COMMENT '배점',
    `choices` json DEFAULT NULL COMMENT '문제 객관식 선택지',
    `correct_choice` int DEFAULT NULL COMMENT '객관식 정답 id',
    `question_type` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL DEFAULT 'SUBJECTIVE' COMMENT '객관식, 주관식 정답 여부',
    `id` binary(16) NOT NULL COMMENT 'PK',
    `unit_id` binary(16) NOT NULL COMMENT '단원 id',
    `scoring_rubric` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '채점 기준 텍스트',
    PRIMARY KEY (`id`),
    KEY `FKs1tl5ukggla0y9dkixxfimpwx` (`unit_id`),
    CONSTRAINT `fk_question_unit` FOREIGN KEY (`unit_id`) REFERENCES `unit` (`id`) ON DELETE CASCADE,
    CONSTRAINT `FKs1tl5ukggla0y9dkixxfimpwx` FOREIGN KEY (`unit_id`) REFERENCES `unit` (`id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '문제 정보 테이블';

-- campus_25SW_FS_p3_4.student_answer_sheet_question definition

CREATE TABLE `student_answer_sheet_question` (
    `selected_choice` int DEFAULT NULL,
    `id` binary(16) NOT NULL,
    `question_id` binary(16) NOT NULL,
    `student_answer_sheet_id` binary(16) NOT NULL,
    `answer_image_url` varchar(500) DEFAULT NULL,
    `answer_text` varchar(1000) DEFAULT NULL,
    PRIMARY KEY (`id`),
    KEY `FKs7pp57bx8d9i9apfybh9w2910` (`question_id`),
    KEY `FKntiunhjdel22t2pqmlj8vp20l` (`student_answer_sheet_id`),
    CONSTRAINT `FKntiunhjdel22t2pqmlj8vp20l` FOREIGN KEY (`student_answer_sheet_id`) REFERENCES `student_answer_sheet` (`id`),
    CONSTRAINT `FKs7pp57bx8d9i9apfybh9w2910` FOREIGN KEY (`question_id`) REFERENCES `question` (`id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- campus_25SW_FS_p3_4.exam_result_question definition

CREATE TABLE `exam_result_question` (
    `confidence_score` decimal(3, 2) DEFAULT NULL,
    `is_correct` bit(1) DEFAULT NULL,
    `score` int DEFAULT NULL,
    `created_at` datetime(6) NOT NULL,
    `updated_at` datetime(6) NOT NULL,
    `answer_id` binary(16) NOT NULL,
    `exam_result_id` binary(16) NOT NULL,
    `id` binary(16) NOT NULL,
    `question_id` binary(16) NOT NULL,
    `scoring_comment` text,
    `scoring_method` enum(
        'AI_ASSISTED',
        'AUTO',
        'MANUAL'
    ) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `FK5aqnya5vgl4c2nwvpv0ornhdu` (`exam_result_id`),
    KEY `FKsbejvkmejga9gx8m6hdidiox5` (`question_id`),
    KEY `FKo6t3vrkoarst5p5wfnssw7ask` (`answer_id`),
    CONSTRAINT `FK5aqnya5vgl4c2nwvpv0ornhdu` FOREIGN KEY (`exam_result_id`) REFERENCES `exam_result` (`id`),
    CONSTRAINT `FKo6t3vrkoarst5p5wfnssw7ask` FOREIGN KEY (`answer_id`) REFERENCES `student_answer_sheet` (`id`),
    CONSTRAINT `FKsbejvkmejga9gx8m6hdidiox5` FOREIGN KEY (`question_id`) REFERENCES `question` (`id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- campus_25SW_FS_p3_4.exam_sheet_question definition

CREATE TABLE `exam_sheet_question` (
    `points` int NOT NULL,
    `seq_no` int NOT NULL,
    `exam_sheet_id` binary(16) NOT NULL,
    `id` binary(16) NOT NULL,
    `question_id` binary(16) NOT NULL,
    `selection_method` enum('MANUAL', 'RANDOM') NOT NULL,
    PRIMARY KEY (`id`),
    KEY `FKhhbpusdcfj01oogq0c4s3dfit` (`exam_sheet_id`),
    KEY `FKrd319pw6ublwiqxr5ojji75o4` (`question_id`),
    CONSTRAINT `FKhhbpusdcfj01oogq0c4s3dfit` FOREIGN KEY (`exam_sheet_id`) REFERENCES `exam_sheet` (`id`),
    CONSTRAINT `FKrd319pw6ublwiqxr5ojji75o4` FOREIGN KEY (`question_id`) REFERENCES `question` (`id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;