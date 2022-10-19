import json
import logging
import subprocess  # nosec
from concurrent.futures import Executor
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from shlex import split as shlex_split
from typing import Any
from typing import Dict
from typing import List

from ...models import Workflow
from ...models import WorkflowTask
from ..common import TaskParameterEncoder
from ..common import TaskParameters


"""
Process Bakend

This backend runs fractal workflows as separate processes using a python
thread process pool, where each thread is responsible for running a single
task in a subprocess.

Incidentally, it represents the reference implementation for a backend.
"""


class TaskExecutionError(RuntimeError):
    """
    Indicate that the subprocess execution exited status != 0

    The traceback is extracted from the subprocess stderr and used to
    initialise the error. If the command is a Python executable, this gives
    access to the full traceback.

    Attributes
    ----------
    completed_process (subprocess.CompletedProcess):
        the full object as returned by subprocess.run()
    """

    def __init__(self, completed_process: subprocess.CompletedProcess):
        self.completed_process = completed_process
        super().__init__(completed_process.stderr.decode("utf-8"))


def _call_command_wrapper(cmd: str) -> subprocess.CompletedProcess:
    """
    Call command and return stdout, stderr, retcode
    """

    result = subprocess.run(shlex_split(cmd), capture_output=True)  # nosec
    if result.returncode != 0:
        raise TaskExecutionError(result)
    return result


def call_single_task(
    *,
    task: WorkflowTask,
    task_pars: TaskParameters,
    workflow_dir: Path = None,
) -> TaskParameters:
    """
    Call a single task

    This assemble the runner (input_paths, output_path, ...) and task
    arguments (arguments that are specific to the task, such as message or
    index in the dummy task), writes them to file, call the task executable
    command passing the arguments file as an input and assembles the output

    Return
    ------
    out_task_parameters (TaskParameters):
        a TaskParameters in which the previous output becomes the input and
        where metadata is the metadata dictionary returned by the task being
        called.
    """
    if not workflow_dir:
        raise RuntimeError

    # assemble full args
    args_dict = task_pars.dict(exclude={"logger"})
    args_dict.update(task.arguments)

    # write args file
    args_file_path = workflow_dir / f"{task.order}.args.json"
    with open(args_file_path, "w") as f:
        json.dump(args_dict, f, cls=TaskParameterEncoder)

    # assemble full command
    cmd = f"{task.task.command} -j {args_file_path}"

    task_pars.logger.debug(f"executing task {task.order=}")
    completed_process = _call_command_wrapper(cmd)

    # NOTE:
    # This assumes that the new metadata is printed to stdout
    updated_metadata = json.loads(completed_process.stdout)
    out_task_parameters = TaskParameters(
        input_paths=[task_pars.output_path],
        output_path=task_pars.output_path,
        metadata=updated_metadata,
        logger=task_pars.logger,
    )
    return out_task_parameters


def recursive_task_submission(
    *,
    executor: Executor,
    task_list: List[WorkflowTask],
    task_pars: TaskParameters,
    workflow_dir: Path,
) -> Future:
    """
    Recursively submit a list of task

    Each following task depends on the future.result() of the previous one,
    thus assuring the dependency chain.

    Induction process
    -----------------
    0: return a future which results in the task parameters necessary for the
       first task of the list

    n -> n+1: use output resulting from step `n` as task parameters to submit
       task `n+1`

    Return
    ------
    this_future (Future[TaskParameters]):
        a future that results to the task parameters which constitute the
        input of the following task in the list.
    """
    try:
        *dependencies, this_task = task_list
    except ValueError:
        # step 0: return future containing original task_pars
        pseudo_future: Future = Future()
        pseudo_future.set_result(task_pars)
        return pseudo_future

    task_pars.logger.debug(f"submitting task {this_task.order=}")
    this_future = executor.submit(
        call_single_task,
        task=this_task,
        task_pars=recursive_task_submission(
            executor=executor,
            task_list=dependencies,
            task_pars=task_pars,
            workflow_dir=workflow_dir,
        ).result(),
        workflow_dir=workflow_dir,
    )
    return this_future


async def process_workflow(
    *,
    workflow: Workflow,
    input_paths: List[Path],
    output_path: Path,
    input_metadata: Dict[str, Any],
    logger: logging.Logger,
    workflow_dir: Path,
    username: str = None,
) -> Dict[str, Any]:

    with ThreadPoolExecutor() as executor:
        output_dataset_metadata = recursive_task_submission(
            executor=executor,
            task_list=workflow.task_list,
            task_pars=TaskParameters(
                input_paths=input_paths,
                output_path=output_path,
                metadata=input_metadata,
                logger=logger,
            ),
            workflow_dir=workflow_dir,
        )
    return output_dataset_metadata.result()