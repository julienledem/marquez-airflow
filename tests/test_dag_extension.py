# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from airflow.utils.state import State
from contextlib import contextmanager
from marquez_client import MarquezClient
from marquez_airflow import DAG
from unittest.mock import Mock, create_autospec, patch

import airflow.models
import marquez_airflow.utils
import os
import pendulum
import pytest
import sys


class MockDag:
    def __init__(self, dag_id, schedule_interval=None, location=None,
                 input_urns=None, output_urns=None,
                 start_date=None, description=None,
                 marquez_run_id=None, airflow_run_id=None,
                 mock_marquez_client=True):
        self.dag_id = dag_id
        self.schedule_interval = schedule_interval or '*/10 * * * *'
        self.location = location or 'test_location'
        self.input_urns = input_urns or []
        self.output_urns = output_urns or []
        self.start_date = start_date or pendulum.datetime(2019, 1, 31, 0, 0, 0)
        self.description = description or 'test description'

        self.marquez_run_id = marquez_run_id or '71d29487-0b54-4ae1-9295'
        self.airflow_run_id = airflow_run_id or 'airflow_run_id_123456'

        self.marquez_dag = DAG(
            self.dag_id,
            schedule_interval=self.schedule_interval,
            default_args={'marquez_location': self.location,
                          'marquez_input_urns': self.input_urns,
                          'marquez_output_urns': self.output_urns,
                          'owner': 'na',
                          'depends_on_past': False,
                          'start_date': self.start_date},
            description=self.description)
        if mock_marquez_client:
            self.marquez_dag._marquez_client = \
                make_mock_marquez_client(self.marquez_run_id)


@contextmanager
def execute_test(test_dag, mock_dag_run, mock_set,
                 expected_starttime="2019-01-31T00:00:00Z",
                 expected_endtime="2019-01-31T00:10:00Z"):
    mock_dag_run.return_value = make_mock_airflow_jobrun(
        test_dag.dag_id,
        test_dag.airflow_run_id)
    yield
    # Test the corresponding marquez calls
    assert_marquez_calls_for_dagrun(test_dag,
                                    expected_starttime=expected_starttime,
                                    expected_endtime=expected_endtime)

    # Assert there is a job_id mapping being created
    mock_set.assert_called_once_with(
        marquez_airflow.utils.JobIdMapping.make_key(test_dag.dag_id,
                                                    test_dag.airflow_run_id),
        test_dag.marquez_run_id)


@patch.object(airflow.models.DAG, 'create_dagrun')
@patch.object(marquez_airflow.utils.JobIdMapping, 'set')
def test_create_dagrun(mock_set, mock_dag_run):

    test_dag = MockDag('test_dag_id')
    with execute_test(test_dag, mock_dag_run, mock_set):
        test_dag.marquez_dag.create_dagrun(state=State.RUNNING,
                                           run_id=test_dag.airflow_run_id,
                                           execution_date=test_dag.start_date)


@patch.object(airflow.models.DAG, 'create_dagrun')
@patch.object(marquez_airflow.utils.JobIdMapping, 'set')
def test_dag_once_schedule(mock_set, mock_dag_run):
    test_dag = MockDag('test_dag_id', schedule_interval="@once")
    with execute_test(test_dag, mock_dag_run, mock_set,
                      expected_endtime=None):
        test_dag.marquez_dag.create_dagrun(state=State.RUNNING,
                                           run_id=test_dag.airflow_run_id,
                                           execution_date=test_dag.start_date)


@patch.object(airflow.models.DAG, 'create_dagrun')
@patch.object(marquez_airflow.utils.JobIdMapping, 'set')
def test_no_marquez_connection(mock_set, mock_dag_run):
    test_dag = MockDag('test_dag_id', mock_marquez_client=False)

    mock_dag_run.return_value = make_mock_airflow_jobrun(
            test_dag.dag_id,
            test_dag.airflow_run_id)

    test_dag.marquez_dag.create_dagrun(state=State.RUNNING,
                                       run_id=test_dag.airflow_run_id,
                                       execution_date=test_dag.start_date)

    mock_set.assert_not_called()


def test_custom_namespace():
    os.environ['MARQUEZ_NAMESPACE'] = 'test_namespace'
    test_dag = MockDag('test_dag_id')
    assert test_dag.marquez_dag.marquez_namespace == 'test_namespace'


def test_default_namespace():
    os.environ.clear()
    test_dag = MockDag('test_dag_id')
    assert test_dag.marquez_dag.marquez_namespace == \
        DAG.DEFAULT_NAMESPACE


def assert_marquez_calls_for_dagrun(test_dag,
                                    expected_starttime,
                                    expected_endtime):
    marquez_client = test_dag.marquez_dag._marquez_client

    marquez_client.create_job.assert_called_once_with(
        test_dag.dag_id, test_dag.location, test_dag.input_urns,
        test_dag.output_urns, description=test_dag.description)

    marquez_client.create_job_run.assert_called_once_with(
        test_dag.dag_id, run_args="{}",
        nominal_start_time=expected_starttime,
        nominal_end_time=expected_endtime)


def make_mock_marquez_client(run_id):
    mock_marquez_client = create_autospec(MarquezClient)
    mock_marquez_client.create_job_run.return_value = {'runId': run_id}
    return mock_marquez_client


def make_mock_airflow_jobrun(dag_id, airflow_run_id):
    mock_airflow_jobrun = Mock()
    mock_airflow_jobrun.run_id = airflow_run_id
    mock_airflow_jobrun.dag_id = dag_id
    return mock_airflow_jobrun


if __name__ == "__main__":
    pytest.main([sys.argv[0]])
