#!/usr/bin/env python3
"""
Simple migration helper script for Alembic.

Usage:
    python migrate.py create "add users table"  # Create new migration
    python migrate.py up                          # Apply all migrations
    python migrate.py down                        # Rollback one migration
    python migrate.py current                     # Show current version
    python migrate.py history                     # Show migration history
"""
import sys
import subprocess

COMMANDS = {
    "create": lambda msg: ["alembic", "revision", "--autogenerate", "-m", msg],
    "up": lambda: ["alembic", "upgrade", "head"],
    "down": lambda: ["alembic", "downgrade", "-1"],
    "current": lambda: ["alembic", "current"],
    "history": lambda: ["alembic", "history"],
}

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command not in COMMANDS:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)
    
    if command == "create":
        if len(sys.argv) < 3:
            print("Error: 'create' requires a message")
            print("Usage: python migrate.py create \"description\"")
            sys.exit(1)
        cmd = COMMANDS[command](sys.argv[2])
    else:
        cmd = COMMANDS[command]()
    
    subprocess.run(cmd)

if __name__ == "__main__":
    main()
