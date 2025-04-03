#!/usr/bin/env python3

import os
import subprocess
import sys
from pathlib import Path

def main():
    # Get the project root directory
    project_root = Path(__file__).parent.absolute()
    
    # Change to project root
    os.chdir(project_root)
    
    print("Applying database migrations...")
    
    try:
        # Run alembic upgrade
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            check=True,
            capture_output=True,
            text=True
        )
        print(result.stdout)
        print("✅ Migrations applied successfully!")
        
    except subprocess.CalledProcessError as e:
        print("❌ Error applying migrations:")
        print(e.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main() 