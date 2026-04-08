import uvicorn

# BUG FIX: was "from api.main import app" which only works if main.py lives
# inside an api/ package. Since main.py is at the project root, import it directly.
from api.main import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)