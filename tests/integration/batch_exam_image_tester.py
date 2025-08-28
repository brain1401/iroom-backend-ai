#!/usr/bin/env python3
"""
배치 시험 이미지 글자 인식 테스터

test_exam_image 폴더의 모든 exam*.jpg 파일들을 자동으로 찾아서
글자 인식 API 엔드포인트를 통해 테스트하고 결과를 수집하는 스크립트

주요 기능:
- 자동 이미지 파일 검색 및 배치 처리
- 비동기 HTTP 클라이언트를 통한 병렬 처리
- 실시간 진행 상황 표시 및 상세 로깅
- 포괄적인 결과 분석 및 리포팅
- JSON/CSV 형태 결과 저장
- 에러 처리 및 재시도 메커니즘
"""

import asyncio
import time
import json
import csv
from pathlib import Path
from typing import Dict, List, Any
from dataclasses import dataclass, asdict
from datetime import datetime

import httpx
import structlog
from rich.console import Console
from rich.table import Table
from rich.progress import (
    Progress, 
    SpinnerColumn, 
    TextColumn, 
    BarColumn, 
    TaskProgressColumn,
    TimeRemainingColumn
)
from rich.panel import Panel

# 로깅 설정
logger = structlog.get_logger("batch_exam_tester")
console = Console()

# 지원 이미지 형식
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# API 설정
DEFAULT_API_BASE_URL = "http://localhost:8000"
DEFAULT_ENDPOINT = "/text-recognition/answer-sheet"
DEFAULT_TIMEOUT = 60.0
MAX_RETRIES = 3
RETRY_DELAY = 1.0

@dataclass
class ImageTestResult:
    """개별 이미지 테스트 결과"""
    filename: str
    file_path: str
    file_size_kb: int
    success: bool
    processing_time_ms: int
    answers_detected: int
    answers: List[Dict[str, Any]]
    confidence_avg: float
    error_message: str = ""
    http_status_code: int = 0
    retry_count: int = 0
    timestamp: str = ""

@dataclass
class BatchTestSummary:
    """배치 테스트 결과 요약"""
    total_files: int
    successful_tests: int
    failed_tests: int
    success_rate: float
    total_processing_time_ms: int
    avg_processing_time_ms: float
    total_answers_detected: int
    avg_answers_per_image: float
    avg_confidence: float
    start_time: str
    end_time: str
    duration_seconds: float

class BatchExamImageTester:
    """배치 시험 이미지 글자 인식 테스터"""
    
    def __init__(
        self, 
        image_folder: str = "tests/data/images",
        api_base_url: str = DEFAULT_API_BASE_URL,
        endpoint: str = DEFAULT_ENDPOINT,
        max_concurrent: int = 3,
        timeout: float = DEFAULT_TIMEOUT
    ):
        """
        배치 테스터 초기화
        
        Args:
            image_folder: 테스트할 이미지들이 있는 폴더 경로
            api_base_url: API 서버 기본 URL
            endpoint: 글자 인식 엔드포인트 경로
            max_concurrent: 최대 동시 처리 수
            timeout: HTTP 요청 타임아웃 (초)
        """
        self.image_folder = Path(image_folder)
        self.api_base_url = api_base_url
        self.endpoint = endpoint
        self.full_endpoint_url = f"{api_base_url.rstrip('/')}{endpoint}"
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        
        # 결과 저장
        self.test_results: List[ImageTestResult] = []
        self.semaphore = asyncio.Semaphore(max_concurrent)
        
    def discover_exam_images(self) -> List[Path]:
        """
        exam*.* 패턴의 이미지 파일들을 자동으로 발견
        
        Returns:
            List[Path]: 발견된 이미지 파일 경로들
        """
        if not self.image_folder.exists():
            console.print(f"❌ 이미지 폴더를 찾을 수 없습니다: {self.image_folder}")
            return []
        
        discovered_files = []
        
        # exam으로 시작하는 이미지 파일들 검색
        for extension in SUPPORTED_EXTENSIONS:
            pattern = f"exam*{extension}"
            files = list(self.image_folder.glob(pattern))
            discovered_files.extend(files)
        
        # 중복 제거 및 정렬
        discovered_files = sorted(set(discovered_files))
        
        if not discovered_files:
            console.print(f"⚠️ {self.image_folder}에서 exam*.* 패턴의 이미지 파일을 찾을 수 없습니다.")
            console.print("지원 형식:", ", ".join(SUPPORTED_EXTENSIONS))
        
        return discovered_files
    
    async def test_single_image(
        self, 
        image_path: Path, 
        use_cache: bool = False
    ) -> ImageTestResult:
        """
        단일 이미지에 대한 글자 인식 테스트
        
        Args:
            image_path: 테스트할 이미지 파일 경로
            use_cache: 캐시 사용 여부
            
        Returns:
            ImageTestResult: 테스트 결과
        """
        async with self.semaphore:  # 동시 처리 수 제한
            start_time = time.time()
            file_size_kb = image_path.stat().st_size // 1024
            
            retry_count = 0
            last_error = ""
            
            while retry_count <= MAX_RETRIES:
                try:
                    # 이미지 파일 읽기
                    with open(image_path, 'rb') as f:
                        image_data = f.read()
                    
                    # HTTP 클라이언트로 API 호출
                    async with httpx.AsyncClient(timeout=self.timeout) as client:
                        files = {
                            "file": (image_path.name, image_data, f"image/{image_path.suffix[1:]}")
                        }
                        params = {"use_cache": use_cache}
                        
                        response = await client.post(
                            self.full_endpoint_url,
                            files=files,
                            params=params
                        )
                        
                        processing_time_ms = int((time.time() - start_time) * 1000)
                        
                        if response.status_code == 200:
                            # 성공 응답 처리
                            result_data = response.json()
                            answers = result_data.get("answers", [])
                            
                            # 평균 신뢰도 계산
                            confidence_avg = 0.0
                            if answers:
                                confidence_avg = sum(
                                    answer.get("confidence", 0) for answer in answers
                                ) / len(answers)
                            
                            return ImageTestResult(
                                filename=image_path.name,
                                file_path=str(image_path),
                                file_size_kb=file_size_kb,
                                success=True,
                                processing_time_ms=processing_time_ms,
                                answers_detected=len(answers),
                                answers=answers,
                                confidence_avg=confidence_avg,
                                http_status_code=response.status_code,
                                retry_count=retry_count,
                                timestamp=datetime.now().isoformat()
                            )
                        
                        else:
                            # HTTP 에러 응답
                            error_msg = f"HTTP {response.status_code}: {response.text}"
                            last_error = error_msg
                            
                            # 4xx 에러는 재시도하지 않음
                            if 400 <= response.status_code < 500:
                                break
                
                except httpx.TimeoutException as e:
                    last_error = f"요청 타임아웃: {str(e)}"
                except httpx.RequestError as e:
                    last_error = f"요청 오류: {str(e)}"
                except Exception as e:
                    last_error = f"예상치 못한 오류: {str(e)}"
                
                retry_count += 1
                if retry_count <= MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY * retry_count)  # 지수 백오프
            
            # 실패 결과 반환
            processing_time_ms = int((time.time() - start_time) * 1000)
            
            return ImageTestResult(
                filename=image_path.name,
                file_path=str(image_path),
                file_size_kb=file_size_kb,
                success=False,
                processing_time_ms=processing_time_ms,
                answers_detected=0,
                answers=[],
                confidence_avg=0.0,
                error_message=last_error,
                retry_count=retry_count - 1,
                timestamp=datetime.now().isoformat()
            )
    
    async def check_server_health(self) -> bool:
        """
        API 서버 상태 확인
        
        Returns:
            bool: 서버가 정상인지 여부
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                health_response = await client.get(f"{self.api_base_url}/health")
                return health_response.status_code == 200
        except Exception as e:
            logger.error("서버 상태 확인 실패", error=str(e))
            return False
    
    async def run_batch_test(
        self, 
        use_cache: bool = False,
        show_progress: bool = True
    ) -> BatchTestSummary:
        """
        배치 테스트 실행
        
        Args:
            use_cache: 캐시 사용 여부
            show_progress: 진행 상황 표시 여부
            
        Returns:
            BatchTestSummary: 배치 테스트 결과 요약
        """
        start_time = time.time()
        start_time_str = datetime.now().isoformat()
        
        # 서버 상태 확인
        console.print("🔍 [bold blue]API 서버 상태 확인...[/bold blue]")
        if not await self.check_server_health():
            console.print("❌ API 서버에 연결할 수 없습니다.")
            console.print(f"서버 URL: {self.api_base_url}")
            console.print("서버가 실행 중인지 확인해주세요: uv run dev")
            raise RuntimeError("API 서버 연결 실패")
        
        console.print("✅ API 서버 연결 확인")
        
        # 이미지 파일 검색
        console.print("\n📁 [bold blue]이미지 파일 검색 중...[/bold blue]")
        image_files = self.discover_exam_images()
        
        if not image_files:
            raise RuntimeError("테스트할 이미지 파일을 찾을 수 없습니다.")
        
        console.print(f"📊 발견된 이미지 파일: {len(image_files)}개")
        for img_file in image_files:
            file_size_mb = img_file.stat().st_size / (1024 * 1024)
            console.print(f"  • {img_file.name} ({file_size_mb:.1f}MB)")
        
        # 배치 테스트 실행
        console.print(f"\n🚀 [bold green]배치 글자 인식 테스트 시작[/bold green]")
        console.print(f"🔗 엔드포인트: {self.full_endpoint_url}")
        console.print(f"⚡ 최대 동시 처리: {self.max_concurrent}개")
        console.print(f"💾 캐시 사용: {'예' if use_cache else '아니오'}")
        console.print(f"⏱️ 타임아웃: {self.timeout}초")
        
        if show_progress:
            # Rich 진행 상황 표시
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeRemainingColumn(),
                console=console
            ) as progress:
                
                task = progress.add_task(
                    "이미지 처리 중...", 
                    total=len(image_files)
                )
                
                # 비동기 배치 처리
                tasks = [
                    self.test_single_image(img_file, use_cache)
                    for img_file in image_files
                ]
                
                # 병렬 실행 및 진행 상황 업데이트
                for coro in asyncio.as_completed(tasks):
                    result = await coro
                    self.test_results.append(result)
                    
                    status = "✅" if result.success else "❌"
                    progress.update(
                        task, 
                        advance=1,
                        description=f"{status} {result.filename} 처리 완료"
                    )
        else:
            # 진행 상황 표시 없이 배치 처리
            tasks = [
                self.test_single_image(img_file, use_cache)
                for img_file in image_files
            ]
            self.test_results = await asyncio.gather(*tasks)
        
        # 결과 요약 생성
        end_time = time.time()
        end_time_str = datetime.now().isoformat()
        duration_seconds = end_time - start_time
        
        successful_results = [r for r in self.test_results if r.success]
        failed_results = [r for r in self.test_results if not r.success]
        
        total_processing_time = sum(r.processing_time_ms for r in self.test_results)
        avg_processing_time = total_processing_time / len(self.test_results) if self.test_results else 0
        
        total_answers = sum(r.answers_detected for r in successful_results)
        avg_answers = total_answers / len(successful_results) if successful_results else 0
        
        avg_confidence = sum(r.confidence_avg for r in successful_results) / len(successful_results) if successful_results else 0
        
        return BatchTestSummary(
            total_files=len(image_files),
            successful_tests=len(successful_results),
            failed_tests=len(failed_results),
            success_rate=len(successful_results) / len(image_files) if image_files else 0,
            total_processing_time_ms=total_processing_time,
            avg_processing_time_ms=avg_processing_time,
            total_answers_detected=total_answers,
            avg_answers_per_image=avg_answers,
            avg_confidence=avg_confidence,
            start_time=start_time_str,
            end_time=end_time_str,
            duration_seconds=duration_seconds
        )
    
    def display_results(self, summary: BatchTestSummary):
        """결과를 콘솔에 표시"""
        
        console.print("\n" + "="*60)
        console.print("🎯 [bold green]배치 테스트 결과 요약[/bold green]")
        console.print("="*60)
        
        # 요약 통계 테이블
        summary_table = Table(show_header=True, header_style="bold cyan")
        summary_table.add_column("항목", style="cyan")
        summary_table.add_column("값", style="magenta")
        
        summary_table.add_row("총 파일 수", str(summary.total_files))
        summary_table.add_row("성공", f"{summary.successful_tests} ({summary.success_rate:.1%})")
        summary_table.add_row("실패", str(summary.failed_tests))
        summary_table.add_row("총 처리 시간", f"{summary.duration_seconds:.1f}초")
        summary_table.add_row("평균 처리 시간", f"{summary.avg_processing_time_ms:.0f}ms")
        summary_table.add_row("총 답안 감지", f"{summary.total_answers_detected}개")
        summary_table.add_row("이미지당 평균 답안", f"{summary.avg_answers_per_image:.1f}개")
        summary_table.add_row("평균 신뢰도", f"{summary.avg_confidence:.1%}")
        
        console.print(summary_table)
        
        # 개별 결과 상세 표시
        if self.test_results:
            console.print("\n📋 [bold blue]개별 테스트 결과[/bold blue]")
            
            results_table = Table(show_header=True, header_style="bold cyan")
            results_table.add_column("파일명", style="white")
            results_table.add_column("상태", justify="center")
            results_table.add_column("처리시간", justify="right")
            results_table.add_column("답안수", justify="center")
            results_table.add_column("신뢰도", justify="right")
            results_table.add_column("에러", style="red")
            
            for result in self.test_results:
                status = "✅ 성공" if result.success else "❌ 실패"
                processing_time = f"{result.processing_time_ms}ms"
                answers_count = str(result.answers_detected) if result.success else "-"
                confidence = f"{result.confidence_avg:.1%}" if result.success else "-"
                error_msg = result.error_message[:50] + "..." if len(result.error_message) > 50 else result.error_message
                
                results_table.add_row(
                    result.filename,
                    status,
                    processing_time,
                    answers_count,
                    confidence,
                    error_msg if not result.success else ""
                )
            
            console.print(results_table)
        
        # 성공한 결과들의 상세 답안 표시
        successful_results = [r for r in self.test_results if r.success]
        if successful_results:
            console.print("\n📝 [bold blue]감지된 답안 상세[/bold blue]")
            for result in successful_results:
                if result.answers:
                    console.print(f"\n🔍 {result.filename}:")
                    for i, answer in enumerate(result.answers, 1):
                        question_label = answer.get('question_label', f'문제{i}')
                        extracted_text = answer.get('extracted_text', '')
                        confidence = answer.get('confidence', 0)
                        console.print(f"  • {question_label}: '{extracted_text}' (신뢰도: {confidence:.2f})")
    
    def save_results(self, summary: BatchTestSummary, output_base_dir: str = "tests/results") -> Path:
        """
        결과를 실행별 폴더에 저장
        
        Args:
            summary: 배치 테스트 결과 요약
            output_base_dir: 결과 저장 기본 디렉토리
            
        Returns:
            Path: 생성된 결과 폴더 경로
        """
        # 실행별 고유 폴더 생성
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_folder = Path(output_base_dir) / f"run_{timestamp}"
        
        # 폴더 생성 (부모 폴더도 자동 생성)
        results_folder.mkdir(parents=True, exist_ok=True)
        
        # 테스트 설정 저장
        config_data = {
            "test_execution": {
                "timestamp": timestamp,
                "start_time": summary.start_time,
                "end_time": summary.end_time,
                "duration_seconds": summary.duration_seconds
            },
            "test_config": {
                "image_folder": str(self.image_folder),
                "api_base_url": self.api_base_url,
                "endpoint": self.endpoint,
                "full_endpoint_url": self.full_endpoint_url,
                "max_concurrent": self.max_concurrent,
                "timeout": self.timeout,
                "max_retries": MAX_RETRIES,
                "retry_delay": RETRY_DELAY
            },
            "environment": {
                "supported_extensions": list(SUPPORTED_EXTENSIONS),
                "python_version": "3.11+",
                "script_version": "2.0.0"
            }
        }
        
        config_file = results_folder / "config.json"
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)
        
        # 메인 결과 데이터 저장 (JSON)
        results_data = {
            "summary": asdict(summary),
            "individual_results": [asdict(result) for result in self.test_results]
        }
        
        results_json_file = results_folder / "results.json"
        with open(results_json_file, 'w', encoding='utf-8') as f:
            json.dump(results_data, f, ensure_ascii=False, indent=2)
        
        # CSV 결과 저장
        results_csv_file = results_folder / "results.csv"
        with open(results_csv_file, 'w', newline='', encoding='utf-8') as f:
            if self.test_results:
                fieldnames = [
                    'filename', 'success', 'processing_time_ms', 
                    'answers_detected', 'confidence_avg', 
                    'file_size_kb', 'error_message', 'retry_count', 'timestamp'
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                
                for result in self.test_results:
                    writer.writerow({
                        'filename': result.filename,
                        'success': result.success,
                        'processing_time_ms': result.processing_time_ms,
                        'answers_detected': result.answers_detected,
                        'confidence_avg': result.confidence_avg,
                        'file_size_kb': result.file_size_kb,
                        'error_message': result.error_message,
                        'retry_count': result.retry_count,
                        'timestamp': result.timestamp
                    })
        
        # 마크다운 요약 리포트 생성
        summary_md_file = results_folder / "summary.md"
        self._generate_markdown_summary(summary, summary_md_file)
        
        console.print(f"\n💾 결과 저장 완료: {results_folder}")
        console.print(f"  • 설정: config.json")
        console.print(f"  • 결과: results.json")
        console.print(f"  • CSV: results.csv")
        console.print(f"  • 요약: summary.md")
        
        return results_folder
    
    def _generate_markdown_summary(self, summary: BatchTestSummary, output_file: Path):
        """
        마크다운 형태의 요약 리포트 생성
        
        Args:
            summary: 배치 테스트 결과 요약
            output_file: 출력 파일 경로
        """
        successful_results = [r for r in self.test_results if r.success]
        failed_results = [r for r in self.test_results if not r.success]
        
        md_content = f"""# 배치 시험 이미지 글자 인식 테스트 결과

## 📊 테스트 요약

- **실행 시간**: {summary.start_time} ~ {summary.end_time}
- **총 처리 시간**: {summary.duration_seconds:.1f}초
- **테스트 파일 수**: {summary.total_files}개
- **성공률**: {summary.success_rate:.1%} ({summary.successful_tests}/{summary.total_files})
- **평균 처리 시간**: {summary.avg_processing_time_ms:.0f}ms
- **총 답안 감지**: {summary.total_answers_detected}개
- **이미지당 평균 답안**: {summary.avg_answers_per_image:.1f}개  
- **평균 신뢰도**: {summary.avg_confidence:.1%}

## 🔧 테스트 설정

- **이미지 폴더**: `{self.image_folder}`
- **API 엔드포인트**: `{self.full_endpoint_url}`
- **최대 동시 처리**: {self.max_concurrent}개
- **타임아웃**: {self.timeout}초
- **재시도 횟수**: {MAX_RETRIES}회

## ✅ 성공한 테스트 ({len(successful_results)}개)

"""
        
        if successful_results:
            md_content += "| 파일명 | 처리시간 | 답안수 | 평균 신뢰도 |\n"
            md_content += "|--------|----------|--------|----------|\n"
            
            for result in successful_results:
                md_content += f"| {result.filename} | {result.processing_time_ms}ms | {result.answers_detected} | {result.confidence_avg:.1%} |\n"
            
            md_content += "\n### 감지된 답안 상세\n\n"
            for result in successful_results:
                if result.answers:
                    md_content += f"#### {result.filename}\n\n"
                    for answer in result.answers:
                        question_label = answer.get('question_label', '')
                        extracted_text = answer.get('extracted_text', '')
                        confidence = answer.get('confidence', 0)
                        md_content += f"- **{question_label}**: `{extracted_text}` (신뢰도: {confidence:.2f})\n"
                    md_content += "\n"
        
        if failed_results:
            md_content += f"\n## ❌ 실패한 테스트 ({len(failed_results)}개)\n\n"
            md_content += "| 파일명 | 처리시간 | 재시도 횟수 | 에러 메시지 |\n"
            md_content += "|--------|----------|-------------|-------------|\n"
            
            for result in failed_results:
                error_msg = result.error_message[:100] + "..." if len(result.error_message) > 100 else result.error_message
                md_content += f"| {result.filename} | {result.processing_time_ms}ms | {result.retry_count} | {error_msg} |\n"
        
        md_content += f"\n## 📈 성능 분석\n\n"
        
        if successful_results:
            processing_times = [r.processing_time_ms for r in successful_results]
            min_time = min(processing_times)
            max_time = max(processing_times)
            
            md_content += f"- **최소 처리 시간**: {min_time}ms\n"
            md_content += f"- **최대 처리 시간**: {max_time}ms\n"
            md_content += f"- **처리 시간 범위**: {max_time - min_time}ms\n"
            
            confidence_scores = [r.confidence_avg for r in successful_results if r.confidence_avg > 0]
            if confidence_scores:
                min_confidence = min(confidence_scores)
                max_confidence = max(confidence_scores)
                md_content += f"- **최소 신뢰도**: {min_confidence:.1%}\n"
                md_content += f"- **최대 신뢰도**: {max_confidence:.1%}\n"
        
        md_content += f"\n---\n*생성 시간: {datetime.now().isoformat()}*\n"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(md_content)


async def main():
    """메인 실행 함수"""
    
    console.print(Panel.fit(
        "[bold blue]배치 시험 이미지 글자 인식 테스터[/bold blue]\n"
        "test_exam_image 폴더의 모든 exam*.* 파일들을 자동으로 테스트합니다.",
        title="🧪 Batch Exam Image Tester",
        border_style="blue"
    ))
    
    # 설정
    IMAGE_FOLDER = "tests/data/images"
    USE_CACHE = False  # 캐시 비활성화로 실제 성능 측정
    MAX_CONCURRENT = 2  # 안정성을 위해 동시 처리 수 제한
    
    try:
        # 테스터 초기화
        tester = BatchExamImageTester(
            image_folder=IMAGE_FOLDER,
            max_concurrent=MAX_CONCURRENT
        )
        
        # 배치 테스트 실행
        summary = await tester.run_batch_test(
            use_cache=USE_CACHE,
            show_progress=True
        )
        
        # 결과 표시
        tester.display_results(summary)
        
        # 결과 저장
        results_folder = tester.save_results(summary)
        
        # 최종 메시지
        if summary.success_rate == 1.0:
            console.print("\n🎉 [bold green]모든 테스트가 성공했습니다![/bold green]")
        elif summary.success_rate > 0.5:
            console.print(f"\n⚠️ [bold yellow]일부 테스트가 실패했습니다. 성공률: {summary.success_rate:.1%}[/bold yellow]")
        else:
            console.print(f"\n❌ [bold red]대부분의 테스트가 실패했습니다. 성공률: {summary.success_rate:.1%}[/bold red]")
            console.print("API 서버나 이미지 파일을 확인해주세요.")
        
    except KeyboardInterrupt:
        console.print("\n⛔ 사용자에 의해 테스트가 중단되었습니다.")
    except Exception as e:
        console.print(f"\n❌ 테스트 실행 중 오류: {e}")
        logger.exception("배치 테스트 실행 오류")


if __name__ == "__main__":
    asyncio.run(main())