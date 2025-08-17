# 주석 
- 주석은 한국어로 작성
- 존댓말이 아닌 한국어 명사형으로 작성
- pydoc 또한 작성.
- 간단하면서도 명료하게 작성.
- 따로 영어 주석을 찾지는 말고, 다른 작업 하다가 영어 주석이 보이면 겸사겸사 한국어로 바꿔줘.
  
# 프로젝트 구조
- pip가 아닌 uv로 패키지 관리중임.

# Context7 주소

- uv -> "/astral-sh/uv"
- langserve -> "/langchain-ai/langserve"
- langchain -> "/langchain-ai/langchain"

# 타입 체킹
uv run typecheck 명령어로 타입 체킹 가능. 코드 생성 후에 반드시 사용해서 타입을 체크하고, 오류가 있으면 수정해줘.