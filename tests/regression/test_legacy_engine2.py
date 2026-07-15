import asyncio
from core.update_engine import handle_message

async def main():
    replies = []
    async def dummy_send(text, document=None):
        replies.append(text)

    # Test multi intent without user assignment
    msg = "complete task 2 and add note testing"
    await handle_message(msg, 99999, [], dummy_send)
    
    print(f"Replies from engine:")
    for r in replies:
        print(f" -> {r}")

if __name__ == "__main__":
    asyncio.run(main())
