"""
UUID 유틸리티 모듈

UUIDv7 생성 및 변환 기능 제공
시간 기반 정렬 가능한 UUID 생성

주요 기능:
- UUIDv7 생성
- Binary(16) 형식 변환
- 시간 정보 추출
"""

import os
import time
import random
from uuid import UUID
from typing import Optional


def generate_uuidv7() -> UUID:
    """
    UUIDv7 생성
    
    uuid7 라이브러리를 사용한 표준 UUIDv7 생성
    시간 기반 정렬 가능한 UUID 생성
    
    Returns:
        UUID: 생성된 UUIDv7
    """
    from uuid_extensions import uuid7
    return uuid7()


def uuid_to_binary(uuid_obj: UUID) -> bytes:
    """
    UUID를 Binary(16) 형식으로 변환
    
    MySQL의 BINARY(16) 컬럼에 저장하기 위한 형식
    
    Args:
        uuid_obj: 변환할 UUID 객체
        
    Returns:
        bytes: 16바이트 바이너리 데이터
    """
    return uuid_obj.bytes


def binary_to_uuid(binary_data: bytes) -> UUID:
    """
    Binary(16) 데이터를 UUID로 변환
    
    MySQL에서 읽어온 BINARY(16) 데이터를 UUID 객체로 변환
    
    Args:
        binary_data: 16바이트 바이너리 데이터
        
    Returns:
        UUID: 변환된 UUID 객체
    """
    return UUID(bytes=binary_data)


def extract_timestamp_from_uuidv7(uuid_obj: UUID) -> Optional[float]:
    """
    UUIDv7에서 타임스탬프 추출
    
    UUIDv7에 포함된 시간 정보를 추출하여 반환
    uuid7 라이브러리 사양에 따른 정확한 타임스탬프 추출
    
    Args:
        uuid_obj: UUIDv7 객체
        
    Returns:
        float: Unix 타임스탬프 (초 단위) 또는 None (v7이 아닌 경우)
    """
    if uuid_obj.version != 7:
        return None
    
    # UUIDv7 사양에 따른 타임스탬프 추출
    # 처음 36비트가 Unix 타임스탬프 (초 단위)
    # 다음 24비트가 fractional seconds
    uuid_int = uuid_obj.int
    
    # 상위 36비트 추출 (초 단위 타임스탬프)
    timestamp_secs = (uuid_int >> 92) & 0xFFFFFFFFF
    
    # 다음 24비트 추출 (fractional seconds)
    # 12비트 + 4비트 버전 + 12비트로 구성되어 있음
    frac_high = (uuid_int >> 80) & 0xFFF  # 상위 12비트
    frac_low = (uuid_int >> 64) & 0xFFF   # 하위 12비트
    
    # 24비트 fractional을 초로 변환
    fractional = ((frac_high << 12) | frac_low) / (1 << 24)
    
    return float(timestamp_secs) + fractional


def generate_ordered_uuid() -> UUID:
    """
    정렬 가능한 UUID 생성 (UUIDv7 별칭)
    
    시간 기반으로 정렬 가능한 UUID를 생성
    데이터베이스 인덱싱에 유리
    
    Returns:
        UUID: 정렬 가능한 UUID
    """
    from uuid_extensions import uuid7
    return uuid7()


# 테스트 코드
if __name__ == "__main__":
    from uuid_extensions import uuid7, uuid7str
    
    # UUIDv7 생성 테스트
    uuid1 = uuid7()
    print(f"Generated UUIDv7: {uuid1}")
    print(f"Version: {uuid1.version}")
    
    # 문자열 형태로 생성
    uuid_str = uuid7str()
    print(f"UUIDv7 as string: {uuid_str}")
    
    # 바이너리 변환 테스트
    binary = uuid_to_binary(uuid1)
    print(f"Binary representation: {binary.hex()}")
    
    # 바이너리에서 UUID 복원
    restored = binary_to_uuid(binary)
    print(f"Restored UUID: {restored}")
    print(f"Match: {uuid1 == restored}")
    
    # 타임스탬프 추출
    timestamp = extract_timestamp_from_uuidv7(uuid1)
    if timestamp:
        from datetime import datetime
        dt = datetime.fromtimestamp(timestamp)
        print(f"Extracted timestamp: {dt}")
    
    # 순서 테스트
    time.sleep(0.001)  # 1ms 대기
    uuid2 = uuid7()
    print("\nUUID1:", uuid1)
    print("UUID2:", uuid2)
    print("UUID1 < UUID2:", str(uuid1) < str(uuid2))
    
    # 다양한 형식으로 생성
    print("\n다양한 형식:")
    for fmt in ('bytes', 'hex', 'int', 'str', 'uuid', None):
        result = uuid7(as_type=fmt)
        print(f"{fmt}: {repr(result)}")