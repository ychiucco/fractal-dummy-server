import importlib
from concurrent.futures import Future
from copy import deepcopy
from logging import FileHandler
from logging import Formatter
from logging import getLogger
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Literal
from typing import Optional
from typing import Union

from devtools import debug
from parsl.app.app import join_app
from parsl.app.python import PythonApp
from parsl.dataflow.dflow import DataFlowKernel
from parsl.dataflow.dflow import DataFlowKernelLoader
from parsl.dataflow.futures import AppFuture
from sqlalchemy.ext.asyncio import AsyncSession

from ... import __VERSION__
from ..models.project import Dataset
from ..models.project import Project
from ..models.task import PreprocessedTask
from ..models.task import Subtask
from ..models.task import Task
from .runner_utils import async_wrap
from .runner_utils import get_unique_executor
from .runner_utils import load_parsl_config


formatter = Formatter("%(asctime)s; %(levelname)s; %(message)s")
logger = getLogger(__name__)
handler = FileHandler("fractal.log", mode="a")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel("INFO")


def _task_fun(
    *,
    task: Task,
    input_paths: List[Path],
    output_path: Path,
    metadata: Optional[Dict[str, Any]],
    task_args: Optional[Dict[str, Any]],
    inputs,
):
    task_module = importlib.import_module(task.import_path)
    _callable = getattr(task_module, task.callable)
    metadata_update = _callable(
        input_paths=input_paths,
        output_path=output_path,
        metadata=metadata,
        **task_args,
    )
    metadata.update(metadata_update)
    try:
        metadata["history"].append(task.name)
    except KeyError:
        metadata["history"] = [task.name]
    return metadata


def _task_app_future(
    *,
    task: Task,
    input_paths: List[Path],
    output_path: Path,
    metadata: Optional[Dict[str, Any]],
    task_args: Optional[Dict[str, Any]],
    inputs,
    executors: Union[List[str], Literal["all"]] = "all",
    data_flow_kernel=None,
) -> AppFuture:

    app = PythonApp(
        _task_fun, executors=executors, data_flow_kernel=data_flow_kernel
    )
    # TODO: can we reassign app.__name__, for clarity in monitoring?
    return app(
        task=task,
        input_paths=input_paths,
        output_path=output_path,
        metadata=metadata,
        task_args=task_args,
        inputs=inputs,
    )


#####################


# FIXME RENAME dummy_fun
def dummy_fun(
    *,
    task: Task,
    component: str,
    input_paths: List[Path],
    output_path: Path,
    metadata: Optional[Dict[str, Any]],
    task_args: Optional[Dict[str, Any]],
):

    task_module = importlib.import_module(task.import_path)
    _callable = getattr(task_module, task.callable)
    _callable(
        input_paths=input_paths,
        output_path=output_path,
        metadata=metadata,
        component=component,
        **task_args,
    )
    return task.name, component


# FIXME RENAME dummy_collect
def dummy_collect(metadata, task_name=None, component_list=None, inputs=None):
    history = f"{task_name}: {component_list}"
    try:
        metadata["history"].append(history)
    except KeyError:
        metadata["history"] = [history]

    return metadata


# NOTE: this is a standard function
def _atomic_task_factory(
    *,
    task: Union[Task, Subtask, PreprocessedTask],
    input_paths: List[Path],
    output_path: Path,
    metadata: Optional[Union[Future, Dict[str, Any]]] = None,
    depends_on: Optional[List[AppFuture]] = None,
    workflow_id: int = None,
    data_flow_kernel: DataFlowKernel = None,
) -> AppFuture:
    """
    Single task processing

    Create a single PARSL app that encapsulates the task at hand and
    its parallelizazion.
    """
    if depends_on is None:
        depends_on = []

    task_args = task._arguments
    task_executor = get_unique_executor(
        workflow_id=workflow_id, task_executor=task.executor
    )
    logger.info(f'Starting "{task.name}" task on "{task_executor}" executor.')

    # NOTE this should be replaced by the logic of a specific DFK
    if data_flow_kernel is None:
        data_flow_kernel = DataFlowKernelLoader.dfk()
    assert data_flow_kernel is not None

    parall_level = task.parallelization_level
    if metadata and parall_level:

        # Define a single app
        debug(data_flow_kernel)
        dummy_task_app = PythonApp(
            dummy_fun,
            executors=[task_executor],
            data_flow_kernel=data_flow_kernel,
        )

        # Define an app that takes all the other as input
        collection_app = PythonApp(
            dummy_collect, executors="all", data_flow_kernel=data_flow_kernel
        )

        @join_app(data_flow_kernel=data_flow_kernel)
        def _parallel_task_app_future(
            *,
            task: Task,
            parall_level: str,
            input_paths: List[Path],
            output_path: Path,
            metadata: AppFuture,
            task_args: Optional[Dict[str, Any]],
            executors: Union[List[str], Literal["all"]] = "all",
        ) -> AppFuture:

            # Define a list of futures
            # NOTE: This must happen within a join_app, because metadata has
            # not yet been computed
            app_futures = []
            for item in metadata[parall_level]:
                app_future = dummy_task_app(
                    task=task,
                    component=item,
                    input_paths=input_paths,
                    output_path=output_path,
                    metadata=metadata,
                    task_args=task_args,
                )

                app_futures.append(app_future)

            # Define the corresponding future
            collection_app_future = collection_app(
                metadata,
                task_name=task.name,
                component_list=metadata[parall_level],
                inputs=app_futures,
            )

            return collection_app_future

        res = _parallel_task_app_future(
            parall_level=parall_level,
            task=task,
            input_paths=input_paths,
            output_path=output_path,
            metadata=metadata,
            task_args=task_args,
            executors=[task_executor],
        )
        return res
    else:
        res = _task_app_future(
            task=task,
            input_paths=input_paths,
            output_path=output_path,
            metadata=metadata,
            task_args=task_args,
            inputs=depends_on,
            executors=[task_executor],
            data_flow_kernel=data_flow_kernel,
        )
        return res


def _process_workflow(
    task: Union[Task, Subtask],
    input_paths: List[Path],
    output_path: Path,
    metadata: Dict[str, Any],
) -> AppFuture:
    """
    Creates the PARSL app that will execute the full workflow, taking care of
    dependencies

    Arguments
    ---------
    output_path (Path):
        directory or file where the final output, i.e., the output of the last
        task, will be written
    TBD

    Return
    ------
    TBD
    """
    preprocessed = task.preprocess()

    this_input = input_paths
    this_output = output_path
    this_metadata = deepcopy(metadata)

    workflow_id = task.id
    load_parsl_config(workflow_id=workflow_id, logger=logger)

    apps: List[PythonApp] = []

    for i, task in enumerate(preprocessed):
        this_task_app = _atomic_task_factory(
            task=task,
            input_paths=this_input,
            output_path=this_output,
            metadata=apps[i - 1] if i > 0 else this_metadata,
            workflow_id=workflow_id,
        )
        apps.append(this_task_app)
        this_input = [this_output]

    # Got to make sure that it is executed serially, task by task
    return apps[-1]


async def auto_output_dataset(
    *,
    project: Project,
    input_dataset: Dataset,
    workflow: Task,
    overwrite_input: bool = False,
):
    """
    Determine the output dataset if it was not provided explicitly

    Only datasets containing exactly one path can be used as output.

    Returns
    -------
    output_dataset (Dataset):
        the output dataset
    """
    if overwrite_input and not input_dataset.read_only:
        input_paths = input_dataset.paths
        if len(input_paths) != 1:
            raise ValueError
        output_dataset = input_dataset
    else:
        raise NotImplementedError

    return output_dataset


def validate_workflow_compatibility(
    *,
    input_dataset: Dataset,
    workflow: Task,
    output_dataset: Optional[Dataset] = None,
):
    """
    Check compatibility of workflow and input / ouptut dataset
    """
    if (
        workflow.input_type != "Any"
        and workflow.input_type != input_dataset.type
    ):
        raise TypeError(
            f"Incompatible types `{workflow.input_type}` of workflow "
            f"`{workflow.name}` and `{input_dataset.type}` of dataset "
            f"`{input_dataset.name}`"
        )

    if not output_dataset:
        if input_dataset.read_only:
            raise ValueError("Input dataset is read-only")
        else:
            input_paths = input_dataset.paths
            if len(input_paths) != 1:
                # Only single input can be safely transformed in an output
                raise ValueError(
                    "Cannot determine output path: multiple input "
                    "paths to overwrite"
                )
            else:
                output_path = input_paths[0]
    else:
        output_path = output_dataset.paths
        if len(output_path) != 1:
            raise ValueError(
                "Cannot determine output path: Multiple paths in dataset."
            )
    return output_path


def get_app_future_result(app_future: AppFuture):
    """
    See issue #140 and https://stackoverflow.com/q/43241221/19085332

    By replacing
        .. = final_metadata.result()
    with
        .. = await async_wrap(get_app_future_result)(app_future=final_metadata)
    we avoid a (long) blocking statement.
    """
    return app_future.result()


async def submit_workflow(
    *,
    db: AsyncSession,
    workflow: Task,
    input_dataset: Dataset,
    output_dataset: Dataset,
):
    """
    Prepares a workflow and applies it to a dataset

    Arguments
    ---------
    db: (AsyncSession):
        Asynchronous database session
    output_dataset (Dataset | str) :
        the destination dataset of the workflow. If not provided, overwriting
        of the input dataset is implied and an error is raised if the dataset
        is in read only mode. If a string is passed and the dataset does not
        exist, a new dataset with that name is created and within it a new
        resource with the same name.
    """

    input_paths = input_dataset.paths
    output_path = output_dataset.paths[0]

    logger.info("*" * 80)
    logger.info(f"fractal_server.__VERSION__: {__VERSION__}")
    logger.info(f"Start workflow {workflow.name}")
    logger.info(f"{input_paths=}")
    logger.info(f"{output_path=}")

    final_metadata = _process_workflow(
        task=workflow,
        input_paths=input_paths,
        output_path=output_path,
        metadata=input_dataset.meta,
    )
    output_dataset.meta = await async_wrap(get_app_future_result)(
        app_future=final_metadata
    )

    # FIXME
    # shutdown_executors(workflow_id=workflow.id)

    db.add(output_dataset)

    await db.commit()
