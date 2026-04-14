import json
import os
from datetime import datetime
from typing import Optional
from app.config import Config
from app.services.stock_service import detect_market, get_table_name, collect_and_store
from app.models.database import db_manager


class WorkflowService:
    def __init__(self):
        self.workflows = {}
        self.load_workflows()

    def get_workflow_id(self, market: str, stock_code: str, interval: str) -> str:
        return f"{market}_{stock_code}_{interval}"

    def check_existing_workflows(self, stock_code: str) -> Optional[list[str]]:
        existing = []
        for interval in ['daily', '120min', '90min', '60min']:
            for market in ['a', 'hk', 'us']:
                wf_id = self.get_workflow_id(market, stock_code, interval)
                if wf_id in self.workflows:
                    existing.append(wf_id)
        return existing if existing else None

    def register_stock(self, stock_input: str) -> dict:
        market, stock_code = detect_market(stock_input)

        existing = self.check_existing_workflows(stock_code)
        if existing:
            return {
                'success': True,
                'message': '工作流已存在',
                'workflows': existing
            }

        created_workflows = []
        for interval in ['daily', '120min', '90min', '60min']:
            wf_id = self.get_workflow_id(market, stock_code, interval)
            table_name = get_table_name(stock_code, interval)

            if not db_manager.table_exists(market, table_name):
                db_manager.create_stock_table(market, table_name)
                collect_and_store(market, stock_code, interval)

            self.workflows[wf_id] = {
                'market': market,
                'stock_code': stock_code,
                'interval': interval,
                'table': table_name,
                'db_path': Config.DB_PATHS[market],
                'created_at': datetime.now().isoformat(),
                'active': True
            }
            created_workflows.append(wf_id)

        self.save_workflows()

        return {
            'success': True,
            'message': '工作流已创建',
            'workflows': created_workflows
        }

    def get_stock_workflows(self, stock_code: str) -> list[dict]:
        result = []
        for wf_id, wf_data in self.workflows.items():
            if wf_data['stock_code'] == stock_code:
                result.append({'id': wf_id, **wf_data})
        return result

    def get_all_workflows(self) -> list[dict]:
        return [{'id': wf_id, **wf_data} for wf_id, wf_data in self.workflows.items()]

    def delete_workflow(self, workflow_id: str) -> bool:
        if workflow_id in self.workflows:
            del self.workflows[workflow_id]
            self.save_workflows()
            return True
        return False

    def save_workflows(self):
        with open(Config.WORKFLOWS_FILE, 'w', encoding='utf-8') as f:
            json.dump({'workflows': self.workflows}, f, ensure_ascii=False, indent=2)

    def load_workflows(self):
        if os.path.exists(Config.WORKFLOWS_FILE):
            with open(Config.WORKFLOWS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.workflows = data.get('workflows', {})


workflow_service = WorkflowService()
