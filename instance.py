"""Hold a user-local file lock so two app instances cannot overwrite profiles."""
import os
from pathlib import Path

class InstanceLock:
    def __init__(self,folder):
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        self.file=(folder/'instance.lock').open('a+b')
        if self.file.tell()==0:self.file.write(b'0');self.file.flush()
        self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close();raise
    def close(self):
        if not self.file.closed:self.file.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
