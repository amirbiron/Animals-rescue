"""
Worker management system for the Animal Rescue Bot.

Handles RQ worker lifecycle, health monitoring, job scheduling,
and provides management interface for background tasks.
"""

import asyncio
import signal
import sys
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
import multiprocessing as mp
from pathlib import Path
import psutil
import os
import uuid as _uuid

import redis
import structlog
from rq import Worker, Queue
from rq.job import Job
from rq.registry import StartedJobRegistry, FinishedJobRegistry, FailedJobRegistry
from rq_scheduler import Scheduler

from app.core.config import settings
from app.core.cache import redis_client, redis_queue_client, redis_queue_sync
from app.core.exceptions import (
    WorkerError,
    QueueError,
    ConfigurationError,
    JobFailedError
)
from app.workers.jobs import schedule_recurring_jobs

logger = structlog.get_logger(__name__)

# Worker configuration
WORKER_QUEUES = ['default', 'alerts', 'maintenance', 'external']
WORKER_TIMEOUT = settings.WORKER_TIMEOUT if hasattr(settings, 'WORKER_TIMEOUT') else 300
WORKER_PROCESSES = settings.WORKER_PROCESSES if hasattr(settings, 'WORKER_PROCESSES') else 2
JOB_TIMEOUT = 600  # 10 minutes default
HEARTBEAT_INTERVAL = 30  # seconds
MAX_MEMORY_MB = 500  # MB per worker
STATS_UPDATE_INTERVAL = 60  # seconds


class WorkerStats:
    """Tracks worker statistics and health metrics."""
    
    def __init__(self):
        self.start_time = datetime.utcnow()
        self.jobs_processed = 0
        self.jobs_failed = 0
        self.last_heartbeat = datetime.utcnow()
        self.current_job_id = None
        self.current_job_started = None
        self.memory_usage_mb = 0
        self.cpu_usage_percent = 0
        self.queue_sizes = {}
        self.error_count_last_hour = 0
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert stats to dictionary."""
        uptime = datetime.utcnow() - self.start_time
        
        return {
            'start_time': self.start_time.isoformat(),
            'uptime_seconds': uptime.total_seconds(),
            'jobs_processed': self.jobs_processed,
            'jobs_failed': self.jobs_failed,
            'last_heartbeat': self.last_heartbeat.isoformat(),
            'current_job_id': self.current_job_id,
            'current_job_duration': (
                (datetime.utcnow() - self.current_job_started).total_seconds()
                if self.current_job_started else 0
            ),
            'memory_usage_mb': self.memory_usage_mb,
            'cpu_usage_percent': self.cpu_usage_percent,
            'queue_sizes': self.queue_sizes,
            'error_rate_per_hour': self.error_count_last_hour,
            'success_rate': (
                self.jobs_processed / (self.jobs_processed + self.jobs_failed)
                if (self.jobs_processed + self.jobs_failed) > 0 else 1.0
            )
        }


class ManagedWorker:
    """Enhanced RQ Worker with health monitoring and management."""
    
    def __init__(
        self,
        worker_id: str,
        queues: List[str],
        connection: redis.Redis
    ):
        self.worker_id = worker_id
        self.queues = [Queue(name, connection=connection) for name in queues]
        self.connection = connection
        self.worker = None
        self.stats = WorkerStats()
        self.is_running = False
        self.should_stop = False
        self.process = None
        
        # Health monitoring
        self._last_stats_update = datetime.utcnow()
        self._monitoring_thread = None
        
    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            logger.info(f"Worker {self.worker_id} received signal {signum}")
            self.stop_graceful()
        
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
    
    def start(self):
        """Start the worker process."""
        if self.is_running:
            logger.warning(f"Worker {self.worker_id} is already running")
            return
        
        try:
            # Create RQ Worker
            # Use a unique RQ worker name to avoid collisions on restarts
            unique_suffix = f"{os.getpid()}-{_uuid.uuid4().hex[:6]}"
            rq_worker_name = f"{self.worker_id}-{unique_suffix}"
            self.worker = Worker(
                queues=self.queues,
                connection=self.connection,
                name=rq_worker_name,
                default_worker_ttl=WORKER_TIMEOUT
            )
            
            # Setup job lifecycle hooks
            self.worker.push_exc_handler(self._job_exception_handler)
            
            # Setup signal handlers
            self.setup_signal_handlers()
            
            # Start monitoring thread
            self._start_monitoring()
            
            logger.info(
                f"Starting worker {self.worker_id}",
                queues=[q.name for q in self.queues],
                timeout=WORKER_TIMEOUT
            )
            
            self.is_running = True
            
            # Run worker (blocks until stopped)
            self.worker.work(
                with_scheduler=False,
                logging_level='INFO'
            )
            
        except Exception as e:
            logger.error(
                f"Worker {self.worker_id} failed to start",
                error=str(e)
            )
            raise WorkerError(f"Failed to start worker {self.worker_id}: {str(e)}")
        
        finally:
            self.is_running = False
            self._stop_monitoring()
    
    def stop_graceful(self, timeout: int = 30):
        """Stop worker gracefully."""
        if not self.is_running:
            return
        
        logger.info(f"Stopping worker {self.worker_id} gracefully")
        self.should_stop = True
        
        if self.worker:
            # Send stop signal to worker (RQ>=2.0 expects frame param)
            try:
                self.worker.request_stop(signal.SIGTERM, None)
            except TypeError:
                # Fallback for older RQ versions
                self.worker.request_stop()
            
            # Wait for graceful shutdown
            start_time = time.time()
            while self.is_running and (time.time() - start_time) < timeout:
                time.sleep(0.5)
        
        if self.is_running:
            logger.warning(f"Worker {self.worker_id} did not stop gracefully, forcing")
            self.stop_force()
    
    def stop_force(self):
        """Force stop worker."""
        if self.process and self.process.is_alive():
            logger.warning(f"Force killing worker process {self.worker_id}")
            self.process.terminate()
            self.process.join(timeout=5)
            
            if self.process.is_alive():
                self.process.kill()
        
        self.is_running = False
        self._stop_monitoring()
    
    def _start_monitoring(self):
        """Start health monitoring thread."""
        if self._monitoring_thread and self._monitoring_thread.is_alive():
            return
        
        self._monitoring_thread = threading.Thread(
            target=self._monitoring_loop,
            daemon=True
        )
        self._monitoring_thread.start()
    
    def _stop_monitoring(self):
        """Stop monitoring thread."""
        self.should_stop = True
    
    def _monitoring_loop(self):
        """Background monitoring loop."""
        while not self.should_stop:
            try:
                self._update_stats()
                self._send_heartbeat()
                time.sleep(HEARTBEAT_INTERVAL)
            except Exception as e:
                logger.error(f"Worker {self.worker_id} monitoring error", error=str(e))
                time.sleep(5)
    
    def _update_stats(self):
        """Update worker statistics."""
        try:
            # System metrics
            process = psutil.Process()
            self.stats.memory_usage_mb = process.memory_info().rss / 1024 / 1024
            self.stats.cpu_usage_percent = process.cpu_percent()
            
            # Queue sizes
            for queue in self.queues:
                self.stats.queue_sizes[queue.name] = len(queue)
            
            # Update timestamp
            self._last_stats_update = datetime.utcnow()
            
            # Check memory usage
            if self.stats.memory_usage_mb > MAX_MEMORY_MB:
                logger.warning(
                    f"Worker {self.worker_id} high memory usage",
                    memory_mb=self.stats.memory_usage_mb,
                    limit_mb=MAX_MEMORY_MB
                )
            
        except Exception as e:
            logger.error(f"Failed to update worker stats", error=str(e))
    
    def _send_heartbeat(self):
        """Send heartbeat to Redis."""
        try:
            heartbeat_key = f"worker_heartbeat:{self.worker_id}"
            heartbeat_data = {
                'worker_id': self.worker_id,
                'timestamp': datetime.utcnow().isoformat(),
                'is_busy': self.worker.get_state() == 'busy' if self.worker else False,
                'current_job': self.stats.current_job_id,
                **self.stats.to_dict()
            }
            
            # Store heartbeat with TTL
            self.connection.setex(
                heartbeat_key,
                HEARTBEAT_INTERVAL * 2,  # TTL = 2x heartbeat interval
                str(heartbeat_data)
            )
            
            self.stats.last_heartbeat = datetime.utcnow()
            
        except Exception as e:
            logger.error(f"Failed to send heartbeat", error=str(e))
    
    def _job_exception_handler(self, job: Job, exc_type, exc_value, traceback):
        """Handle job exceptions."""
        self.stats.jobs_failed += 1
        self.stats.error_count_last_hour += 1
        
        logger.error(
            f"Job failed in worker {self.worker_id}",
            job_id=job.id,
            job_func=job.func_name,
            error=str(exc_value),
            error_type=exc_type.__name__
        )
        
        # Clear current job
        self.stats.current_job_id = None
        self.stats.current_job_started = None
        
        return False  # Don't suppress the exception


class WorkerManager:
    """Manages multiple worker processes and provides monitoring."""
    
    def __init__(self):
        self.workers: Dict[str, ManagedWorker] = {}
        self.worker_processes: Dict[str, mp.Process] = {}
        self.scheduler = None
        self.is_running = False
        self.should_stop = False
        
        # Health check
        self._last_health_check = datetime.utcnow()
        self._health_thread = None
        
        # Statistics
        self.start_time = datetime.utcnow()
    
    async def start(self):
        """Start the worker manager."""
        if self.is_running:
            logger.warning("Worker manager is already running")
            return
        
        logger.info("Starting worker manager", worker_count=WORKER_PROCESSES)
        
        try:
            # Start scheduler
            await self._start_scheduler()
            
            # Start worker processes
            await self._start_workers()
            
            # Start health monitoring
            self._start_health_monitoring()
            
            self.is_running = True
            logger.info("Worker manager started successfully")
            
        except Exception as e:
            logger.error("Failed to start worker manager", error=str(e))
            await self.stop()
            raise WorkerError(f"Worker manager startup failed: {str(e)}")
    
    async def stop(self, timeout: int = 30):
        """Stop all workers gracefully."""
        if not self.is_running:
            return
        
        logger.info("Stopping worker manager")
        self.should_stop = True
        
        # Stop scheduler
        if self.scheduler:
            try:
                self.scheduler.cancel_delayed_jobs()
                logger.info("Scheduler stopped")
            except Exception as e:
                logger.error("Error stopping scheduler", error=str(e))
        
        # Stop all workers
        stop_tasks = []
        for worker_id, process in self.worker_processes.items():
            if process.is_alive():
                logger.info(f"Stopping worker process {worker_id}")
                process.terminate()
        
        # Wait for processes to stop
        start_time = time.time()
        while time.time() - start_time < timeout:
            alive_workers = [
                wid for wid, proc in self.worker_processes.items() 
                if proc.is_alive()
            ]
            if not alive_workers:
                break
            time.sleep(0.5)
        
        # Force kill remaining processes
        for worker_id, process in self.worker_processes.items():
            if process.is_alive():
                logger.warning(f"Force killing worker {worker_id}")
                process.kill()
                process.join()
        
        # Stop health monitoring
        self._stop_health_monitoring()
        
        self.workers.clear()
        self.worker_processes.clear()
        self.is_running = False
        
        logger.info("Worker manager stopped")
    
    async def _start_scheduler(self):
        """Start job scheduler."""
        try:
            self.scheduler = Scheduler(connection=redis_queue_sync)
            
            # Schedule recurring jobs
            schedule_recurring_jobs()
            
            logger.info("Job scheduler started")
            
        except Exception as e:
            logger.error("Failed to start scheduler", error=str(e))
            raise
    
    async def _start_workers(self):
        """Start all worker processes."""
        for i in range(WORKER_PROCESSES):
            worker_id = f"worker_{i+1}"
            
            # Create worker process
            process = mp.Process(
                target=self._worker_process_target,
                args=(worker_id, WORKER_QUEUES),
                name=f"RQWorker-{worker_id}"
            )
            
            process.start()
            self.worker_processes[worker_id] = process
            
            logger.info(f"Started worker process {worker_id} (PID: {process.pid})")
    
    def _worker_process_target(self, worker_id: str, queues: List[str]):
        """Target function for worker processes."""
        try:
            # Create worker in subprocess
            worker = ManagedWorker(
                worker_id=worker_id,
                queues=queues,
                connection=redis_queue_sync
            )
            
            # Start worker (blocks until stopped)
            worker.start()
            
        except Exception as e:
            logger.error(f"Worker process {worker_id} failed", error=str(e))
            sys.exit(1)
    
    def _start_health_monitoring(self):
        """Start health monitoring thread."""
        if self._health_thread and self._health_thread.is_alive():
            return
        
        self._health_thread = threading.Thread(
            target=self._health_monitoring_loop,
            daemon=True
        )
        self._health_thread.start()
    
    def _stop_health_monitoring(self):
        """Stop health monitoring."""
        self.should_stop = True
    
    def _health_monitoring_loop(self):
        """Health monitoring background loop."""
        while not self.should_stop:
            try:
                self._check_worker_health()
                time.sleep(STATS_UPDATE_INTERVAL)
            except Exception as e:
                logger.error("Health monitoring error", error=str(e))
                time.sleep(10)
    
    def _check_worker_health(self):
        """Check health of all workers."""
        try:
            current_time = datetime.utcnow()
            unhealthy_workers = []
            # Grace period on startup: skip aggressive checks for initial heartbeats
            uptime_seconds = (current_time - self.start_time).total_seconds()
            in_grace_period = uptime_seconds < (HEARTBEAT_INTERVAL * 2)
            
            for worker_id, process in self.worker_processes.items():
                # Check if process is alive
                if not process.is_alive():
                    unhealthy_workers.append(worker_id)
                    logger.warning(f"Worker process {worker_id} is not alive")
                    continue
                
                # Check heartbeat
                heartbeat_key = f"worker_heartbeat:{worker_id}"
                try:
                    heartbeat_data = redis_queue_sync.get(heartbeat_key)
                    if not heartbeat_data:
                        if in_grace_period and process.is_alive():
                            # Allow some time for first heartbeat after startup
                            continue
                        logger.warning(f"No heartbeat from worker {worker_id}")
                        unhealthy_workers.append(worker_id)
                except Exception as e:
                    logger.error(f"Error checking heartbeat for {worker_id}", error=str(e))
            
            # Restart unhealthy workers if needed
            for worker_id in unhealthy_workers:
                logger.info(f"Restarting unhealthy worker {worker_id}")
                self._restart_worker(worker_id)
            
            self._last_health_check = current_time
            
        except Exception as e:
            logger.error("Worker health check failed", error=str(e))
    
    def _restart_worker(self, worker_id: str):
        """Restart a specific worker."""
        try:
            # Terminate old process
            if worker_id in self.worker_processes:
                old_process = self.worker_processes[worker_id]
                if old_process.is_alive():
                    old_process.terminate()
                    old_process.join(timeout=10)
                    if old_process.is_alive():
                        old_process.kill()
            
            # Start new process
            new_process = mp.Process(
                target=self._worker_process_target,
                args=(worker_id, WORKER_QUEUES),
                name=f"RQWorker-{worker_id}"
            )
            
            new_process.start()
            self.worker_processes[worker_id] = new_process
            
            logger.info(f"Restarted worker {worker_id} (PID: {new_process.pid})")
            
        except Exception as e:
            logger.error(f"Failed to restart worker {worker_id}", error=str(e))
    
    async def get_status(self) -> Dict[str, Any]:
        """Get comprehensive worker manager status."""
        uptime = datetime.utcnow() - self.start_time
        
        # Worker status
        worker_status = {}
        for worker_id, process in self.worker_processes.items():
            worker_status[worker_id] = {
                'pid': process.pid,
                'is_alive': process.is_alive(),
                'exitcode': process.exitcode
            }
            
            # Get heartbeat data
            heartbeat_key = f"worker_heartbeat:{worker_id}"
            try:
                heartbeat_data = redis_queue_client.get(heartbeat_key)
                if heartbeat_data:
                    worker_status[worker_id]['heartbeat'] = eval(heartbeat_data.decode())
            except Exception:
                worker_status[worker_id]['heartbeat'] = None
        
        # Queue status
        queue_status = {}
        try:
            for queue_name in WORKER_QUEUES:
                queue = Queue(queue_name, connection=redis_queue_sync)
                started_registry = StartedJobRegistry(queue.name, queue.connection)
                finished_registry = FinishedJobRegistry(queue.name, queue.connection)
                failed_registry = FailedJobRegistry(queue.name, queue.connection)
                
                queue_status[queue_name] = {
                    'pending': len(queue),
                    'started': len(started_registry),
                    'finished': len(finished_registry),
                    'failed': len(failed_registry)
                }
        except Exception as e:
            logger.error("Error getting queue status", error=str(e))
            queue_status = {"error": str(e)}
        
        return {
            'manager_status': 'running' if self.is_running else 'stopped',
            'uptime_seconds': uptime.total_seconds(),
            'worker_processes': len(self.worker_processes),
            'scheduler_active': self.scheduler is not None,
            'last_health_check': self._last_health_check.isoformat(),
            'workers': worker_status,
            'queues': queue_status,
            'configuration': {
                'worker_timeout': WORKER_TIMEOUT,
                'job_timeout': JOB_TIMEOUT,
                'worker_processes': WORKER_PROCESSES,
                'heartbeat_interval': HEARTBEAT_INTERVAL
            }
        }
    
    async def get_job_info(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific job."""
        try:
            job = Job.fetch(job_id, connection=redis_queue_sync)
            
            return {
                'id': job.id,
                'status': job.status,
                'func_name': job.func_name,
                'args': job.args,
                'kwargs': job.kwargs,
                'created_at': job.created_at.isoformat() if job.created_at else None,
                'started_at': job.started_at.isoformat() if job.started_at else None,
                'ended_at': job.ended_at.isoformat() if job.ended_at else None,
                'result': str(job.result) if job.result else None,
                'exc_info': job.exc_info,
                'timeout': job.timeout,
                'ttl': job.ttl
            }
        except Exception as e:
            logger.error(f"Error getting job info for {job_id}", error=str(e))
            return None


# Global worker manager instance
worker_manager = WorkerManager()


# Context manager for worker lifecycle
@asynccontextmanager
async def managed_workers():
    """Context manager for worker lifecycle."""
    try:
        await worker_manager.start()
        yield worker_manager
    finally:
        await worker_manager.stop()


# Convenience functions
async def start_workers():
    """Start the worker manager."""
    await worker_manager.start()


async def stop_workers():
    """Stop the worker manager."""
    await worker_manager.stop()


async def get_workers_status() -> Dict[str, Any]:
    """Get worker status."""
    return await worker_manager.get_status()


async def restart_workers():
    """Restart all workers."""
    logger.info("Restarting all workers")
    await worker_manager.stop()
    await worker_manager.start()


# CLI command for running workers standalone
def run_workers_cli():
    """CLI command to run workers."""
    import asyncio
    
    async def main():
        try:
            async with managed_workers() as manager:
                logger.info("Workers started, press Ctrl+C to stop")
                
                # Keep running until interrupted
                while True:
                    await asyncio.sleep(1)
                    
        except KeyboardInterrupt:
            logger.info("Received interrupt, shutting down")
        except Exception as e:
            logger.error("Worker manager error", error=str(e))
            sys.exit(1)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown complete")
