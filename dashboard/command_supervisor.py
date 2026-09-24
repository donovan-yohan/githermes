"""Private POSIX subprocess supervisor; invoked only by account_backend.

No threads/forked Python state, files, logs, or credentials in argv. The inherited
flock description stays open here AND in gh until gh is killed and reaped. Never
LOCK_UN/unlink it. A dead backend therefore cannot cancel deadline enforcement.
"""
import json
import os
import selectors
import signal
import subprocess
import sys
import time


def supervise(request):
    body = None if request['body'] is None else json.dumps(request['body']).encode()
    fence = request['fence']
    deadline = time.monotonic() + request['timeout']
    proc = subprocess.Popen(
        [request['executable'], *request['args']], env=request['env'],
        cwd=request['env']['GH_CONFIG_DIR'], start_new_session=True,
        pass_fds=() if fence is None else (fence,),
        stdin=subprocess.DEVNULL if body is None else subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    chunks = [bytearray(), bytearray()]
    error = None
    try:
        with selectors.DefaultSelector() as selector:
            for index, pipe in enumerate((proc.stdout, proc.stderr)):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, index)
            if body is not None:
                os.set_blocking(proc.stdin.fileno(), False)
                selector.register(proc.stdin, selectors.EVENT_WRITE, None)
                body = memoryview(body)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    error = 'timeout'
                    break
                for key, _ in selector.select(remaining):
                    pipe = key.fileobj
                    if key.data is None:
                        try:
                            written = os.write(pipe.fileno(), body[:65536])
                            body = body[written:]
                        except BrokenPipeError:
                            body = body[:0]
                        if not body:
                            selector.unregister(pipe)
                            pipe.close()
                    else:
                        block = os.read(pipe.fileno(), 65536)
                        if not block:
                            selector.unregister(pipe)
                            pipe.close()
                        elif len(chunks[key.data]) + len(block) > request['limit']:
                            error = 'overflow'
                            break
                        else:
                            chunks[key.data].extend(block)
                if error:
                    break
            if not error:
                try:
                    proc.wait(timeout=max(0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    error = 'timeout'
    finally:
        # Do not poll/reap before killing the group: keep the PID reserved.
        # Also kill ordinary descendants holding a pipe open at the deadline.
        if proc.returncode is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            if pipe is not None:
                pipe.close()
    if error:
        return {'error': error}
    return dict(code=proc.returncode, stdout=chunks[0].decode('utf-8'),
                stderr=chunks[1].decode('utf-8'))


def main():
    try:
        request = json.load(sys.stdin)
        result = supervise(request)
    except Exception:
        # Never serialize exceptions, argv, environment, or child diagnostics.
        result = {'error': 'unavailable'}
    try:
        payload = json.dumps(result).encode()
        while payload:
            payload = payload[os.write(sys.stdout.fileno(), payload):]
    except (BrokenPipeError, OSError):
        pass  # Backend died; child was already killed/reaped above.
    # Avoid interpreter flush diagnostics after a broken parent pipe.
    os._exit(0)


if __name__ == '__main__':
    main()
