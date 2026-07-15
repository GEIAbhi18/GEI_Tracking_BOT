import asyncio
from core.update_engine import handle_message

async def main():
    replies = []
    async def dummy_send(text, document=None):
        replies.append(text)

    # Test multi intent
    msg = "create a task for Vikash to inspect the generator tomorrow and complete task 2"
    # Using a dummy user_id that might not be in DB, but that's fine
    await handle_message(msg, 99999, [], dummy_send)
    
    print(f"Replies from engine:")
    for r in replies:
        print(f" -> {r}")

if __name__ == "__main__":
    asyncio.run(main())
