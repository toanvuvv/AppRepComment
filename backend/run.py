import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()  # Đọc backend/.env trước khi khởi động

if __name__ == "__main__":
    is_dev = os.getenv("ENV", "development") == "development"
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=is_dev,
    )
