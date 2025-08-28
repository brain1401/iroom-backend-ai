#!/usr/bin/env python3
"""
글자 인식 반복 테스트 스크립트

시험 이미지(exam1.jpg)에 대한 반복적인 글자 인식 테스트 수행

주요 기능:
- 반복 테스트 실행 및 결과 수집
- 정확도 및 일관성 분석
- 예상 답안과 비교
- 성능 메트릭 수집
- 오류 패턴 분석
"""

import asyncio
import time
import json
import statistics
from pathlib import Path
from typing import Dict, List, Any
from dataclasses import dataclass, asdict

import httpx
import structlog
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

# 로깅 설정
logger = structlog.get_logger("text_recognition_test")
console = Console()

# 예상 정답 (Ground Truth)
EXPECTED_ANSWERS = [
    {"question_number": 1, "question_label": "주1", "expected_text": "19.38"},
    {"question_number": 2, "question_label": "주2", "expected_text": "√2/√3"},
    {"question_number": 3, "question_label": "주3", "expected_text": "3∛6"},
    {"question_number": 4, "question_label": "주4", "expected_text": "3°"},
    {"question_number": 5, "question_label": "주5", "expected_text": "5/3<m²"},
    {"question_number": 6, "question_label": "주6", "expected_text": "√6×9/3"},
    {"question_number": 7, "question_label": "주7", "expected_text": "4ab"},
]

@dataclass
class TestResult:
    """테스트 결과 데이터 클래스"""
    attempt: int
    success: bool
    processing_time_ms: int
    answers_count: int
    accuracy_score: float
    answers: List[Dict[str, Any]]
    error_message: str = ""
    

class TextRecognitionTester:
    """글자 인식 반복 테스트 클래스"""
    
    def __init__(self, base_url: str = "http://localhost:8000", image_path: str = "tests/data/images/exam1.jpg"):
        self.base_url = base_url
        self.image_path = Path(image_path)
        self.endpoint = f"{base_url}/text-recognition/answer-sheet"
        self.results: List[TestResult] = []
        
    def calculate_accuracy_score(self, actual_answers: List[Dict]) -> float:
        """
        정확도 점수 계산
        
        Args:
            actual_answers: 실제 인식된 답안 리스트
            
        Returns:
            float: 정확도 점수 (0.0-1.0)
        """
        if not actual_answers:
            return 0.0
            
        total_score = 0.0
        total_questions = len(EXPECTED_ANSWERS)
        
        # 각 예상 답안에 대해 매칭 확인
        for expected in EXPECTED_ANSWERS:
            best_match_score = 0.0
            
            for actual in actual_answers:
                # 문제 번호가 일치하는지 확인
                if actual.get("question_number") == expected["question_number"]:
                    # 텍스트 유사도 계산 (간단한 방식)
                    expected_text = expected["expected_text"].lower().replace(" ", "")
                    actual_text = actual.get("extracted_text", "").lower().replace(" ", "")
                    
                    if expected_text == actual_text:
                        best_match_score = 1.0  # 완전 일치
                    elif actual_text in expected_text or expected_text in actual_text:
                        best_match_score = 0.7  # 부분 일치
                    elif len(actual_text) > 0:
                        best_match_score = 0.3  # 텍스트가 인식되었지만 다름
                    break
            
            total_score += best_match_score
        
        return total_score / total_questions
    
    async def perform_single_test(self, attempt: int, use_cache: bool = False) -> TestResult:
        """
        단일 테스트 수행
        
        Args:
            attempt: 시도 번호
            use_cache: 캐시 사용 여부
            
        Returns:
            TestResult: 테스트 결과
        """
        start_time = time.time()
        
        try:
            # 이미지 파일 읽기
            if not self.image_path.exists():
                raise FileNotFoundError(f"테스트 이미지를 찾을 수 없습니다: {self.image_path}")
                
            with open(self.image_path, "rb") as f:
                image_data = f.read()
            
            # HTTP 요청 전송
            async with httpx.AsyncClient(timeout=60.0) as client:
                files = {"file": ("exam1.jpg", image_data, "image/jpeg")}
                params = {"use_cache": use_cache}
                
                response = await client.post(
                    self.endpoint,
                    files=files,
                    params=params
                )
                
                processing_time_ms = int((time.time() - start_time) * 1000)
                
                if response.status_code == 200:
                    result_data = response.json()
                    answers = result_data.get("answers", [])
                    accuracy_score = self.calculate_accuracy_score(answers)
                    
                    return TestResult(
                        attempt=attempt,
                        success=True,
                        processing_time_ms=processing_time_ms,
                        answers_count=len(answers),
                        accuracy_score=accuracy_score,
                        answers=answers
                    )
                else:
                    error_msg = f"HTTP {response.status_code}: {response.text}"
                    logger.error("API 요청 실패", 
                               attempt=attempt, 
                               status_code=response.status_code,
                               error=error_msg)
                    
                    return TestResult(
                        attempt=attempt,
                        success=False,
                        processing_time_ms=processing_time_ms,
                        answers_count=0,
                        accuracy_score=0.0,
                        answers=[],
                        error_message=error_msg
                    )
                    
        except Exception as e:
            processing_time_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)
            
            logger.error("테스트 수행 중 오류", 
                       attempt=attempt, 
                       error=error_msg)
            
            return TestResult(
                attempt=attempt,
                success=False,
                processing_time_ms=processing_time_ms,
                answers_count=0,
                accuracy_score=0.0,
                answers=[],
                error_message=error_msg
            )
    
    async def run_repeated_tests(self, num_tests: int = 5, use_cache: bool = False) -> List[TestResult]:
        """
        반복 테스트 실행
        
        Args:
            num_tests: 테스트 횟수
            use_cache: 캐시 사용 여부
            
        Returns:
            List[TestResult]: 테스트 결과 리스트
        """
        console.print(f"\n🧪 [bold blue]글자 인식 반복 테스트 시작[/bold blue]")
        console.print(f"📊 테스트 횟수: {num_tests}회")
        console.print(f"📁 이미지 경로: {self.image_path}")
        console.print(f"🔗 API 엔드포인트: {self.endpoint}")
        console.print(f"💾 캐시 사용: {'예' if use_cache else '아니오'}")
        console.print()
        
        results = []
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("테스트 진행 중...", total=num_tests)
            
            for i in range(1, num_tests + 1):
                progress.update(task, description=f"테스트 {i}/{num_tests} 수행 중...")
                
                # 캐시 방지를 위한 약간의 딜레이 (첫 번째 테스트 제외)
                if i > 1 and not use_cache:
                    await asyncio.sleep(0.5)
                
                result = await self.perform_single_test(i, use_cache)
                results.append(result)
                
                # 진행 상황 로깅
                if result.success:
                    console.print(f"  ✅ 테스트 {i}: 성공 (정확도: {result.accuracy_score:.2%}, {result.processing_time_ms}ms)")
                else:
                    console.print(f"  ❌ 테스트 {i}: 실패 - {result.error_message}")
                
                progress.advance(task)
        
        self.results = results
        return results
    
    def analyze_results(self) -> Dict[str, Any]:
        """
        테스트 결과 분석
        
        Returns:
            Dict[str, Any]: 분석 결과
        """
        if not self.results:
            return {"error": "테스트 결과가 없습니다."}
        
        successful_tests = [r for r in self.results if r.success]
        failed_tests = [r for r in self.results if not r.success]
        
        # 기본 통계
        total_tests = len(self.results)
        success_rate = len(successful_tests) / total_tests if total_tests > 0 else 0
        
        analysis = {
            "summary": {
                "total_tests": total_tests,
                "successful_tests": len(successful_tests),
                "failed_tests": len(failed_tests),
                "success_rate": success_rate,
            }
        }
        
        # 성공한 테스트들 분석
        if successful_tests:
            processing_times = [r.processing_time_ms for r in successful_tests]
            accuracy_scores = [r.accuracy_score for r in successful_tests]
            answers_counts = [r.answers_count for r in successful_tests]
            
            analysis["performance"] = {
                "avg_processing_time_ms": statistics.mean(processing_times),
                "min_processing_time_ms": min(processing_times),
                "max_processing_time_ms": max(processing_times),
                "median_processing_time_ms": statistics.median(processing_times),
                "std_processing_time_ms": statistics.stdev(processing_times) if len(processing_times) > 1 else 0,
            }
            
            analysis["accuracy"] = {
                "avg_accuracy_score": statistics.mean(accuracy_scores),
                "min_accuracy_score": min(accuracy_scores),
                "max_accuracy_score": max(accuracy_scores),
                "median_accuracy_score": statistics.median(accuracy_scores),
                "std_accuracy_score": statistics.stdev(accuracy_scores) if len(accuracy_scores) > 1 else 0,
            }
            
            analysis["detection"] = {
                "avg_answers_detected": statistics.mean(answers_counts),
                "min_answers_detected": min(answers_counts),
                "max_answers_detected": max(answers_counts),
                "expected_answers": len(EXPECTED_ANSWERS),
            }
            
            # 가장 정확한 결과 저장
            best_result = max(successful_tests, key=lambda x: x.accuracy_score)
            analysis["best_result"] = asdict(best_result)
        
        # 실패한 테스트들 분석
        if failed_tests:
            error_patterns = {}
            for test in failed_tests:
                error_key = test.error_message.split(":")[0] if ":" in test.error_message else test.error_message
                error_patterns[error_key] = error_patterns.get(error_key, 0) + 1
            
            analysis["failures"] = {
                "error_patterns": error_patterns,
                "failure_details": [{"attempt": r.attempt, "error": r.error_message} for r in failed_tests]
            }
        
        return analysis
    
    def print_detailed_results(self):
        """상세 결과 출력"""
        if not self.results:
            console.print("❌ 테스트 결과가 없습니다.")
            return
        
        analysis = self.analyze_results()
        
        # 요약 테이블
        console.print("\n📊 [bold]테스트 결과 요약[/bold]")
        summary_table = Table()
        summary_table.add_column("항목", style="cyan")
        summary_table.add_column("값", style="magenta")
        
        summary = analysis["summary"]
        summary_table.add_row("총 테스트 수", str(summary["total_tests"]))
        summary_table.add_row("성공", f"{summary['successful_tests']} ({summary['success_rate']:.1%})")
        summary_table.add_row("실패", str(summary["failed_tests"]))
        
        console.print(summary_table)
        
        # 성능 분석
        if "performance" in analysis:
            console.print("\n⚡ [bold]성능 분석[/bold]")
            perf_table = Table()
            perf_table.add_column("메트릭", style="cyan")
            perf_table.add_column("값", style="magenta")
            
            perf = analysis["performance"]
            perf_table.add_row("평균 처리 시간", f"{perf['avg_processing_time_ms']:.1f}ms")
            perf_table.add_row("최소 처리 시간", f"{perf['min_processing_time_ms']}ms")
            perf_table.add_row("최대 처리 시간", f"{perf['max_processing_time_ms']}ms")
            perf_table.add_row("처리 시간 편차", f"{perf['std_processing_time_ms']:.1f}ms")
            
            console.print(perf_table)
        
        # 정확도 분석
        if "accuracy" in analysis:
            console.print("\n🎯 [bold]정확도 분석[/bold]")
            acc_table = Table()
            acc_table.add_column("메트릭", style="cyan")
            acc_table.add_column("값", style="magenta")
            
            acc = analysis["accuracy"]
            acc_table.add_row("평균 정확도", f"{acc['avg_accuracy_score']:.1%}")
            acc_table.add_row("최소 정확도", f"{acc['min_accuracy_score']:.1%}")
            acc_table.add_row("최대 정확도", f"{acc['max_accuracy_score']:.1%}")
            acc_table.add_row("정확도 편차", f"{acc['std_accuracy_score']:.1%}")
            
            console.print(acc_table)
        
        # 최고 결과 세부사항
        if "best_result" in analysis:
            console.print("\n🏆 [bold]최고 성능 결과 상세[/bold]")
            best = analysis["best_result"]
            
            console.print(f"• 시도 번호: {best['attempt']}")
            console.print(f"• 정확도: {best['accuracy_score']:.1%}")
            console.print(f"• 처리 시간: {best['processing_time_ms']}ms")
            console.print(f"• 감지된 답안 수: {best['answers_count']}/{len(EXPECTED_ANSWERS)}")
            
            if best['answers']:
                console.print("\n📝 [bold]감지된 답안들:[/bold]")
                for i, answer in enumerate(best['answers'], 1):
                    expected = EXPECTED_ANSWERS[i-1] if i <= len(EXPECTED_ANSWERS) else None
                    status = "✅" if expected and answer.get("extracted_text", "").lower().replace(" ", "") == expected["expected_text"].lower().replace(" ", "") else "❌"
                    console.print(f"  {status} {answer.get('question_label', 'N/A')}: '{answer.get('extracted_text', 'N/A')}' (신뢰도: {answer.get('confidence', 0):.2f})")
                
                console.print("\n📋 [bold]예상 답안과 비교:[/bold]")
                for expected in EXPECTED_ANSWERS:
                    console.print(f"  • {expected['question_label']}: '{expected['expected_text']}'")
        
        # 실패 분석
        if "failures" in analysis:
            console.print("\n❌ [bold]실패 분석[/bold]")
            failures = analysis["failures"]
            
            console.print("오류 패턴:")
            for error, count in failures["error_patterns"].items():
                console.print(f"  • {error}: {count}회")


async def main():
    """메인 실행 함수"""
    # 테스트 설정
    NUM_TESTS = 3  # 테스트 횟수 (3회로 설정)
    USE_CACHE = False  # 캐시 비활성화로 실제 인식 성능 측정
    
    # 테스터 초기화
    tester = TextRecognitionTester()
    
    try:
        # 서버 상태 확인
        console.print("🔍 [bold]서버 연결 상태 확인[/bold]")
        async with httpx.AsyncClient(timeout=10.0) as client:
            health_response = await client.get(f"{tester.base_url}/health")
            if health_response.status_code == 200:
                console.print("✅ 서버 연결 성공")
            else:
                console.print(f"⚠️ 서버 응답 이상: {health_response.status_code}")
    
    except Exception as e:
        console.print(f"❌ 서버 연결 실패: {e}")
        console.print("\n💡 서버를 먼저 실행해주세요:")
        console.print("   uv run dev")
        return
    
    try:
        # 반복 테스트 실행
        results = await tester.run_repeated_tests(num_tests=NUM_TESTS, use_cache=USE_CACHE)
        
        # 결과 분석 및 출력
        tester.print_detailed_results()
        
        # JSON 형태로 저장 (선택사항)
        analysis = tester.analyze_results()
        output_file = "tests/results/current/text_recognition_test_results.json"
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump({
                "test_config": {
                    "num_tests": NUM_TESTS,
                    "use_cache": USE_CACHE,
                    "image_path": str(tester.image_path),
                    "endpoint": tester.endpoint,
                    "expected_answers": EXPECTED_ANSWERS
                },
                "raw_results": [asdict(r) for r in results],
                "analysis": analysis
            }, f, ensure_ascii=False, indent=2)
        
        console.print(f"\n💾 상세 결과가 {output_file}에 저장되었습니다.")
        
    except KeyboardInterrupt:
        console.print("\n⛔ 사용자에 의해 테스트가 중단되었습니다.")
    except Exception as e:
        console.print(f"\n❌ 테스트 실행 중 오류: {e}")
        logger.exception("테스트 실행 오류")


if __name__ == "__main__":
    asyncio.run(main())