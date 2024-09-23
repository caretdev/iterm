import os
import sys
import pty
import subprocess
import time
import select

def read_and_forward_pty_output(fd):
    max_read_bytes = 1024 * 20
    while True:
        timeout_sec = 0
        (data_ready, _, _) = select.select([fd], [], [], timeout_sec)
        if not data_ready:
            time.sleep(0.01)
            continue

        output = os.read(fd, max_read_bytes).decode(errors="ignore")
        # print(output)

def command():
    # return ["iris", "session", "iris"]
    import iris
    bin = iris.system.Util.BinaryDirectory() + "irisdb"
    mgr = "-s" + iris.system.Util.ManagerDirectory()
    return [bin, mgr]

class IRISSession():
    max_read_bytes = 1024

    def __init__(self, pid, fd) -> None:
        self.pid = pid
        self.fd = fd

    @staticmethod
    def start(cmd=None):
        cmd = cmd if cmd else command()

        print('pid', os.getpid())
        master_fd, slave_fd = pty.openpty()

        proc = subprocess.Popen(
            cmd,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            shell=True,
            start_new_session=True,
        )
        return IRISSession(proc.pid, master_fd)


        (child_pid, fd) = pty.fork()
        print('fork', child_pid, fd)
        if child_pid == 0:
            proc = subprocess.Popen(cmd if cmd else command())
            print('child', proc.pid)
        else:
            print('main')
            return IRISSession(child_pid, fd)

    def read(self, timeout_sec = 0):
        if not self.fd:
            return
        (data_ready, _, _) = select.select([self.fd], [], [], timeout_sec)
        if not data_ready:
            return

        return os.read(self.fd, self.max_read_bytes).decode(errors="ignore")

    def write(self, input: str):
        if not self.fd:
            return

        os.write(self.fd, input.encode())

    def alive(self):
        if not self.fd:
            return

        os.write(self.fd, input.encode())

    def running(self):
        if not self.fd:
            return

        return
