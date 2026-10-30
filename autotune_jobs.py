"""Bounded, cancellable controller-tuning jobs; serializes numerical workloads."""
from __future__ import annotations

from copy import deepcopy
import json
import threading
import time
import uuid

from autotune import tune_gains
from engine import SimulationCancelled


class TuningJobs:
    def __init__(self, compute_lock, *, tuner=tune_gains, history_limit=16, active_limit=3):
        self.compute_lock = compute_lock
        self.tuner = tuner
        self.history_limit = history_limit
        self.active_limit = active_limit
        self.lock = threading.Lock()
        self.jobs = {}

    @staticmethod
    def _public(job):
        return deepcopy({k: v for k, v in job.items() if not k.startswith('_')})

    def create(self, config, profile):
        if profile not in ('balanced', 'speed', 'gentle'):
            raise ValueError('自動調整の目的を選んでください。')
        job_id = uuid.uuid4().hex
        with self.lock:
            active = sum(j['status'] in ('queued', 'running') for j in self.jobs.values())
            if active >= self.active_limit:
                raise ValueError('別の自動調整を処理中です。終了または中止してから実行してください。')
            terminal = [key for key, j in self.jobs.items() if j['status'] not in ('queued', 'running')]
            while len(self.jobs) >= self.history_limit and terminal:
                del self.jobs[terminal.pop(0)]
            job = dict(job_id=job_id, status='queued', profile=profile,
                       progress=dict(stage='queued', completed=0, total=0,
                                     message='先の計算の終了を待っています。'),
                       created_at=time.time(), _cancel=threading.Event())
            self.jobs[job_id] = job
            response = self._public(job)
        threading.Thread(target=self._run, args=(job_id, deepcopy(config), profile), daemon=True).start()
        return response

    def read(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            return self._public(job) if job else None

    def cancel(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return None
            if job['status'] in ('queued', 'running'):
                job['_cancel'].set()
                job['status'] = 'cancelled'
                job['progress'] = dict(stage='cancelled', completed=0, total=0,
                                       message='自動調整を中止しました。設定は変更していません。')
                job['finished_at'] = time.time()
            return self._public(job)

    def _run(self, job_id, config, profile):
        with self.lock:
            job = self.jobs.get(job_id)
        if job is None:
            return
        cancelled = job['_cancel'].is_set
        acquired = False
        try:
            while not cancelled():
                acquired = self.compute_lock.acquire(timeout=.1)
                if acquired:
                    break
            if cancelled():
                return
            with self.lock:
                if cancelled():
                    return
                job['status'] = 'running'
                job['started_at'] = time.time()

            def progress(value):
                json.dumps(value, allow_nan=False)
                with self.lock:
                    if not cancelled():
                        job['progress'] = deepcopy(value)

            result = self.tuner(config, profile=profile, cancelled=cancelled, progress=progress)
            # A completed job must be renderable; never strand polling clients on NaN.
            json.dumps(result, allow_nan=False)
            with self.lock:
                if not cancelled():
                    job['result'] = result
                    job['status'] = 'completed'
                    job['finished_at'] = time.time()
        except SimulationCancelled:
            self.cancel(job_id)
        except Exception as exc:
            with self.lock:
                if not cancelled():
                    job['status'] = 'failed'
                    job['error'] = '自動調整を完了できませんでした: ' + str(exc)
                    job['finished_at'] = time.time()
        finally:
            if acquired:
                self.compute_lock.release()
