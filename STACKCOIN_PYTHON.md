# StackCoin Python Client

## StackCoinClient Methods

### Balance Operations
- `get_my_balance()` - Get bot's current balance and username
- `get_balance(user_id)` - Get another user's balance by their ID

### Payment Operations
- `send(to_user_id, amount, label=None)` - Send tokens to another user
- `request_payment(from_user_id, amount, label=None)` - Request payment from a user

### Request Management
- `accept_request(request_id)` - Accept a pending payment request
- `deny_request(request_id)` - Deny a pending payment request

### Data Retrieval (Paginated)
- `get_transactions(from_user_id=None, to_user_id=None, page=1, limit=20)` - Get transaction history
- `get_requests(role=None, status=None, page=1, limit=20)` - Get payment requests
- `get_users(username=None, banned=None, admin=None, page=1, limit=20)` - Get users

### Data Streaming (Auto-pagination)
- `stream_transactions(from_user_id=None, to_user_id=None, limit=20)` - Stream all transactions
- `stream_requests(role=None, status=None, limit=20)` - Stream all payment requests
- `stream_users(username=None, banned=None, admin=None, limit=20)` - Stream all users

## Usage
Must be used as an async context manager:
```python
async with StackCoinClient("your_bot_token") as client:
    balance = await client.get_my_balance()
    print(f"Bot balance: {balance.balance} STK")
```