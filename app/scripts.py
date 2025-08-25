"""개발용 스크립트 모음"""

import subprocess
import sys
import os


def test():
    """pytest를 실행하여 테스트 수행"""
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v"], cwd=os.getcwd()
    )


def lint():
    """ruff를 사용하여 코드 린팅"""
    result1 = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "app/"], cwd=os.getcwd()
    )
    return result1


def format_code():
    """ruff와 black을 사용하여 코드 포맷팅"""
    result1 = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "app/"], cwd=os.getcwd()
    )
    result2 = subprocess.run([sys.executable, "-m", "black", "app/"], cwd=os.getcwd())
    return result1.returncode + result2.returncode


def install():
    """개발 의존성 포함하여 패키지 설치"""
    return subprocess.run(
        [sys.executable, "-m", "uv", "sync", "--dev"], cwd=os.getcwd()
    )


def typecheck():
    """basedpyright를 사용하여 타입 체킹"""
    print("🔍 basedpyright로 타입 체킹 중...")
    result = subprocess.run([sys.executable, "-m", "basedpyright"], cwd=os.getcwd())

    if result.returncode == 0:
        print("✅ 타입 체킹 완료!")
    else:
        print("❌ 타입 오류 발견")

    return result


def check():
    """코드 품질 종합 검사 (린팅 + 타입 체킹 + 테스트)"""
    print("🔍 코드 린팅 중...")
    lint_result = lint()

    print("\n🔍 타입 체킹 중...")
    type_result = typecheck()

    print("\n🧪 테스트 실행 중...")
    test_result = test()

    if (
        lint_result.returncode == 0
        and type_result.returncode == 0
        and test_result.returncode == 0
    ):
        print("\n✅ 모든 검사 통과!")
        return 0
    else:
        print("\n❌ 검사 실패")
        return 1
