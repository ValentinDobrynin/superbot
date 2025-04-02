import os
import sys
import atexit
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class ProcessLock:
    def __init__(self, lock_file: str = "bot.lock"):
        self.lock_file = Path(lock_file)
        self.lock_fd = None

    def acquire(self) -> bool:
        """Acquire the lock file."""
        try:
            # Try to create the lock file
            self.lock_fd = os.open(
                self.lock_file,
                os.O_CREAT | os.O_EXCL | os.O_RDWR
            )
            
            # Write the current process ID to the lock file
            pid = str(os.getpid()).encode()
            os.write(self.lock_fd, pid)
            
            # Register cleanup on exit
            atexit.register(self.release)
            
            logger.info("Process lock acquired successfully")
            return True
            
        except FileExistsError:
            # Lock file already exists
            try:
                # Try to read the PID from the lock file
                with open(self.lock_file, 'r') as f:
                    pid = int(f.read().strip())
                
                # Check if the process is still running
                try:
                    os.kill(pid, 0)
                    logger.warning(f"Another bot instance is already running (PID: {pid})")
                    return False
                except ProcessLookupError:
                    # Process is not running, remove stale lock file
                    os.remove(self.lock_file)
                    return self.acquire()
                    
            except (ValueError, IOError):
                # Lock file is corrupted or unreadable
                os.remove(self.lock_file)
                return self.acquire()
                
        except Exception as e:
            logger.error(f"Error acquiring process lock: {e}")
            return False

    def release(self):
        """Release the lock file."""
        if self.lock_fd is not None:
            try:
                os.close(self.lock_fd)
                if self.lock_file.exists():
                    os.remove(self.lock_file)
                logger.info("Process lock released")
            except Exception as e:
                logger.error(f"Error releasing process lock: {e}") 