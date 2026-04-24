import os
import pytest
from unittest.mock import MagicMock, patch
from app.services.workflow_service import WorkflowService
from app.config import Config


class TestWorkflowService:
    @pytest.fixture
    def mock_deps(self):
        with patch('app.services.workflow_service.collect_and_store') as mock_collect, \
             patch('app.services.workflow_service.detect_market') as mock_detect, \
             patch('app.services.workflow_service.db_manager') as mock_db:
            mock_db.table_exists.return_value = False
            mock_db.save_workflow = MagicMock()
            mock_db.load_workflows.return_value = {}
            mock_collect.return_value = 200
            yield mock_detect, mock_collect, mock_db

    @pytest.fixture
    def workflow_service(self, mock_deps):
        mock_detect, _, mock_db = mock_deps
        ws = WorkflowService()
        ws.workflows = {}
        return ws

    def test_workflow_id_format(self, workflow_service):
        assert workflow_service.get_workflow_id('a', '000001', 'daily') == 'A_000001.SZ_daily'
        assert workflow_service.get_workflow_id('hk', '00700', '120min') == 'HK_00700.HK_120min'
        assert workflow_service.get_workflow_id('us', 'AAPL', '90min') == 'US_AAPL.US_90min'

    def test_register_single_market(self, workflow_service, mock_deps):
        mock_detect, mock_collect, mock_db = mock_deps
        mock_detect.return_value = [('a', '000001')]

        result = workflow_service.register_stock('000001')
        assert result['success'] is True
        assert len(result['workflows']) == 4
        assert mock_db.save_workflow.call_count == 4
        for wf_id in result['workflows']:
            parts = wf_id.split('_')
            assert parts[0] == 'A'
            assert parts[2] in ('daily', '120min', '90min', '60min')

    def test_register_multi_market(self, workflow_service, mock_deps):
        mock_detect, mock_collect, mock_db = mock_deps
        mock_detect.return_value = [('hk', '09988'), ('us', 'BABA')]

        result = workflow_service.register_stock('阿里巴巴')
        assert result['success'] is True
        assert len(result['workflows']) == 8
        assert len(result['markets']) == 2
        assert mock_db.save_workflow.call_count == 8

        hk_workflows = [w for w in result['workflows'] if w.startswith('HK_')]
        us_workflows = [w for w in result['workflows'] if w.startswith('US_')]
        assert len(hk_workflows) == 4
        assert len(us_workflows) == 4

    def test_register_duplicate(self, workflow_service, mock_deps):
        mock_detect, mock_collect, mock_db = mock_deps
        mock_detect.return_value = [('a', '000001')]

        workflow_service.register_stock('000001')
        result = workflow_service.register_stock('000001')
        assert '工作流已存在' in result['message']

    def test_get_stock_workflows(self, workflow_service, mock_deps):
        mock_detect, mock_collect, mock_db = mock_deps
        mock_detect.return_value = [('a', '000001')]
        workflow_service.register_stock('000001')
        workflows = workflow_service.get_stock_workflows('000001')
        assert len(workflows) == 4

    def test_delete_workflow(self, workflow_service, mock_deps):
        mock_detect, mock_collect, mock_db = mock_deps
        mock_detect.return_value = [('a', '000001')]
        workflow_service.register_stock('000001')
        assert workflow_service.delete_workflow('A_000001.SZ_daily') is True
        assert workflow_service.delete_workflow('A_000001.SZ_daily') is False

    def test_table_name_matches_workflow_id(self, workflow_service, mock_deps):
        mock_detect, mock_collect, mock_db = mock_deps
        mock_detect.return_value = [('a', '000001')]
        result = workflow_service.register_stock('000001')
        for wf_id in result['workflows']:
            wf_data = workflow_service.workflows[wf_id]
            assert wf_data['table'] == wf_id

    def test_multi_market_partial(self, workflow_service, mock_deps):
        mock_detect, mock_collect, mock_db = mock_deps
        mock_detect.return_value = [('hk', '09988'), ('us', 'BABA')]

        r1 = workflow_service.register_stock('阿里巴巴')
        assert len(r1['workflows']) == 8

        r2 = workflow_service.register_stock('阿里巴巴')
        assert '工作流已存在' in r2['message']
