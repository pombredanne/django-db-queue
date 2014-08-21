from django.db import transaction
from django.core.management.base import NoArgsCommand
from django.utils.module_loading import import_by_path
from django_dbq.apps.core.models import Job
from simplesignals.process import WorkerProcessBase
from time import sleep
import logging


logger = logging.getLogger(__name__)


def process_job():
    """This function grabs the next available job, and runs its next task."""

    with transaction.atomic():
        job = Job.objects.get_ready_or_none()
        if not job:
            return

        logger.info('Processing job: name="%s" id=%s state=%s next_task=%s', job.name, job.pk, job.state, job.next_task)
        job.state = Job.STATES.PROCESSING
        job.save()

    try:
        task_function = import_by_path(job.next_task)
        task_function(job)
        job.update_next_task()
        if not job.next_task:
            job.state = Job.STATES.COMPLETE
        else:
            job.state = Job.STATES.READY
    except Exception as exception:
        logger.exception("Job id=%s failed", job.pk)
        job.state = Job.STATES.FAILED

        failure_hook_name = job.get_failure_hook_name()
        if failure_hook_name:
            logger.info("Running failure hook %s for job id=%s", failure_hook_name, job.pk)
            failure_hook_function = import_by_path(failure_hook_name)
            failure_hook_function(job, exception)
        else:
            logger.info("No failure hook for job id=%s", job.pk)

    logger.info('Updating job: name="%s" id=%s state=%s next_task=%s', job.name, job.pk, job.state, job.next_task or 'none')

    try:
        job.save()
    except:
        logger.error('Failed to save job: id=%s org=%s', job.pk, job.workspace.get('organisation_id'))
        raise


class Worker(WorkerProcessBase):

    process_title = "jobworker"

    def do_work(self):
        sleep(1)
        process_job()


class Command(NoArgsCommand):

    help = "Run a queue worker process"

    def handle_noargs(self, **options):
        logger.info("Starting job worker")
        worker = Worker()
        worker.run()