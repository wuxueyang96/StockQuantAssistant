import logging
from datetime import datetime
from typing import Optional
from app.config import Config
from app.services.stock_service import (
    detect_market, get_workflow_id, get_table_name, collect_and_store,
    format_stock_code, MARKET_LABEL
)
from app.models.database import db_manager

logger = logging.getLogger(__name__)


class WorkflowService:
    def __init__(self):
        self.workflows = self.load_workflows()

    def get_workflow_id(self, market: str, stock_code: str, interval: str) -> str:
        return get_workflow_id(market, stock_code, interval)

    def check_existing_workflows_for_code(self, market: str, stock_code: str) -> Optional[list[str]]:
        existing = []
        for interval in ['daily', '120min', '90min', '60min']:
            wf_id = self.get_workflow_id(market, stock_code, interval)
            if wf_id in self.workflows:
                existing.append(wf_id)
        return existing if existing else None

    def _register_one_market(self, market: str, stock_code: str) -> list[str]:
        created = []
        for interval in ['daily', '120min', '90min', '60min']:
            wf_id = self.get_workflow_id(market, stock_code, interval)
            table_name = get_table_name(market, stock_code, interval)

            if not db_manager.table_exists(market, table_name):
                db_manager.create_stock_table(market, table_name)
                try:
                    collect_and_store(market, stock_code, interval)
                except Exception as e:
                    logger.warning(f"数据拉取失败 ({wf_id}): {e}，工作流已注册但暂无数据")

            wf_data = {
                'market': market,
                'stock_code': stock_code,
                'interval': interval,
                'table': table_name,
                'db_path': Config.DB_PATHS[market],
                'created_at': datetime.now().isoformat(),
                'active': True
            }
            self.workflows[wf_id] = wf_data
            db_manager.save_workflow(wf_id, wf_data)
            created.append(wf_id)
        return created

    def register_stock(self, stock_input: str) -> dict:
        detections = detect_market(stock_input)

        all_existing = []
        for market, stock_code in detections:
            existing = self.check_existing_workflows_for_code(market, stock_code)
            if existing:
                all_existing.extend(existing)

        if all_existing:
            return {
                'success': True,
                'message': '工作流已存在',
                'workflows': all_existing,
                'markets': [{'market': d[0], 'stock_code': d[1]} for d in detections],
            }

        all_created = []
        for market, stock_code in detections:
            created = self._register_one_market(market, stock_code)
            all_created.extend(created)

        return {
            'success': True,
            'message': '工作流已创建',
            'workflows': all_created,
            'markets': [{'market': m, 'stock_code': c} for m, c in detections],
        }

    def get_stock_workflows(self, stock_code: str) -> list[dict]:
        result = []
        for wf_id, wf_data in self.workflows.items():
            if wf_data['stock_code'] == stock_code:
                display_code = format_stock_code(wf_data['market'], wf_data['stock_code'])
                result.append({
                    'id': wf_id,
                    'market': wf_data['market'],
                    'stock_code': wf_data['stock_code'],
                    'display_code': display_code,
                    'interval': wf_data['interval'],
                    'table': wf_data['table'],
                    'active': wf_data.get('active', True),
                    'created_at': wf_data.get('created_at'),
                })
        return result

    def get_all_workflows(self) -> list[dict]:
        result = []
        for wf_id, wf_data in self.workflows.items():
            display_code = format_stock_code(wf_data['market'], wf_data['stock_code'])
            result.append({
                'id': wf_id,
                'market': wf_data['market'],
                'stock_code': wf_data['stock_code'],
                'display_code': display_code,
                'interval': wf_data['interval'],
                'table': wf_data['table'],
                'active': wf_data.get('active', True),
                'created_at': wf_data.get('created_at'),
            })
        return result

    def delete_workflow(self, workflow_id: str) -> bool:
        if workflow_id in self.workflows:
            del self.workflows[workflow_id]
            db_manager.delete_workflow_by_id(workflow_id)
            return True
        return False

    def load_workflows(self) -> dict:
        return db_manager.load_workflows()


workflow_service = WorkflowService()
