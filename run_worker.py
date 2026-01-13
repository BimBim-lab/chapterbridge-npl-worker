"""Worker runner script with absolute imports."""

import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

# Import and run main
from nlp_worker.main import main

if __name__ == '__main__':
    main()
