"""
Cooperative cancellation for downloads / uploads / ffmpeg.

Every unit of work (one rename, or one whole auto-post episode) gets a short
task id. The progress message's Cancel button carries `cancel_<id>`; the
progress callback checks the flag on every chunk and calls
client.stop_transmission(); a running ffmpeg process is killed directly.
"""
import uuid


class TaskCancelled(Exception):
    """Raised inside a pipeline when the user pressed Cancel."""


_tasks = {}          # task_id -> {'user_id': int, 'cancelled': bool, 'proc': process|None}
_user_current = {}   # user_id -> task_id of the normal-rename file in progress


def new_task(user_id, task_id=None):
    task_id = task_id or uuid.uuid4().hex[:10]
    _tasks[task_id] = {'user_id': user_id, 'cancelled': False, 'proc': None}
    return task_id


def drop_task(task_id):
    _tasks.pop(task_id, None)


def get_task(task_id):
    return _tasks.get(task_id)


def is_cancelled(task_id):
    task = _tasks.get(task_id)
    return bool(task and task['cancelled'])


def raise_if_cancelled(task_id):
    if is_cancelled(task_id):
        raise TaskCancelled()


def set_proc(task_id, proc):
    task = _tasks.get(task_id)
    if task is not None:
        task['proc'] = proc


def request_cancel(task_id):
    task = _tasks.get(task_id)
    if not task:
        return False
    task['cancelled'] = True
    proc = task.get('proc')
    if proc is not None and proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    return True


def set_current(user_id, task_id):
    if task_id is None:
        _user_current.pop(user_id, None)
    else:
        _user_current[user_id] = task_id


def current_for(user_id):
    return _user_current.get(user_id)
