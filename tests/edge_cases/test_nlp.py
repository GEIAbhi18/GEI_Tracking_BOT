import asyncio
from core.llm_parser import parse_with_llm
import json

message = "create a task for Vikash to inspect the generator tomorrow and complete task 2"
res = parse_with_llm(message)
print(json.dumps(res, indent=2))
